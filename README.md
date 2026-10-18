# single-cell-rna-seq-analysis-pipeline
Single-Cell RNA-seq Analysis Pipeline (SCRAP for short) developed for the NVIDIA x Red Hat Small Models Hack. Leverages small language models, vLLM, and specialized AI agents to automate statistical analysis, literature research, and scientific verification of biological datasets.

## Data sources

- **COVID-19 PBMC atlas.** Wilk, A.J., Rustagi, A., Zhao, N.Q. et al. *A single-cell atlas of the peripheral immune response in patients with severe COVID-19.* Nat Med 26, 1070–1076 (2020). https://doi.org/10.1038/s41591-020-0944-y. Raw data: GEO [GSE150728](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE150728). We use the annotated `.h5ad` (44,721 cells) from [CZ CELLxGENE](https://cellxgene.cziscience.com/collections/a72afd53-ab92-4511-88da-252fb0e26b9a).

## How to run the app

The app has two parts: the **backend** (`backend/`, FastAPI) that drives the agents and streams their progress, and the **web app** (`frontend/`, React). Python dependencies are managed with [uv](https://docs.astral.sh/uv/); the frontend uses Node 20+.

### The database (Postgres in Docker)

The backend saves every event (chat, progress, trace) and the project list in Postgres, so a restart loses nothing; on startup it rebuilds its state from the database. Runs that were in progress when it stopped are marked stopped (the agents' working state can't resume).

```bash
cp .env.example .env              # then set a real POSTGRES_PASSWORD (and the same in DATABASE_URL)
docker compose up -d db           # postgres:16, data in the "pgdata" volume, bound to 127.0.0.1:5432
```

The backend refuses to start if it can't reach the database. `SCRAP_STORE=memory` runs without it (nothing is saved). `GET /api/health` reports `"db": "ok"` or `"down"`.

**Backups:** `backend/scripts/backup_db.sh` writes `~/workspace/backups/scrap-<time>.sql.gz` (keeps the newest 10). Make one before the demo and copy it off the box (`scp`). To restore: `gunzip -c <file> | docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`.

**Querying:** `docker compose exec db psql -U scrap scrap`, e.g. `SELECT agent, sum(tokens_in) FROM llm_calls GROUP BY agent;`

### On the Brev box (real agents)

vLLM and the sandbox image must be set up first (`infra/setup_brev.sh`, `infra/serve_vllm.sh`), and the database started (above). Then:

```bash
# One worker and no --reload: runs live in the backend's memory.
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8080
```

`DATA_ROOT` (default `/home/ubuntu/workspace/data`) holds one folder per project; the COVID project is created from `raw/covid_pbmc_wilk2020.h5ad` on first start. The backend only listens on `127.0.0.1`: it can start Docker containers, so never expose it publicly. Reach it through an SSH tunnel.

### On your laptop

```bash
ssh -L 8080:localhost:8080 <brev-box>        # if the backend runs on the box

cd frontend && npm install
VITE_USE_MOCK=false npm run dev               # the app, talking to the backend through /api
# or just: npm run dev                        # sample data only, no backend needed
```

Open http://localhost:5173.

### Without the GPU: replay a recorded run

```bash
mkdir -p /tmp/scrap-data/raw && cp <any .h5ad> /tmp/scrap-data/raw/covid_pbmc_wilk2020.h5ad
DATA_ROOT=/tmp/scrap-data SCRAP_AGENTS=replay uv run uvicorn backend.main:app --port 8080
# add SCRAP_STORE=memory to skip the database
```

`backend/dev/recordings/sample_run.jsonl` plays back through the same event system (`SCRAP_REPLAY_FILE` picks another recording, `SCRAP_REPLAY_SPEED` its speed). Record a real run with `uv run python -m backend.dev.record <project_id> out.jsonl`.

### Tests

```bash
uv run pytest tests -m "not integration and not llm"   # backend + agents (database tests need docker compose up -d db)
cd frontend && npm test && npm run check:contract       # web app, and its types vs shared/
```
