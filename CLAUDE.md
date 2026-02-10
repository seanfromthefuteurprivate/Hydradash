# HYDRA ENGINE — PROJECT OPERATIONS PROTOCOL

## IDENTITY
- Project: HYDRA Engine
- Stack: Python 3.12 / FastAPI (backend) + React 18 / Vite (frontend)
- DB: In-memory + file-based (no external DB)
- Auth: API keys via environment variables
- Deploy: Docker Compose on DigitalOcean VM

## RULES OF ENGAGEMENT — ALL AGENTS MUST FOLLOW

### Code Standards
- Python: Type hints on all functions. Use Pydantic for validation.
- React: Functional components only. No class components.
- All functions under 50 lines. Extract helper if longer.
- No print() in committed code. Use structured logging.
- Imports: stdlib first, then external libs, then internal. Alphabetical within groups.

### File Ownership (CRITICAL — PREVENTS MERGE CONFLICTS)
- **Backend agents**: ONLY touch files in `backend/`
  - `server.py` — API routes
  - `hydra_engine.py` — Trading engine
  - `hydra_signal_detection.py` — Signal sources
  - `hydra_telegram.py` — Telegram bridge
- **Frontend agents**: ONLY touch files in `frontend/src/`
  - `App.jsx` — Main dashboard
  - `main.jsx` — Entry point
- **DevOps agents**: ONLY touch:
  - `docker-compose.yml`
  - `scripts/deploy.sh`
  - `.github/workflows/`
  - `Dockerfile` files
- **Config/Schema**: ONLY the Lead modifies:
  - `requirements.txt`
  - `package.json`
  - `.env.example`

### Git Discipline
- Commit messages: `type(scope): description`
  - `feat(engine): add new signal source`
  - `fix(api): handle missing API key`
  - `docs(readme): update deployment steps`
- No force pushes. No rebasing shared branches.
- Run tests before marking any task complete.

### Communication Protocol
- When finished: update task status + send summary to lead
- When blocked: immediately flag the blocker AND message lead
- When you find a bug outside your scope: create a new task, don't fix it
- NEVER modify files outside your assigned scope

### Error Handling
- All async operations wrapped in try/except with typed errors
- API routes return consistent `{"status": "ok/error", "data": ..., "error": ...}` shape
- Log errors with context: `{"operation": ..., "input": ..., "error": ...}`

## ARCHITECTURE DECISIONS

### Backend
- FastAPI with uvicorn ASGI server
- WebSocket for real-time signal updates
- Background tasks via asyncio
- Alpaca SDK for paper trading

### Frontend
- React 18 with Vite bundler
- Single-page dashboard (no routing needed)
- Fetch API for REST calls
- Native WebSocket for real-time updates

### Infrastructure
- Docker Compose for orchestration
- Nginx reverse proxy (frontend container)
- GitHub Actions for CI/CD
- DigitalOcean Droplet deployment

## DEPLOYMENT TARGETS
- Droplet IP: 64.23.144.49
- SSH User: hydra
- SSH Key: ~/.ssh/id_ed25519
- Install Path: /opt/hydra
- Dashboard: http://64.23.144.49
- API: http://64.23.144.49:8000

## AGENT SPAWN TEMPLATES

### Backend Agent
```
You are BACKEND. Your scope is ONLY: backend/*.py
DO NOT touch frontend files, devops files, or config files.
Read CLAUDE.md first. Follow all code standards.
Files to pre-read: backend/server.py, backend/hydra_engine.py
When done: run `python -c "from server import app; print('OK')"` to verify imports.
```

### Frontend Agent
```
You are FRONTEND. Your scope is ONLY: frontend/src/*.jsx, frontend/src/*.css
DO NOT touch backend files, devops files, or config files.
Read CLAUDE.md first. Follow all code standards.
Files to pre-read: frontend/src/App.jsx, frontend/package.json
When done: run `cd frontend && npm run build` to verify build succeeds.
```

### DevOps Agent
```
You are DEVOPS. Your scope is ONLY: docker-compose.yml, scripts/, .github/workflows/, Dockerfile files
DO NOT touch application source code.
Read CLAUDE.md first.
Files to pre-read: docker-compose.yml, scripts/deploy.sh
When done: run `docker compose config` to verify compose file is valid.
```

### Tester Agent
```
You are TESTER. READ-ONLY on all files. Create new test files only.
DO NOT modify application code.
Test files go in: backend/tests/, frontend/src/__tests__/
When done: run tests and report pass/fail to lead.
```
