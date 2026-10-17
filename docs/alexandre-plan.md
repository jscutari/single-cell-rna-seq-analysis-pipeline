# Alexandre's build plan: infra, sandbox, agents, bench

## Progress
- [x] 0. Shared schemas + events
- [x] 1. Brev box + `setup_brev.sh` (H100 SXM on Nebius: `consistent-brown-moth`)
- [x] 2. `serve_vllm.sh` (DSpark: 62% draft tokens accepted)
- [x] 3. `agents/llm.py` (10 concurrent calls: 6.9 s wall vs 55.7 s sequential)
- [x] 4. Sandbox Dockerfile
- [x] 5. `preprocess.py` (44,649 cells → `~/workspace/data/covid_pbmc/`)
- [x] 6. `kernel_manager.py` + `scrap_tools.py` helpers (reproduce ISG up / HLA-II down)
- [x] 7. Prompts + `checks.py`
- [x] 8. Single-hypothesis loop: first critic-approved finding (IFN-α in CD14 monocytes, d = 1.72, p = 0.014, 90 s)
- [ ] 9. Full orchestrator
- [ ] 10. Intake agent
- [ ] 11. Literature (11a index · 11b background · 11c novelty · 11d Europe PMC)
- [ ] 12. Reporter
- [ ] 13. Benchmarks

## Context
The repo is only placeholders right now (one comment line per file, committed in `41b107d`). PLAN.md makes Alexandre responsible for `infra/`, `sandbox/`, `agents/` and `bench/`, plus `shared/` jointly with the partner. This plan splits that work into small steps. Each step has one thing to check before moving on, so you can follow along and learn as we build.

**How we work each step:** I write the code, then explain what it does and why. You run the "Done when" check yourself. We commit, push, and move to the next step. One step is one small commit (or PR) into `main`.

**Dev setup:** everything runs on the Brev H100. You edit through VS Code Remote-SSH, and there is no mock LLM. The only thing written before the box is up is the step 1 script.

---

## Phase A: the box and the model (Saturday afternoon)

### Step 0: Shared contract, with partner (≤ 1 hr)
- `shared/schemas.py`: the 7 Pydantic models from PLAN.md §5 (Project, Brief, Hypothesis, CodeCell, LLMCall, Finding, ChatMessage), with string enums for statuses.
  - **Change from PLAN.md:** add a `Source` model to replace `Project.paper_path`. Fields: id, project_id, kind (`upload` / `europe_pmc`), title, path_or_url, pmid?, added_at.
  - Change `Finding.novelty` to an enum: `known` / `partly_known` / `not_found_in_sources`.
  - Add `Finding.sources_searched[]`.
  - The partner's backend accepts the uploaded PDFs and saves them to `data/<project>/sources/`.
- `shared/events.py`:
  - an `Event` model holding `type`, `project_id`, `payload` and a timestamp
  - an `EventType` enum covering the 8 types in §6
  - `emit(event)`, which by default prints JSON to the console
  - `set_sink(fn)`, so the backend can later swap in "save to Postgres and push over SSE"
- **You learn:** Pydantic models, and why a shared event interface lets the two of you work without blocking each other.
- **Done when:** `python -c "from shared.events import emit, Event; ..."` prints a valid event, and your partner signs off on the field names.

### Step 1: Launch Brev and write `infra/setup_brev.sh`
- In the Brev console, launch one H100 (80 GB). Then set up VS Code Remote-SSH to it.
- `setup_brev.sh` must be idempotent (safe to run twice). It:
  - checks Docker and the NVIDIA container toolkit (`docker run --gpus all ... nvidia-smi`)
  - installs `uv` and creates the Python env from a `pyproject.toml` (to be added)
  - creates `/home/ubuntu/workspace/data/`
  - pre-pulls the vLLM image
  - starts downloading the COVID dataset (GSE150728)
- **You learn:** how to make a rented GPU box reproducible ("cattle, not pets"), and how Docker passes the GPU through to a container.
- **Done when:**
  - `nvidia-smi` shows the H100
  - the GPU test container runs
  - the repo is cloned on the box
  - the data download has started

### Step 2: `infra/serve_vllm.sh`
- Write the `docker run` command for `vllm/vllm-openai:v0.27.1` with the Lightning NVFP4 model, `--kv-cache-dtype fp8`, `--gpu-memory-utilization 0.85` and `--enable-prefix-caching`.
- Start from the model card's **"1× H100 interactive"** recipe: Marlin MoE backend, `--reasoning-parser nemotron_v3`, `--tool-call-parser qwen3_coder`, and **DSpark** speculative decoding (3 tokens). The card says DSpark is best at our concurrency (≤ 128 requests at once). With no speculative decoding, the card's max-throughput recipe is fastest; that becomes our serving ablation in step 13.
- Serve on `:8000`, and mount the Hugging Face cache so the weights download only once.
- **You learn:** what each flag buys (NVFP4 weights, FP8 KV cache, prefix caching across agents, speculative decoding), and how to read `/metrics`.
- **Done when:**
  - `curl :8000/v1/models` lists the model
  - a chat completion returns separate `reasoning_content` and `content`
  - `curl :8000/metrics` shows prefix-cache counters

### Step 3: `agents/llm.py`, the one door to the model
- An async OpenAI client pointed at `localhost:8000`.
- `async def chat(agent, messages, *, project_id, hypothesis_id=None, reasoning=True, tools=None, parent_call_id=None) -> LLMCall`
- It toggles reasoning per call, times each call, reads the token counts from `usage`, splits reasoning from output, and `emit`s an `llm_call` event.
- **You learn:** async I/O, the OpenAI-compatible API, and why logging *every* call in one place gives you the Trace tab almost for free.
- **Done when:** a script fires 10 concurrent `chat()` calls, prints 10 `llm_call` events, and the vLLM logs show them batched together.

---

## Phase B: the analysis sandbox (Saturday afternoon/evening)

### Step 4: `sandbox/Dockerfile`
- Start from a Python 3.11 slim base. Install scanpy, anndata, decoupler, pydeseq2, statsmodels, scipy, gseapy, matplotlib, ipykernel and jupyter_client, with versions pinned (all at least 2 weeks old).
- **Done when:** `docker run --rm scrap-sandbox python -c "import scanpy, decoupler, pydeseq2, gseapy"` succeeds.

### Step 5: `sandbox/preprocess.py`
- Load the Wilk et al. `.h5ad` from CZ CELLxGENE, which `setup_brev.sh` downloads. It's already annotated with cell types, donors and conditions; GEO only has per-sample R files.
- Run the standard steps: QC filtering, normalize + log1p, highly variable genes, PCA, neighbors, UMAP.
- Keep the raw counts in `layers["counts"]`, because pseudobulk DE needs them.
- Write `processed.h5ad`, plus a `dataset_summary.json` (obs columns, unique labels, gene ID format) for the intake agent.
- **You learn:** a standard single-cell QC pipeline, and why the agents start from a *fixed* preprocessing (fewer places to go wrong).
- **Done when:** `processed.h5ad` has about 44.7k cells, the summary JSON lists the condition, donor and cell-type columns, and the UMAP plot looks sane.

### Step 6: `sandbox/kernel_manager.py`
- Run one container per hypothesis with `--network none`, memory/CPU limits, and the project data dir mounted read-only. The kernel inside talks to us through **IPC (unix socket) transport** on a shared volume. Normal kernels connect over TCP ports, which `--network none` blocks.
- API: `start_kernel(hypothesis_id)`, `run_cell(hypothesis_id, source, timeout) -> CodeCell`, `stop_kernel(hypothesis_id)`.
- `run_cell` collects stdout and stderr, saves figures as PNGs, emits `cell_started` / `cell_finished`, and appends the cell to `<hypothesis>.ipynb` via `nbformat`.
- A cell that hits the timeout gets its kernel interrupted.
- **You learn:** how Jupyter actually works underneath (the ZMQ messaging protocol), and how to sandbox untrusted LLM-written code.
- **Done when:**
  - 3 cells run: load data, print a table, make a plot
  - the `.ipynb` opens in Jupyter with outputs
  - `while True: pass` times out cleanly
  - `urllib.request.urlopen("https://example.com")` fails

---

## Phase C: first end-to-end finding (Saturday night milestone)

### Step 7: Prompts and `agents/checks.py`
- `agents/prompts/`: one Markdown file per role: `intake`, `literature`, `planner`, `coder`, `reader`, `critic`, `reporter`, `orchestrator`. All of them share the same **prefix** (brief + dataset summary), so the vLLM prefix cache gets hits.
- The coder prompt makes it print the numbers behind every plot, and output one cell at a time.
- `checks.py` runs deterministic checks for the critic's checklist:
  - pseudobulk by donor before DE (inspect the code)
  - multiple-testing correction (padj present)
  - effect size reported
  - donor/batch confounding
  - minimum cells per group (computed in the kernel)
- It returns a structured report that the critic sees.
- **You learn:** prompt design for small models (short, structured, consistent prefix), and why hard rules belong in code rather than in the LLM.

### Step 8: Single-hypothesis loop
- Inside the orchestrator, write one function `run_hypothesis(h)` that goes plan → for each step: code → run (up to 3 fix attempts using the stderr) → read results → critic (in a fresh context, given only the code, outputs and `checks.py` report) → approve / revise / reject.
- It updates `Hypothesis.status` and emits `hypothesis_status`.
- Test it on one hand-written hypothesis: *"interferon-stimulated genes are up in COVID monocytes vs healthy, pseudobulked by donor."*
- **You learn:** agent loops, error-driven retries, and why the critic gets a fresh context.
- **Done when:** a `finding` event comes out with a statistic, p_adj, effect size, figure path and critic verdict, and the hypothesis `.ipynb` reproduces it. → **Push. Partner wires this into the Analyses and Findings tabs.**

---

## Phase D: the full multi-agent run (Sunday morning)

### Step 9: `agents/orchestrator.py`, full version
- Implement `start_run`, `handle_user_message` and `stop_run` (the contract in PLAN.md §4).
- Stages run in order: intake → literature → planner → 2–3 `run_hypothesis` tasks in parallel (`asyncio.TaskGroup`) → reporter. Emit `stage_done` after each stage.
- `stop_run` cancels the tasks and shuts down the kernels.
- **Done when:** 3 hypotheses run at once, and vLLM `/metrics` shows several concurrent requests and prefix-cache hits.

### Step 10: Intake agent
- Reads `dataset_summary.json` and the chat, asks the user only what it can't infer, and fills in `Brief`. Emits `brief_updated` and `chat_reply`.
- **Done when:** a short chat produces a correct Brief for the COVID dataset.

### Step 11: Literature (four sub-steps; uploads first, online search last)
All sources go into **one index per project**, so adding online search later doesn't change anything downstream.

**11a: Source ingestion and retrieval** (`agents/literature/index.py`)
- Parse the uploaded PDFs with `pymupdf`. Chunk them by section/paragraph, keeping the page numbers.
- Embed the chunks with a small retriever embedding model, and rerank the hits with a reranker. Serve both on the same GPU; vLLM uses 0.85 of the memory, which leaves room. Pick the exact models at this step, at least 2 weeks old.
- Store the index in-process (numpy or FAISS), saved to `data/<project>/sources/index/`.
- **You learn:** retrieval-augmented generation (RAG): chunking, embeddings, and why reranking fixes poor top-k results.
- **Done when:** asking "interferon response in monocytes" against the Wilk paper returns the right paragraphs, with page numbers.

**11b: Background summary** (Tier 1)
- Before planning, the literature agent retrieves passages for the brief's goals. It writes a short background where every sentence cites a passage (doc + page). The planner gets the background as context.
- **Done when:** every citation in the background points to a real passage, and the planner's hypotheses use it.

**11c: Novelty check per approved finding** (Tier 2)
- Turn the finding into its parts: genes/pathway, cell type, condition, direction. Retrieve and rerank passages for them.
- Lightning grades each top passage as `same_claim` / `contradicts` / `related` / `unrelated`.
- The labels then follow mechanically:
  - any `same_claim` → `known`, with citations
  - only `related` → `partly_known`
  - otherwise `not_found_in_sources`
- Store `sources_searched`, so the UI can say what was searched. It never claims "novel."
- **Done when:** on COVID, the ISG finding comes out `known` with a citation to the Wilk paper.

**11d: Online search with Europe PMC** (Tier 2, small)
- One REST endpoint with no API key: query → titles, abstracts, PMIDs as JSON. Add those abstracts to the same index as `Source(kind="europe_pmc")`.
- It runs in the orchestrator process, which has network, unlike the sandbox. A per-project toggle in the Brief turns it on.
- **Done when:** with online search on, the novelty check cites PMIDs that aren't in the uploads.

### Step 12: Reporter
- Produces finding cards, a final report, and answers Q&A chat questions over the results (Tier 2).

---

## Phase E: benchmarks (Sunday midday)

### Step 13: `bench/`
- `baseline_single_agent.py`: one Lightning agent, no critic and no parallelism, given the same data and budget.
- `cellbench_subset.py`: 10 papers from the CellVoyager repo, scored by a larger hosted judge model.
- Ablations:
  - critic off
  - vLLM without prefix caching and without speculative decoding (restart vLLM with different flags)
- Collect, for each run:
  - COVID findings recovered (ISG signature, HLA-II down, developing neutrophils)
  - % of cells that run after retries
  - tokens/s
  - wall-clock time and GPU cost
- **Done when:** the benchmark table in PLAN.md §13 is filled in with real numbers.

---

## Verification (whole system)
Run `start_run` on the COVID project from the partner's UI. Then confirm that:
- the intake chat produces a Brief
- the literature background appears
- 2–3 hypotheses stream code cells live
- the Trace tab shows every `llm_call`
- at least one critic-approved finding has its stats, plot, code and citations
- the System tab shows vLLM metrics

This is PLAN.md §15, the definition of done.

## Order vs. timeline (submission due Sun 11:00)
| When | Steps | Notes |
| --- | --- | --- |
| Sat 16:15–19:00 | 1–3, and 4 in parallel | Build the sandbox image while the weights download |
| Sat 19:00–23:00 | 5–6 | Data preprocessed, kernels running |
| Sat 23:00–03:00 | 7–8 | **Critical milestone: first critic-approved finding** |
| Sun 03:00–07:00 | 9, 10, 11a–b | Parallel hypotheses, intake, background summary |
| Sun 07:00–09:00 | 11c, 12, slim 13 | Benchmarks on COVID only: single-agent baseline, critic off, serving ablation |
| Sun 09:00 | **Code freeze** | |
| Sun 09:00–11:00 | — | Backup demo video, README, bounty write-ups, submit |

**Cut first if behind:** the CellBench 10-paper subset, 11d (Europe PMC), Q&A chat, and mid-run steering. These are Tier 2/3 or extra benchmarks; the demo works without them.
