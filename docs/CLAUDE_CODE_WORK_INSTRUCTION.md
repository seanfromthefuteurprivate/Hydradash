# Hyper-Detailed Instruction for Claude Code: Work Done on HYDRA Worktree

Use this document to replicate or extend the work that was done. Every change is listed with **exact paths** (relative to the repo root) and **precise content**.

---

## Worktree location (absolute path)

- **Repository root (worktree):**  
  `/Users/seankuesia/Downloads/hydradasha/Hydradash`
- **Backend:**  
  `/Users/seankuesia/Downloads/hydradasha/Hydradash/backend`
- **Frontend:**  
  `/Users/seankuesia/Downloads/hydradasha/Hydradash/frontend`
- **Docs:**  
  `/Users/seankuesia/Downloads/hydradasha/Hydradash/docs`
- **Scripts:**  
  `/Users/seankuesia/Downloads/hydradasha/Hydradash/scripts`

All paths below are **relative to the repo root** unless marked absolute.

---

## Summary of work done

1. **Created `.env`** from `.env.example` at project root (file is gitignored; not in repo).
2. **Added local `.env` loading** so the backend loads the project-root `.env` when run locally (no Docker).
3. **Installed backend deps** and **started backend** (uvicorn on port 8000).
4. **Installed frontend deps** and **started frontend** (Vite on port 3000).
5. **Initialized Git** in the worktree and **committed** all project files plus the code changes below.

---

## 1. Backend: load `.env` from project root

### File: `backend/requirements.txt`

**Change:** Add `python-dotenv` so the server can load `.env` when run from the backend directory.

**Exact addition:** One new line after `uvicorn[standard]==0.31.0`:

```
python-dotenv==1.0.1
```

**Full file (as it is now):**

```
fastapi==0.115.0
uvicorn[standard]==0.31.0
python-dotenv==1.0.1
websockets==13.1
requests==2.32.3
beautifulsoup4==4.12.3
feedparser==6.0.11
alpaca-py==0.33.1
numpy==2.1.0
schedule==1.2.2
python-telegram-bot==21.6
```

**Path in worktree:**  
`backend/requirements.txt`  
Absolute: `/Users/seankuesia/Downloads/hydradasha/Hydradash/backend/requirements.txt`

---

### File: `backend/server.py`

**Change:** Load environment variables from the project root `.env` file when the server runs (e.g. `uvicorn server:app` from `backend/`), so Alpaca/Telegram/FRED etc. keys can be set in one place.

**Exact edits:**

1. **After** the line `import json`, add:
   - `from pathlib import Path`
   - A blank line
   - `from dotenv import load_dotenv`
   - Comment: `# Load .env from project root (parent of backend/) when running locally`
   - `_load_env = Path(__file__).resolve().parent.parent / ".env"`
   - `load_dotenv(_load_env)`

**Resulting top of file (first ~20 lines):**

```python
"""
HYDRA API Server — FastAPI backend that:
1. Runs the signal detection engine on a background loop
2. Exposes REST API for the dashboard
3. Runs the trading engine (paper mode)
4. Manages Telegram bridge
"""

import os
import json
from pathlib import Path

from dotenv import load_dotenv
# Load .env from project root (parent of backend/) when running locally
_load_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_load_env)
import asyncio
import threading
...
```

**Path in worktree:**  
`backend/server.py`  
Absolute: `/Users/seankuesia/Downloads/hydradasha/Hydradash/backend/server.py`

**Important:** No other part of `server.py` was changed. All existing `os.environ.get(...)` calls behave as before; they now read from the loaded `.env` when present.

---

## 2. Project root `.env` (not in Git)

**Action:** A file `.env` was created at the **project root** by copying `.env.example`. It is listed in `.gitignore` and is **not** committed.

**Path:**  
`.env` at repo root  
Absolute: `/Users/seankuesia/Downloads/hydradasha/Hydradash/.env`

**Content:** Same as `.env.example` (see repo file ` .env.example`). Users should fill in API keys there; the backend loads it automatically when run locally.

**To recreate (if missing):**  
Copy `.env.example` to `.env` in the repo root. Do not commit `.env`.

---

## 3. Git state

- **Repository:** Initialized in `/Users/seankuesia/Downloads/hydradasha/Hydradash` (no prior history).
- **Branch:** `main`.
- **Commit:** First commit contains the full HYDRA codebase plus the two code changes above (requirements.txt and server.py). Commit message: `Add dotenv support for local .env loading; initial HYDRA codebase`.
- **Not committed (by design):**  
  `.env`, `node_modules/`, `frontend/dist/`, `data/`, `__pycache__/`, `.DS_Store` (per `.gitignore`).

---

## 4. File map (what lives where in the worktree)

| Path (relative to repo root) | Purpose |
|------------------------------|--------|
| `README.md` | Project overview, quick start, API keys, roadmap |
| `.env.example` | Template for env vars; copy to `.env` and fill keys |
| `.env` | Local env (gitignored); created from `.env.example` |
| `.gitignore` | Excludes .env, node_modules, __pycache__, data, etc. |
| `docker-compose.yml` | Backend + frontend + optional Watchtower |
| `.github/workflows/deploy.yml` | CI/CD: test → build → push → deploy |
| `backend/server.py` | **MODIFIED** — FastAPI app + dotenv loading |
| `backend/requirements.txt` | **MODIFIED** — added python-dotenv |
| `backend/hydra_engine.py` | Trading engine (regime, strategies, risk, Alpaca) |
| `backend/hydra_signal_detection.py` | 37 data sources, orchestrator |
| `backend/hydra_telegram.py` | Telegram bridge (parse + send) |
| `backend/Dockerfile` | Backend container build |
| `frontend/src/App.jsx` | Command center dashboard UI |
| `frontend/src/main.jsx` | React entry |
| `frontend/index.html` | HTML shell |
| `frontend/package.json` | Node deps (React 18, Vite 5) |
| `frontend/vite.config.js` | Vite config, /api proxy to backend:8000 |
| `frontend/nginx.conf` | Production reverse proxy |
| `frontend/Dockerfile` | Multi-stage frontend build |
| `docs/STRATEGY_BIBLE.md` | Strategy documentation |
| `docs/CLAUDE_CODE_WORK_INSTRUCTION.md` | This file |
| `scripts/deploy.sh` | One-command VM deploy |

---

## 5. Commands to push this worktree to a remote

Run from the **repository root**:

```bash
cd /Users/seankuesia/Downloads/hydradasha/Hydradash

# If you already have a remote (e.g. GitHub):
git remote add origin https://github.com/YOUR_ORG/Hydradash.git
# or: git remote add origin git@github.com:YOUR_ORG/Hydradash.git

# Push (first time):
git push -u origin main
```

If the remote already exists and you only need to push:

```bash
cd /Users/seankuesia/Downloads/hydradasha/Hydradash
git push -u origin main
```

---

## 6. Nothing else was changed

- No edits to `hydra_engine.py`, `hydra_signal_detection.py`, `hydra_telegram.py`, `frontend/src/App.jsx`, or any other backend/frontend logic.
- No new source files except this doc (`docs/CLAUDE_CODE_WORK_INSTRUCTION.md`).
- No changes to Dockerfiles, docker-compose, or deploy scripts beyond what was already in the tree.

---

## 7. One-line summary for Claude Code

**"In the HYDRA repo at `/Users/seankuesia/Downloads/hydradasha/Hydradash`: (1) `backend/requirements.txt` — add line `python-dotenv==1.0.1` after uvicorn. (2) `backend/server.py` — after `import json`, add `from pathlib import Path`, then `from dotenv import load_dotenv`, then the two-line comment and the two lines that set `_load_env = Path(__file__).resolve().parent.parent / \".env\"` and call `load_dotenv(_load_env)`. (3) Ensure a `.env` exists at repo root (copy from `.env.example`); it is gitignored. All other code is unchanged."**
