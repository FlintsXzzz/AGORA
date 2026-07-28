Developer Notes — AGORA

Overview
- Entry points:
  - Node WhatsApp gateway: agora_index.js
  - Python AI Engine (FastAPI): agora_main.py

Run with Docker (recommended):
- Requires Docker and Docker Compose
- From repo root:
  docker compose -f agora_docker-compose.yml up --build

Run locally (without Docker):
- Python AI Engine:
  python -m uvicorn agora_main:app --reload --port 8000
  Required env: NVIDIA_API_KEY, AGORA_STORAGE_DIR (optional)

- Node WhatsApp Gateway:
  NODE: ensure Node 18+ and native dependencies for puppeteer are available.
  node agora_index.js
  Env: AI_ENGINE_BASE_URL (default http://ai-engine:8000), WWEBJS_SESSION_DIR (optional)

Tests
- Python: install deps and run pytest
  python -m pip install -r agora_requirements.txt
  pytest

CI
- A basic GitHub Actions workflow is provided at .github/workflows/ci.yml to run Python tests and an npm audit step.

Notes
- Storage: by default transactions written to AGORA_STORAGE_DIR or current working directory.
- NVIDIA integration: set NVIDIA_API_KEY in environment or .env before starting AI Engine.
- This document is a minimal runbook; expand as needed (troubleshooting, test coverage, local mocking).