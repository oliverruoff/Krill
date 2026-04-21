# AGENTS.md
Operational guide for agentic coding tools working in `Krill`.

## 1) Project Snapshot
- Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic v2, vanilla HTML/CSS/JS.
- Entrypoint: `app/main.py` (1600+ lines; routes, SSE, settings, integration APIs).
- Core persisted state: `data/braindump.db` (SQLite; path overridable via `KRILL_BRAINDUMP_PATH`).
- Product: setup flow + gateway chat UI + provider/tool orchestration + optional integrations.
- No committed lint/formatter config; no external test framework (pytest not wired up).

## 2) Architecture Map
- `app/main.py`: FastAPI app, SSE chat endpoint, all HTTP API routes.
- `app/config.py`: Pydantic settings models + all SQLite persistence helpers (`load_settings`, `save_settings`, `upsert_timed_job`, `view_braindump`, etc.). Single source of truth for schema.
- `app/chat_engine.py`: shared async chat execution path (`generate_chat_response`) used by Gateway SSE and Telegram.
- `app/runtime_prompt.py`: composes the runtime system prompt from settings + memories.
- `app/usage.py`: shared daily token usage helpers.
- `app/timed_jobs.py`: scheduled job runner (`run_due_timed_jobs_once`).
- `app/memory_extraction.py`: background async worker for short-term memory extraction.
- `app/providers/`: LLM provider protocol (`base.py`), registry, implementations (gemini, openai, openrouter, minimax, etc.), resilience helpers.
- `app/mcps/`: MCP tool plugin protocol (`base.py`), registry, tools: `brave_search`, `git_ops`, `local_files`, `google_services`, `browser_control`, `youtube_summarizer`, `home_assistant`, `ssh_control`, `timed_jobs`, `brain_access`, `whatsapp`, `opencode`.
- `app/tooling/orchestrator.py`: recursive tool-calling loop (`generate_with_tools`).
- `app/tooling/runtime_context.py`: per-request runtime context for tool calls.
- `app/integrations/`: integration protocol + registry + `telegram/` + `whatsapp/` + `chat_runtime.py`.
- `app/routers/`: OAuth callback routers (`gemini_oauth`, `google_oauth`, `openai_oauth`).
- `static/js/setup.js`: setup page behavior.
- `static/js/gateway.js`: gateway UI, queueing, streaming, settings sync.

## 3) External Rule Files
- `.cursorrules`: not present.
- `.cursor/rules/`: not present.
- `.github/copilot-instructions.md`: not present.
- Treat this file as the canonical in-repo agent guide.

## 4) Setup / Run Commands
Create virtual environment and install dependencies:

```bash
python -m venv .venv

# PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# macOS/Linux
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

**Backend syntax check** (run after every Python edit):
```bash
python -m compileall app
```

**Frontend syntax check** (run after every JS edit):
```bash
node --check static/js/setup.js
node --check static/js/gateway.js
```

**Test suite location**: `test/` (not `tests/`). Tests are standalone async scripts, not pytest-based.

Run individual tests directly with Python:
```bash
# Telegram /new seed injection smoke test (no real API key needed)
python test/test_telegram_new_chat_seed.py

# Timed jobs integration test (requires .env_test with GEMINI_API_KEY)
python test/test_timed_jobs_run.py

# Full Docker E2E test (requires Docker + .env_test with GEMINI_API_KEY)
python test/e2e_docker_test.py
python test/e2e_docker_test.py --env-file .env_test --model gemini-2.5-flash
python test/e2e_docker_test.py --keep-artifacts
```

Create `.env_test` for tests that hit the live Gemini API:
```
GEMINI_API_KEY=your-key-here
```

There is no pytest configuration. Do not introduce pytest unless requested.

## 6) Code Style Guidelines

### Python imports
- Use explicit imports; no wildcard imports.
- Standard library first, then third-party, then local (`from app.X import Y`).
- Internal imports use relative form inside `app/` (e.g., `from .config import load_settings`), but test files use absolute form after manually inserting `repo_root` into `sys.path`.
- Use `from __future__ import annotations` in files that need it (present in all test files and several app modules).
- Defer heavy imports inside functions only when necessary (e.g., dynamic plugin loading); annotate with `# pylint: disable=import-outside-toplevel`.

### Formatting
- Preserve the existing style in each file; do not reformat unrelated code.
- Readable line lengths; avoid dense one-liners.
- Blank line between class-level constants and class definitions (see `config.py`).
- Do not introduce `black`, `ruff`, `flake8`, or any formatter unless explicitly requested.

### Types and Data Models
- Prefer explicit Pydantic `BaseModel` subclasses for API inputs/outputs and persisted records.
- Use `Field(...)` for constraints, defaults, and `max_length` where relevant.
- Use `TypedDict` for internal return structures (see `ChatEngineResult`, `ChatEngineToolUsage`).
- Add type hints (`-> ReturnType`, parameter annotations) to all new or edited functions.
- Use `Literal[...]` for fields with a fixed set of values (e.g., `role`, `type`).
- Any new persisted field requires schema support in `app/config.py` (both the Pydantic model and the SQLite read/write path).

### Naming
- `snake_case` for functions and variables.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for module-level constants.
- Provider IDs, MCP IDs, integration IDs: lowercase strings (e.g., `"gemini"`, `"git_ops"`, `"telegram"`).
- Route paths and response model names aligned: `/api/integrations/status` → `IntegrationStatusResponse`.
- Private helpers prefixed with `_` (e.g., `_now_iso`, `_DB_LOCK`, `_server_timezone`).

## 7) Error Handling Conventions
- Fail fast on invalid state; return actionable detail.
- For HTTP API issues, raise `HTTPException` with a clear `detail` string.
- SSE contract events: `tool_step`, `meta`, `token`, `done`, `error`. Do not break this protocol.
- In streaming paths, emit a graceful `error` SSE event rather than letting exceptions propagate uncaught.
- Log unexpected backend exceptions with sufficient context for diagnosis.
- In tests, raise `RuntimeError` (or the script-local `E2EFailure`) with a descriptive message on assertion failure.

## 8) Persistence and State Rules
- `data/braindump.db` is the source of truth. Path is controlled by `KRILL_BRAINDUMP_PATH` env var.
- Always use `load_settings()` / `save_settings()` helpers. Never read/write the SQLite file directly from application code outside `app/config.py`.
- Settings I/O is protected by `_DB_LOCK` (`asyncio.Lock()`); keep that behavior intact.
- Any new persisted field requires changes to both the Pydantic model and the SQL read/write helpers in `app/config.py`.
- Telegram chat sessions are intentionally ephemeral: do not write them to `settings.chats`.
- Telegram persisted state is limited to: owner binding, update offset, integration config.

## 9) Chat Flow Rules
- All chat execution goes through `app/chat_engine.py::generate_chat_response`.
- Tool-calling orchestration is centralized in `app/tooling/orchestrator.py::generate_with_tools`.
- If chat behavior changes, update the shared engine first; then update channel adapters if needed.
- Gateway (SSE) and Telegram share execution logic but keep channel state isolated.
- Runtime context (per-request tool state) lives in `app/tooling/runtime_context.py`; reset it before each request.

## 10) Frontend Rules
- Vanilla JS only. Do not introduce frameworks (no React, Vue, etc.).
- Keep state updates explicit and predictable.
- Preserve accessibility attributes and semantic HTML structure.
- Keep integration status polling separate from chat state sync.
- Run `node --check` on any edited `.js` file before committing.

## 11) Security and Secrets
- Never commit real API keys, tokens, or private keys.
- `SENSITIVE_KEYWORDS` in `app/config.py` lists fields that must not be logged: `api_key`, `token`, `secret`, `password`, `private_key`, `ssh_private`.
- Be especially careful with Git MCP SSH key paths/content.
- `.env_test` is gitignored; never commit it.

## 12) Agent Execution Checklist
- Read relevant modules before editing.
- Keep diffs minimal and scoped to the user's request; do not reformat unrelated code.
- Do not revert unrelated local changes.
- After any code or behavior change: bump `app/version.py::APP_VERSION`.
- After any Python edit: `python -m compileall app`.
- After any JS edit: `node --check static/js/<file>.js`.
- After adding a persisted field: update both the Pydantic model and SQL helpers in `app/config.py`.
- Update `README.md` when user-facing behavior or architecture changes.
