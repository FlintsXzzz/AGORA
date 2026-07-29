# Developer Notes — AGORA

## Overview
- Entry points:
  - Node WhatsApp gateway: `index.js`
  - Python AI Engine (FastAPI): `main.py`

## Run with Docker (recommended)
- Requires Docker and Docker Compose
- From repo root:
  ```bash
  docker compose up --build
  ```

## Run locally (without Docker)

### Python AI Engine
```bash
python -m uvicorn main:app --reload --port 8000
```
Required env: `NVIDIA_API_KEY`, `AGORA_STORAGE_DIR` (optional)

### Node WhatsApp Gateway
Ensure Node 18+ and native dependencies for puppeteer are available.
```bash
node index.js
```
Env: `AI_ENGINE_BASE_URL` (default `http://ai-engine:8000`), `WWEBJS_SESSION_DIR` (optional)

## Tests
- Python: install deps and run pytest
  ```bash
  python -m pip install -r agora_requirements.txt
  pytest
  ```

## CI
- A basic GitHub Actions workflow is provided at `.github/workflows/ci.yml` to run Python tests and an npm audit step.

## Notes
- **Storage**: by default transactions are written to `AGORA_STORAGE_DIR` or the current working directory. The JSON file storage is single-process only — do not use `uvicorn --workers > 1` in production without switching to a database.
- **NVIDIA integration**: set `NVIDIA_API_KEY` in environment or `.env` before starting AI Engine.
- This document is a minimal runbook; expand as needed (troubleshooting, test coverage, local mocking).