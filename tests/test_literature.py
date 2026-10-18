"""agents/literature.py: PDF chunking, the index, reranking, Europe PMC, background and novelty.

The embedding and reranking models are replaced by word-overlap fakes, so these
tests check our logic, not the models.
"""

import json
import re

import httpx
import numpy as np
import pytest

from agents import literature as lit
from agents.literature import Chunk, Grade, Grades, Index, Queries
from shared.schemas import Finding

VOCAB = ["interferon", "monocytes", "hla", "neutrophils", "covid", "platelets", "ventilation", "class"]


def bag(text: str) -> np.ndarray:
    words = re.findall(r"[a-z]+", text.lower())
    v = np.array([float(words.count(w)) for w in VOCAB]) + 1e-3
    return v / np.linalg.norm(v)


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    calls = {"rerank": []}
    monkeypatch.setattr(lit, "_embed_passages", lambda texts: np.stack([bag(t) for t in texts]))
    monkeypatch.setattr(lit, "_embed_query", bag)

    def rerank(query, passages):
        calls["rerank"].append(len(passages))
        q = set(re.findall(r"[a-z]+", query.lower()))
        return [float(len(q & set(re.findall(r"[a-z]+", p.lower())))) for p in passages]
    monkeypatch.setattr(lit, "_rerank", rerank)
    return calls


PARAS = {
    1: ["Interferon stimulated genes are strongly induced in monocytes from patients with severe COVID.",
        "Platelets show modest changes across all donors in this cohort of hospitalized patients."],
    2: ["HLA class II genes are downregulated on monocytes from ventilated patients with COVID.",
        "A population of developing neutrophils appears in the blood of ventilated patients."],
}


def make_pdf(path, paras=PARAS, title="Wilk 2020"):
    import pymupdf
    doc = pymupdf.open()
    for page_no in sorted(paras):
        page = doc.new_page()
        y = 50
        for para in paras[page_no]:  # one text box per paragraph, like a real layout
            page.insert_textbox(pymupdf.Rect(50, y, 550, y + 100), para, fontsize=10)
            y += 115
    doc.set_metadata({"title": title})
    doc.save(path)


def test_pdf_chunks_keep_pages_and_drop_short_lines(tmp_path):
    pdf = tmp_path / "wilk2020.pdf"
    make_pdf(pdf, {1: PARAS[1] + ["Fig. 1"], 2: PARAS[2]})
    chunks = lit._pdf_chunks(pdf)
    assert {c.page for c in chunks} == {1, 2}
    assert all(c.source_id == "wilk2020" and c.title == "Wilk 2020" for c in chunks)
    text = " ".join(c.text for c in chunks)
    assert "developing neutrophils" in text and "Fig. 1" not in text
    assert all(len(c.text) <= lit.CHUNK_CHARS + 300 for c in chunks)


def test_long_pages_split_into_several_chunks(tmp_path):
    pdf = tmp_path / "long.pdf"
    para = "Monocytes express interferon stimulated genes in this cohort of patients. " * 6
    make_pdf(pdf, {1: [para] * 6})
    assert len([c for c in lit._pdf_chunks(pdf) if c.page == 1]) > 1


def test_chunk_citation():
    assert Chunk("wilk2020", "t", 3, "x").cite() == "wilk2020 p.3"
    assert Chunk("PMID:1", "t", None, "x").cite() == "PMID:1"


async def test_index_adds_pdfs_once_and_skips_fake_pdfs(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    make_pdf(sources / "wilk2020.pdf")
    (sources / "botcheck.pdf").write_text("<html>Enable JavaScript and cookies to continue</html>")
    index = Index(tmp_path)
    assert await index.add_new_pdfs(sources) == ["wilk2020"]
    assert await index.add_new_pdfs(sources) == []
    assert index.source_ids == ["wilk2020"] and index.emb.shape[0] == len(index.chunks)


async def test_index_persists_to_disk(tmp_path):
    index = Index(tmp_path)
    await index.add([Chunk("a", "t", 1, "interferon monocytes"), Chunk("b", "t", 2, "platelets")])
    reloaded = Index(tmp_path)
    assert [c.source_id for c in reloaded.chunks] == ["a", "b"]
    assert np.allclose(reloaded.emb, index.emb)


async def test_search_reranks_candidates(tmp_path, fake_models):
    index = Index(tmp_path)
    await index.add([Chunk("p", "t", i, text) for i, text in enumerate(
        ["platelets platelets", "hla class monocytes", "interferon monocytes covid", "neutrophils ventilation"])])
    hits = await index.search("interferon in monocytes", k=2)
    assert [c.text for c, _ in hits][0] == "interferon monocytes covid"
    assert len(hits) == 2 and hits[0][1] >= hits[1][1]
    assert fake_models["rerank"] == [4]  # every candidate went through the reranker


async def test_search_on_empty_index(tmp_path):
    assert await Index(tmp_path).search("anything") == []


# --- Europe PMC ---

def mock_http(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(lit.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


async def test_europe_pmc_parses_abstracts(monkeypatch):
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"resultList": {"result": [
            {"pmid": "111", "title": "IFN in COVID", "pubYear": "2021", "authorString": "Wilk AJ, Rustagi A.",
             "abstractText": "<p>Monocytes <i>up</i>.</p>"},
            {"pmid": "222", "title": "No abstract"},
            {"title": "No pmid", "abstractText": "x"}]}})
    mock_http(monkeypatch, handler)
    chunks = await lit.europe_pmc("interferon monocytes", n=5)
    assert [c.source_id for c in chunks] == ["PMID:111"]
    assert chunks[0].text == "IFN in COVID (2021). Monocytes up." and chunks[0].page is None
    assert chunks[0].title == "Wilk AJ et al. 2021"  # how the citation reads in summaries
    assert seen["params"]["pageSize"] == "5" and "HAS_ABSTRACT:y" in seen["params"]["query"]


async def test_europe_pmc_http_error_raises(monkeypatch):
    mock_http(monkeypatch, lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await lit.europe_pmc("x")


# --- agents ---

async def test_background_without_sources_is_empty(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setattr(lit, "chat", fake_llm)
    assert await lit.background("p", tmp_path, "PREFIX", "Monocytes in COVID.") == ("", [])
    assert fake_llm.calls == []


async def test_background_cites_retrieved_passages(tmp_path, monkeypatch, fake_llm):
    sources = tmp_path / "sources"
    sources.mkdir()
    make_pdf(sources / "wilk2020.pdf")
    fake_llm.reply("literature", "ISGs are induced in monocytes [wilk2020 p.1].")
    monkeypatch.setattr(lit, "chat", fake_llm)
    text, searched = await lit.background("p", tmp_path, "PREFIX",
                                          "Interferon response in monocytes. HLA class II changes in COVID.")
    assert text.endswith("[wilk2020 p.1].") and searched == ["wilk2020"]
    prompt = fake_llm.calls[0]["messages"][1]["content"]
    assert "[wilk2020 p.1]" in prompt and "[wilk2020 p.2]" in prompt


def queries(*qs) -> str:
    return Queries(queries=list(qs)).model_dump_json()


async def test_background_online_searches_keyword_queries(tmp_path, monkeypatch, fake_llm):
    asked = []

    async def fake_epmc(query, n=10):
        asked.append(query)
        return [Chunk("PMID:9", "Wilk AJ et al. 2020", None, "interferon monocytes covid abstract")]
    monkeypatch.setattr(lit, "europe_pmc", fake_epmc)
    fake_llm.reply("literature", queries("COVID-19 monocytes interferon", "COVID-19 HLA-DR monocytes"), "Known [PMID:9].")
    monkeypatch.setattr(lit, "chat", fake_llm)
    text, searched = await lit.background("p", tmp_path, "PREFIX", "How do monocytes respond in COVID-19 patients?",
                                          online=True)
    assert asked == ["COVID-19 monocytes interferon", "COVID-19 HLA-DR monocytes"]  # keywords, not the sentence
    assert searched == ["PMID:9"] and text == "Known [PMID:9]."
    first = fake_llm.calls[0]
    assert first["kwargs"]["schema"] is Queries and first["kwargs"]["reasoning"] is False
    assert "PMID:9" in fake_llm.calls[1]["messages"][1]["content"]


async def test_online_search_dedupes_and_survives_a_failed_query(tmp_path, monkeypatch):
    async def flaky_epmc(query, n=10):
        if query == "bad":
            raise httpx.ConnectError("offline")
        return [Chunk("PMID:1", "A", None, "interferon monocytes"), Chunk("PMID:2", "B", None, "hla class")]
    monkeypatch.setattr(lit, "europe_pmc", flaky_epmc)
    index = Index(tmp_path)
    assert await lit.add_online(index, ["good", "bad", "good again"]) == ["PMID:1", "PMID:2"]
    assert await lit.add_online(index, ["good"]) == []  # already indexed
    assert index.source_ids == ["PMID:1", "PMID:2"]


def grades(*pairs) -> str:
    return Grades(grades=[Grade(citation=c, relation=r, reason="x") for c, r in pairs]).model_dump_json()


@pytest.fixture
async def indexed(tmp_path):
    index = Index(tmp_path)
    await index.add([Chunk("wilk2020", "t", 1, "interferon monocytes covid"),
                     Chunk("wilk2020", "t", 2, "hla class monocytes")])
    return tmp_path


def claim() -> Finding:
    return Finding(hypothesis_id="h", claim="Interferon response is higher in COVID monocytes", test="t")


@pytest.mark.parametrize("relations, novelty, citations", [
    ([("wilk2020 p.1", "same_claim"), ("wilk2020 p.2", "related")], "known", ["wilk2020 p.1"]),
    ([("wilk2020 p.1", "related"), ("wilk2020 p.2", "contradicts")], "partly_known", ["wilk2020 p.1", "wilk2020 p.2"]),
    ([("wilk2020 p.1", "unrelated"), ("wilk2020 p.2", "unrelated")], "not_found_in_sources", []),
])
async def test_novelty_labels_follow_the_grades(indexed, monkeypatch, fake_llm, relations, novelty, citations):
    monkeypatch.setattr(lit, "chat", fake_llm.reply("novelty", grades(*relations)))
    f = claim()
    await lit.novelty("p", indexed, "PREFIX", f)
    assert f.novelty == novelty and f.citations == citations and f.sources_searched == ["wilk2020"]
    assert fake_llm.calls[0]["kwargs"]["schema"] is Grades


async def test_novelty_with_no_sources_stays_unchecked(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setattr(lit, "chat", fake_llm)
    f = claim()
    await lit.novelty("p", tmp_path, "PREFIX", f)
    assert f.novelty is None and f.sources_searched == [] and fake_llm.calls == []


async def test_novelty_online_adds_new_abstracts_only(indexed, monkeypatch, fake_llm):
    added = []

    async def fake_epmc(query, n=10):
        added.append(query)
        return [Chunk("PMID:5", "T", None, "interferon monocytes")]
    monkeypatch.setattr(lit, "europe_pmc", fake_epmc)
    fake_llm.reply("literature", queries("interferon monocytes COVID-19"))
    monkeypatch.setattr(lit, "chat", fake_llm.reply("novelty", grades(("PMID:5", "same_claim"))))
    f = claim()
    await lit.novelty("p", indexed, "PREFIX", f, online=True)
    await lit.novelty("p", indexed, "PREFIX", claim(), online=True)
    assert f.novelty == "known" and f.citations == ["PMID:5"]
    assert added == ["interferon monocytes COVID-19"] * 2  # searched with keywords from the claim
    assert [c.source_id for c in Index(indexed).chunks].count("PMID:5") == 1
