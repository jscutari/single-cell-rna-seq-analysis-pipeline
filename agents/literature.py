"""Literature agent: a per-project search index over the user's papers (and,
optionally, Europe PMC abstracts), a cited background summary before planning,
and a novelty check for each finding.

Retrieval is two-stage: an embedding model finds ~30 candidate passages fast,
then a cross-encoder reranker reads each (query, passage) pair and reorders
them. Neither model is generative, so neither counts toward the 33B cap.

Files, per project:
    <project_dir>/sources/<source_id>.pdf   uploaded by the backend
    <project_dir>/sources/index/            chunks.json + embeddings.npy (built here)

Test on the box:  uv run python -m agents.literature
"""

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
from pydantic import BaseModel

from agents import prompting
from agents.llm import chat, chat_json
from shared.schemas import Finding, Novelty

EMBED_MODEL = "nvidia/Nemotron-3-Embed-1B-BF16"
RERANK_MODEL = "nvidia/llama-nemotron-rerank-1b-v2"
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CHUNK_CHARS = 1200
CANDIDATES = 30  # from the embedding search, before reranking
log = logging.getLogger("scrap.literature")


@dataclass
class Chunk:
    source_id: str  # file stem for uploads, "PMID:<n>" for Europe PMC
    title: str
    page: int | None
    text: str

    def cite(self) -> str:
        return self.source_id if self.page is None else f"{self.source_id} p.{self.page}"


# --- models (loaded once, on first use) ---

_models = None
_gpu_lock = asyncio.Lock()


def _load_models():
    global _models
    if _models is None:
        import torch
        from sentence_transformers import SentenceTransformer
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        embed = SentenceTransformer(EMBED_MODEL, device="cuda",
                                    model_kwargs={"dtype": torch.bfloat16, "attn_implementation": "sdpa"})
        tok = AutoTokenizer.from_pretrained(RERANK_MODEL, trust_remote_code=True, padding_side="left")
        tok.pad_token = tok.pad_token or tok.eos_token
        rerank = AutoModelForSequenceClassification.from_pretrained(
            RERANK_MODEL, trust_remote_code=True, torch_dtype=torch.bfloat16).eval().to("cuda")
        rerank.config.pad_token_id = rerank.config.pad_token_id or tok.eos_token_id
        _models = (embed, tok, rerank)
    return _models


def _embed_passages(texts: list[str]) -> np.ndarray:
    embed, _, _ = _load_models()
    return embed.encode_document(texts, batch_size=16, convert_to_numpy=True, normalize_embeddings=True)


def _embed_query(text: str) -> np.ndarray:
    embed, _, _ = _load_models()
    return embed.encode_query([text], convert_to_numpy=True, normalize_embeddings=True)[0]


def _rerank(query: str, passages: list[str]) -> list[float]:
    import torch
    _, tok, model = _load_models()
    batch = tok([f"question:{query} \n \n passage:{p}" for p in passages], padding=True,
                truncation=True, max_length=512, return_tensors="pt").to("cuda")
    with torch.inference_mode():
        return model(**batch).logits.view(-1).float().cpu().tolist()


# --- index ---

def _pdf_chunks(path: Path) -> list[Chunk]:
    """Split a PDF into ~CHUNK_CHARS passages that keep their page number."""
    import pymupdf

    doc = pymupdf.open(path)
    title = (doc.metadata or {}).get("title") or path.stem
    chunks = []
    for page_no, page in enumerate(doc, 1):
        # Text blocks follow the layout (roughly one per paragraph); block[6] == 0 means text, not image.
        paras = [re.sub(r"\s+", " ", b[4]).strip() for b in page.get_text("blocks") if b[6] == 0]
        buf = ""
        for p in paras:
            if len(p) < 40:  # headers, page numbers, figure labels
                continue
            if buf and len(buf) + len(p) > CHUNK_CHARS:
                chunks.append(Chunk(path.stem, title, page_no, buf))
                buf = ""
            buf = f"{buf} {p}".strip()
        if buf:
            chunks.append(Chunk(path.stem, title, page_no, buf))
    return chunks


class Index:
    def __init__(self, project_dir: Path):
        self.dir = project_dir / "sources" / "index"
        self.chunks: list[Chunk] = []
        self.emb = np.zeros((0, 0), dtype=np.float32)
        if (self.dir / "chunks.json").exists():
            self.chunks = [Chunk(**c) for c in json.loads((self.dir / "chunks.json").read_text())]
            self.emb = np.load(self.dir / "embeddings.npy")

    @property
    def source_ids(self) -> list[str]:
        return sorted({c.source_id for c in self.chunks})

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "chunks.json").write_text(json.dumps([asdict(c) for c in self.chunks]))
        np.save(self.dir / "embeddings.npy", self.emb)

    async def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        async with _gpu_lock:
            emb = await asyncio.to_thread(_embed_passages, [c.text for c in chunks])
        self.emb = emb if not self.chunks else np.vstack([self.emb, emb])
        self.chunks += chunks
        self._save()

    async def add_new_pdfs(self, sources_dir: Path) -> list[str]:
        """Index any PDF in sources/ not indexed yet. Returns the new source ids."""
        known = set(self.source_ids)
        new = []
        for p in sorted(sources_dir.glob("*.pdf")):
            if p.stem in known:
                continue
            with open(p, "rb") as f:
                if f.read(5) != b"%PDF-":  # e.g. a saved bot-check page with a .pdf name
                    log.warning("Skipping %s: not a PDF file", p.name)
                    continue
            await self.add(await asyncio.to_thread(_pdf_chunks, p))
            new.append(p.stem)
        return new

    async def search(self, query: str, k: int = 6) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        async with _gpu_lock:
            q = await asyncio.to_thread(_embed_query, query)
            top = np.argsort(-(self.emb @ q))[:CANDIDATES]
            scores = await asyncio.to_thread(_rerank, query, [self.chunks[i].text for i in top])
        ranked = sorted(zip(top, scores), key=lambda t: -t[1])[:k]
        return [(self.chunks[i], s) for i, s in ranked]


# --- Europe PMC (optional online search) ---

async def europe_pmc(query: str, n: int = 10) -> list[Chunk]:
    """Titles and abstracts from Europe PMC as chunks. One GET, no API key."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(EUROPE_PMC, params={"query": f"({query}) AND HAS_ABSTRACT:y", "format": "json",
                                                 "resultType": "core", "pageSize": n})
        r.raise_for_status()
    out = []
    for hit in r.json().get("resultList", {}).get("result", []):
        if hit.get("pmid") and hit.get("abstractText"):
            abstract = re.sub(r"<[^>]+>", "", hit["abstractText"])
            out.append(Chunk(f"PMID:{hit['pmid']}", hit.get("title", ""), None,
                             f"{hit.get('title', '')} ({hit.get('pubYear', '')}). {abstract}"))
    return out


# --- agents ---

def _passages(hits: list[tuple[Chunk, float]]) -> str:
    return "\n\n".join(f"[{c.cite()}] {c.title}\n{c.text}" for c, _ in hits) or "(no passages found)"


async def background(project_id: str, project_dir: Path, prefix: str, goals: str,
                     online: bool = False) -> tuple[str, list[str]]:
    """Cited background summary for the planner. Returns (text, source ids searched)."""
    index = Index(project_dir)
    await index.add_new_pdfs(project_dir / "sources")
    if online:
        known = set(index.source_ids)
        await index.add([c for c in await europe_pmc(goals) if c.source_id not in known])
    hits: dict[str, tuple[Chunk, float]] = {}
    for query in [goals] + [s.strip() for s in re.split(r"(?<=[.?!])\s+", goals) if len(s) > 20][:3]:
        for c, s in await index.search(query, k=5):
            hits.setdefault(c.cite(), (c, s))
    if not hits:
        return "", index.source_ids
    call = await chat("literature", prompting.messages(
        prefix, "literature", f"Goals: {goals}\n\nPassages:\n{_passages(list(hits.values()))}\n\n"
                              "Write the background summary."), project_id=project_id)
    return call.output.strip(), index.source_ids


class Grade(BaseModel):
    citation: str
    relation: Literal["same_claim", "contradicts", "related", "unrelated"]
    reason: str


class Grades(BaseModel):
    grades: list[Grade]


async def novelty(project_id: str, project_dir: Path, prefix: str, finding: Finding,
                  online: bool = False) -> None:
    """Set finding.novelty, citations and sources_searched in place."""
    index = Index(project_dir)
    if online:
        known = set(index.source_ids)
        await index.add([c for c in await europe_pmc(finding.claim, n=8) if c.source_id not in known])
    if not index.chunks:  # nothing to search: "not checked" is not "not found"
        return
    hits = await index.search(finding.claim, k=6)
    finding.sources_searched = index.source_ids
    if not hits:
        finding.novelty = Novelty.not_found_in_sources
        return
    _, parsed = await chat_json("novelty", prompting.messages(
        prefix, "novelty", f"Finding: {finding.claim}\n\nPassages:\n{_passages(hits)}\n\nGrade each passage."),
        Grades, chat_fn=chat, project_id=project_id, hypothesis_id=finding.hypothesis_id)
    grades = parsed.grades
    same = [g.citation for g in grades if g.relation == "same_claim"]
    related = [g.citation for g in grades if g.relation in ("related", "contradicts")]
    finding.novelty = (Novelty.known if same else Novelty.partly_known if related
                       else Novelty.not_found_in_sources)
    finding.citations = same or related


async def _demo() -> None:
    """Index the Wilk et al. paper and query it."""
    import time

    # Publishers block scripted downloads; save the PDF from a browser and copy it here.
    project_dir = Path("/home/ubuntu/workspace/data/_reference/covid_pbmc")
    pdf = project_dir / "sources" / "wilk2020.pdf"
    t = time.perf_counter()
    index = Index(project_dir)
    print("new sources:", await index.add_new_pdfs(pdf.parent), f"({len(index.chunks)} chunks, {time.perf_counter() - t:.1f}s)")
    for q in ["interferon response in monocytes", "HLA class II downregulation", "developing neutrophils"]:
        print(f"\nQUERY: {q}")
        for c, s in await index.search(q, k=3):
            print(f"  [{c.cite()}] score={s:.2f}  {c.text[:160]}...")
    print("\nEurope PMC:", [c.source_id for c in await europe_pmc("COVID-19 monocytes interferon single-cell", n=5)])


if __name__ == "__main__":
    asyncio.run(_demo())
