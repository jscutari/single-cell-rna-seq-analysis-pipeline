# Project Plan — Small Models Hack

Multi-agent reanalysis of public single-cell data, running entirely on **Nemotron 3.5 Lightning** served by **vLLM** on one Brev H100.

**Tracks:** Multi-Agent Systems (main) · Best Use of Nemotron Lightning · Best Use of Red Hat vLLM

**Pitch:** Most public single-cell datasets are analyzed once, for one paper. Frontier-model agents like CellVoyager can find what was missed, but they run on closed models, one analysis at a time. Our agents all run on one open NVIDIA model (31.6B total, 3.6B active per token) on one rented GPU. They explore hypotheses in parallel, a statistician agent rejects weak findings, and every step of their reasoning is visible in the app.

---

## 1. Rules we must follow

- Total parameters of all generative models ≤ 33B. Lightning is 31.6B, so **Lightning is our only generative model**. Agents are unlimited (confirmed with organizers).
- Embedding and reranking models don't count toward the cap.
- The CellBench judge can be a larger hosted model. It's evaluation only, not part of the pipeline.
- All code is written during the hackathon. Open-source libraries must be at least 2 weeks old.
- Cite every data source in the README.

---

## 2. Ownership

| Owner | Owns | Folders |
| --- | --- | --- |
| **Alexandre** | Brev box, vLLM server, sandboxed Jupyter kernels, analysis Docker image, orchestrator, agent prompts, critic checks, benchmarks | `infra/` `sandbox/` `agents/` `bench/` |
| **Partner** | Postgres, FastAPI backend, server-sent events, email, web app | `backend/` `frontend/` |
| **Both (hour one)** | Shared data models and the event interface | `shared/` |

**Rule:** stay in your own folders. Changes to `shared/` need both people. Make small PRs into `main`.

---

## 3. Repo layout

```
.
├── PLAN.md
├── README.md                 # data sources, how to run, bounty write-ups
├── docker-compose.yml        # postgres, backend, frontend
├── shared/
│   ├── schemas.py            # pydantic models (section 5)
│   └── events.py             # emit() + event types (section 6)
├── infra/                    # Alexandre
│   ├── setup_brev.sh         # one script to rebuild the box from scratch
│   └── serve_vllm.sh         # vLLM launch command
├── sandbox/                  # Alexandre
│   ├── Dockerfile            # scverse analysis image
│   ├── kernel_manager.py     # start/stop kernels, run cells, save .ipynb
│   └── preprocess.py         # fixed QC + normalization for the dataset
├── agents/                   # Alexandre
│   ├── orchestrator.py
│   ├── llm.py                # vLLM client; logs every call as an LLMCall event
│   ├── prompts/              # one file per agent role
│   └── checks.py             # deterministic stats checks the critic gets
├── bench/                    # Alexandre
│   ├── cellbench_subset.py
│   └── baseline_single_agent.py
├── backend/                  # Partner
│   ├── main.py               # FastAPI app
│   ├── db.py                 # SQLAlchemy models + session
│   ├── routes/
│   ├── sse.py                # live event stream to the browser
│   └── email.py
└── frontend/                 # Partner
```

---

## 4. Architecture

```
Browser (frontend)
   │  REST + SSE
FastAPI backend ──── Postgres (state, trace log)
   │      ▲                │
   │      │ emit(event)    └── file paths → /home/ubuntu/workspace/data/<project>/
   ▼      │                         (.h5ad, .ipynb, .png)
Orchestrator + agents (background async tasks, same process)
   │                    │
vLLM :8000          Jupyter kernels (Docker, no network)
Lightning NVFP4     scanpy, decoupler, pydeseq2, statsmodels
```

**Agents → backend:** agents call `emit(event)` and never touch the database. Until the backend exists, `emit` prints to the console, so neither side blocks the other.

**Backend → agents:** the backend calls three functions in `agents/orchestrator.py`:

```python
async def start_run(project_id: str) -> None
async def handle_user_message(project_id: str, text: str) -> None   # intake chat, Q&A, steering
async def stop_run(project_id: str) -> None
```

---

## 5. Shared schemas (`shared/schemas.py`)

Agree on these first. Field names are a starting point.

| Model | Key fields |
| --- | --- |
| `Project` | id, name, dataset_path, paper_path?, status, created_at |
| `Brief` | project_id, organism, condition_column, condition_labels, donor_column, celltype_column, gene_id_format, prior_analyses[], goals, notes |
| `Hypothesis` | id, project_id, title, rationale, plan_steps[], status (`planning`, `coding`, `running`, `critiquing`, `approved`, `rejected`, `failed`) |
| `CodeCell` | id, hypothesis_id, index, source, stdout, stderr, figure_paths[], status, started_at, ended_at |
| `LLMCall` | id, project_id, hypothesis_id?, agent, messages (JSON), reasoning, output, tool_calls (JSON), tokens_in, tokens_out, latency_ms, parent_call_id?, created_at |
| `Finding` | id, hypothesis_id, claim, test, statistic, p_adj, effect_size, figure_path, critic_verdict, critic_notes, novelty, citations[], notebook_path |
| `ChatMessage` | id, project_id, role (`user`, `assistant`), content, created_at |

---

## 6. Events (`shared/events.py`)

`emit(Event(type, project_id, payload))`. The backend saves each event to Postgres and pushes it over SSE.

| Event type | Payload | Shown in |
| --- | --- | --- |
| `llm_call` | `LLMCall` | Trace |
| `brief_updated` | `Brief` | Brief |
| `hypothesis_status` | `Hypothesis` | Analyses |
| `cell_started` / `cell_finished` | `CodeCell` | Analyses |
| `finding` | `Finding` | Findings |
| `chat_reply` | `ChatMessage` | Chat |
| `stage_done` | stage name + summary | Email + toast |

---

## 7. Agents (all Lightning, one vLLM server)

| Agent | Reasoning | Input | Output |
| --- | --- | --- | --- |
| Orchestrator | off | brief, run state, user messages | next stage, emails |
| Intake | on | dataset summary (obs columns, labels, gene IDs), chat | `Brief` |
| Literature | on | brief; later each approved finding | background; novelty + citations (PubMed / Europe PMC APIs) |
| Planner | on | brief, background, past hypotheses | 2–3 hypotheses with step plans |
| Coder | on | plan step, prior cells, errors | Python cell that **prints the numbers behind every plot**; up to 3 fix attempts |
| Results reader | on | printed tables and stats | plain-language result |
| Stats critic | on | code + outputs only (fresh context) + `checks.py` results | approve / revise (with fix) / reject |
| Reporter | off | approved findings | finding cards, final report, chat answers |

**Critic checklist:** pseudobulk by donor before differential expression · multiple-testing correction · effect size reported · donor/batch confounding checked · enough cells per group.

No vision model fits the budget, so plots are for humans. Agents reason from printed numbers.

---

## 8. Infrastructure (Alexandre)

**vLLM** (from the model card and vLLM's launch post; confirm exact flags there):

```bash
docker pull vllm/vllm-openai:v0.27.1
vllm serve --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.85 \
  --enable-prefix-caching
# then add: DFlash speculative decoding + reasoning parser, per model card
```

- Every agent shares a long common prefix (brief + dataset summary), so prefix caching matters.
- Expose `/metrics` to the backend for the System tab.

**Analysis sandbox:** one Docker image with scanpy, anndata, decoupler, pydeseq2, statsmodels, scipy, gseapy and matplotlib. There's one kernel per hypothesis, with no network, memory/CPU limits and a per-cell timeout. It's driven by `jupyter_client`, and every cell is saved to `<hypothesis>.ipynb`.

**Brev rules:** never stop the instance during the event, since a stopped GPU may not come back. Keep `infra/setup_brev.sh` complete enough to rebuild from zero. Push often.

**Budget: $160.** One H100 at about $2/hr for about 30 hrs is roughly $60. Use the remainder for a second GPU for a few hours to run the single-agent baseline. Check the balance each morning.

---

## 9. Backend + storage (Partner)

- **Postgres** in Docker: projects, briefs, hypotheses, code cells, findings, chat, and the `llm_calls` trace table (JSON columns for messages/reasoning). Many agents write at once, which is why it's Postgres over SQLite.
- **Files on disk:** `/home/ubuntu/workspace/data/<project_id>/` for `.h5ad`, `.ipynb` and `.png`. The DB stores paths.
- **FastAPI:** REST for CRUD, SSE endpoint per project for live events, file serving for plots/notebooks.
- **Email:** Resend or SMTP on `stage_done`.

---

## 10. Web app (Partner)

| Tab | Shows | Tier |
| --- | --- | --- |
| Projects | list; New project → upload `.h5ad` or pick preloaded COVID set, optional paper | 1 |
| Chat | intake conversation → brief; later Q&A and steering | 1 / 2 / 3 |
| Brief | structured brief, editable | 1 |
| Analyses | card per hypothesis with live status; drill in to code cells, outputs, plots streaming | 1 |
| Trace | live timeline of every model call: agent, prompt, reasoning, answer, tool calls, tokens, latency; filter by agent/hypothesis; agent-to-agent messages | 1 |
| Findings | claim, statistic, plot, critic verdict, novelty + citations, notebook link, "How we got here" → Trace | 1 / 2 |
| System | vLLM throughput, latency, queue depth, cache hit rate, agents running, GPU memory | 1 |

Label reasoning traces as "the model's working notes." They're not a guaranteed explanation of why it answered.

Not needed: logins, multi-user, mobile polish.

---

## 11. Scope tiers

**Tier 1, must work for the demo**
- [ ] New project → intake chat → brief
- [ ] Literature background before analysis
- [ ] 2–3 hypotheses in parallel: plan → code → run → read → critique
- [ ] Findings tab with stats, plot, critic verdict, code
- [ ] Trace tab, live
- [ ] System tab with vLLM metrics

**Tier 2**
- [ ] Literature novelty check + citations on each finding
- [ ] Email on stage completion
- [ ] Q&A chat over results
- [ ] Benchmark numbers (section 13)

**Tier 3**
- [ ] Steering a run mid-flight from chat
- [ ] Volunteer browser compute for permutation tests

**Out of scope:** raw FASTQ/GEO processing, non-scRNA data, fine-tuning, NeMo Gym, auth.

---

## 12. Dataset

**First run:** Wilk et al. 2020, COVID-19 PBMC atlas, GEO **GSE150728**. It has 7 hospitalized COVID-19 patients and 6 healthy controls, about 57k cells. It's CellVoyager's first case study, so we can compare directly. The original paper's findings to recover:
- interferon-stimulated gene signature
- HLA class II downregulation
- developing neutrophil population

**Backup:** CellVoyager's endometrium or mouse brain aging case study.

---

## 13. Benchmarks (Alexandre)

| Test | Ours vs. | Metric |
| --- | --- | --- |
| CellBench, 10-paper subset ([CellVoyager repo](https://github.com/zou-group/CellVoyager)) | single-agent Lightning; CellVoyager's reported GPT-4o / o3-mini scores | share of held-out analyses matched (larger hosted judge) |
| COVID PBMC recovery | single-agent Lightning | original findings recovered |
| COVID PBMC vs. CellVoyager | their published case study | overlap + our new findings |
| Execution | single-agent Lightning | % code cells that run after retries |
| Rigor | same run, critic off | findings the critic rejected or fixed |
| Serving | same run, no prefix cache / no speculative decoding | tokens/s, latency, cache hit rate, concurrent agents |
| Cost and speed | CellVoyager's ~30 min per analysis | wall-clock + GPU-$ per analysis |

---

## 14. Timeline (started Sat Oct 17)

**Now, together (≤ 1 hr)**
- [ ] Repo created, this file committed
- [ ] `shared/schemas.py` + `shared/events.py` agreed and committed
- [ ] Brev H100 launched; COVID data downloading

**Saturday afternoon**
- [ ] A: vLLM serving Lightning; `llm.py` client logging calls; one kernel running scanpy on the data
- [ ] P: Postgres + FastAPI + SSE skeleton; Projects and Trace tabs rendering fake events

**Saturday night: first end-to-end**
- [ ] A: one hypothesis runs plan → code → run → critique → `finding` event
- [ ] P: Analyses + Findings tabs showing real events from A's run

**Sunday morning**
- [ ] A: intake + literature agents; 2–3 hypotheses in parallel
- [ ] P: Chat + Brief tabs; System tab from `/metrics`

**Sunday midday**
- [ ] A: benchmark runs (second GPU if needed)
- [ ] P: email, polish, Tier 2 items

**Last 2 hours**
- [ ] Code freeze
- [ ] Record a backup demo video
- [ ] README: data sources, how to run, Lightning + vLLM bounty write-ups

---

## 15. Definition of done

Someone opens the app, starts a project on the COVID dataset, answers a few intake questions, and watches 2–3 hypotheses run live with full traces. At least one critic-approved finding has stats, code and citations. We can show the benchmark table and vLLM metrics.
