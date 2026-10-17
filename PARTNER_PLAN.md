# Partner Work Plan — Backend, Storage & Web App

My part of SCRAP is everything between Alexandre's agents and the person using the app. That means storing what the agents produce, streaming it live, and presenting it in the web app. The pieces are listed in rough build order.

---

## 1. Set Up Frontend Shell
**Folder:** `frontend/`
**Goal:** Set up the frontend project, the shared live-data connection, and the visual design from the ChatGPT mockup.

## 2. Shared Contract (with Alexandre)
**Folder:** `shared/`
**Goal:** Agree on the data models (`schemas.py`) and the event interface (`events.py`) that connect the agents to the backend. Agents report everything through `emit(event)` and never touch the database. This lets both of us work in parallel without blocking each other.

## 3. Local Infrastructure
**Files:** `docker-compose.yml`
**Goal:** Start the whole stack (Postgres, backend, frontend) with one command, both locally and on the Brev box. Each service gets the volumes and settings it needs.

## 4. Database & Storage
**Files:** `backend/db.py`, data directory on disk
**Goal:** Store every project, brief, hypothesis, code cell, finding, chat message and LLM call in Postgres. Large files (`.h5ad`, `.ipynb`, `.png`) stay on disk, and the database stores their paths. Keep a full event log that serves as both the trace history and the replay source for live streams.

## 5. Event Ingest & Live Stream
**Files:** `backend/sse.py`
**Goal:** Take every event the agents emit, save it, and push it to any open browser in real time over server-sent events (SSE). A browser that reconnects should catch up on anything it missed.

## 6. Fake Run Generator
**Files:** `backend/dev/fake_run.py`
**Goal:** Send a realistic scripted analysis run (brief, hypotheses, code cells, LLM calls, findings) so the backend and UI can be built and demoed before Alexandre's agents are ready.

## 7. REST API
**Files:** `backend/main.py`, `backend/routes/`
**Goal:** Give the frontend endpoints to create projects (upload a dataset or pick the COVID preset), start and stop runs, chat, read and edit the brief, list hypotheses, cells, findings and trace entries, and serve plots and notebooks. This layer is where the backend calls the orchestrator's `start_run`, `handle_user_message` and `stop_run`.

## 8. System Metrics
**Files:** `backend/routes/system.py`
**Goal:** Read vLLM's `/metrics` endpoint and turn it into clean numbers: throughput, latency, queue depth, cache hit rate, GPU memory and agents running. These support the vLLM bounty story.

## 9. Notifications
**Files:** `backend/email.py`, in-app toasts
**Goal:** Tell the user when a stage finishes, by email and with an in-app toast, so long runs don't need to be watched.

## 10. Docs & Demo Support
**Files:** `README.md`
**Goal:** Write the "how to run" steps for the backend and frontend, and help prepare the backup demo video before code freeze.
