# AGENTS.md
Operational guide for agentic coding tools working in `Krill`.

## 1) Project Snapshot
- Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic, vanilla HTML/CSS/JS.
- Entrypoint: `app/main.py`.
- Core persisted state: `data/braindump.json`.
- Product: setup flow + gateway chat UI + provider/tool orchestration + optional integrations.

## 2) Architecture Map
- `app/main.py`: FastAPI routes, SSE chat endpoint, settings and integration APIs.
- `app/config.py`: settings models, normalization, robust file load/save.
- `app/chat_engine.py`: shared chat execution path used by Gateway and Telegram.
- `app/runtime_prompt.py`: system prompt composition helper.
- `app/usage.py`: shared daily token usage helpers.
- `app/providers/`: LLM provider protocol + registry + provider implementations.
- `app/mcps/`: tool plugin protocol + registry + tools (`brave_search`, `git_ops`, `local_files`).
- `app/tooling/orchestrator.py`: recursive tool-calling loop (`generate_with_tools`).
- `app/integrations/`: integration protocol + registry.
- `app/integrations/telegram/`: Telegram integration config/client/worker/plugin.
- `static/js/setup.js`: setup page behavior.
- `static/js/gateway.js`: gateway UI, queueing, streaming, settings sync.

## 3) External Rule Files
- `.cursorrules`: not present.
- `.cursor/rules/`: not present.
- `.github/copilot-instructions.md`: not present.
- Treat this file as the canonical in-repo agent guide.

## 4) Setup / Run Commands
Run from repo root: `C:\Users\olive\Documents\develop\Krill`

Create virtual environment:
```bash
python -m venv .venv
```

Install dependencies (PowerShell):
```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install dependencies (macOS/Linux):
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Run app locally:
```bash
uvicorn app.main:app --reload --port 8055
```

Docker (optional):
```bash
docker build -t krill:latest .
docker run --name krill -p 8055:8055 -v krill_data:/app/data krill:latest
```

## 5) Build / Lint / Test Commands
Current repo state:
- No dedicated lint tool config committed (`ruff`, `flake8`, `eslint`, etc.).
- No formatter config committed (`black`, `prettier`, etc.).
- No committed test suite directory at the moment.

Backend sanity check:
```bash
python -m compileall app
```

Frontend syntax checks:
```bash
node --check static/js/setup.js
node --check static/js/gateway.js
```

If tests are added, use `pytest`:
```bash
pytest
```

Run a single test file:
```bash
pytest tests/test_api.py
```

Run a single test function (important):
```bash
pytest tests/test_api.py::test_chat_stream_returns_sse
```

Useful focused options:
```bash
pytest -k settings
pytest -x
pytest -q
```

## 6) Code Style Guidelines

### Python
- Use explicit imports; no wildcard imports.
- Naming: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Add type hints to new or edited functions whenever practical.
- Keep modules cohesive and avoid hidden side effects.
- Use module docstrings (already standard in this repo).

### Formatting
- Preserve existing style in each file.
- Keep line lengths readable; avoid dense one-liners.
- Do not introduce new formatting tools unless requested.

### Types and Data Models
- Prefer explicit Pydantic models for API inputs/outputs.
- Put constraints/defaults in `Field(...)` where relevant.
- Normalize persisted fields in `app/config.py` when adding/changing schema.

### Naming and Semantics
- Provider IDs, MCP IDs, integration IDs are lowercase strings.
- Keep route/model names explicit and aligned (`/api/integrations/status` -> `IntegrationStatusResponse`).

## 7) Error Handling Conventions
- Fail fast on invalid state, but return actionable detail.
- For API validation/state issues, use `HTTPException` with clear `detail`.
- Preserve SSE contract: `tool_step`, `meta`, `token`, `done`, `error`.
- In streaming paths, prefer graceful `error` events over uncaught crashes.
- Log unexpected backend exceptions with context.

## 8) Persistence and State Rules
- `data/braindump.json` is the source of truth for core app settings/state.
- Use `load_settings()` / `save_settings()` helpers; do not bypass them.
- Settings I/O is atomic and locked; keep that behavior intact.
- Any new persisted field requires normalization support in `_normalize_legacy_settings`.
- Telegram chat sessions are intentionally ephemeral and must not be written to `settings.chats`.
- Telegram persisted state is limited (owner binding + update offset + integration config).

## 9) Chat Flow Rules
- Shared chat execution must go through `app/chat_engine.py`.
- Keep orchestration logic centralized in `generate_with_tools(...)`.
- If chat behavior changes, update shared engine first, then channel adapters if needed.
- Gateway and Telegram should share execution behavior but keep channel state isolated.

## 10) Frontend Rules
- Vanilla JS only; avoid introducing frameworks.
- Keep state updates explicit and predictable.
- Preserve accessibility attributes and semantic structure.
- Keep integration status polling separate from chat state sync.

## 11) Security and Secrets
- Never commit real API keys, tokens, or private keys.
- Avoid logging secret values from provider/integration config.
- Be especially careful with Git MCP SSH key paths/content.

## 12) Agent Execution Checklist
- Read relevant modules before editing.
- Keep diffs minimal and scoped to user request.
- Do not revert unrelated local changes.
- After backend edits: `python -m compileall app`.
- After frontend JS edits: `node --check` on changed JS files.
- Update `README.md` when user-facing behavior or architecture changes.
