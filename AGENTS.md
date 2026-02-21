# AGENTS.md
Guidance for coding agents working in `Krill`.

## 1) Project Snapshot
- Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic, vanilla HTML/CSS/JS.
- Current phase: settings-only MVP with JSON-backed state.
- Backend entrypoint: `app/main.py` (`app = FastAPI(...)`).
- Runtime state source: `data/braindump.json`.
- Frontend assets: `static/index.html`, `static/css/style.css`, `static/js/main.js`.
- Direction from `BootStrap.txt`: keep modular and lightweight; do not add chat/providers/MCP/Docker yet.

## 2) Repository Layout
- `app/__init__.py`: package marker.
- `app/main.py`: FastAPI app, startup hook, API routes, static mount.
- `app/config.py`: Pydantic settings model + async IO helpers.
- `static/`: dependency-free frontend files.
- `data/`: persisted runtime state.
- `requirements.txt`: runtime dependencies (unpinned).

## 3) External Rules Discovery
- `.cursorrules`: not present.
- `.cursor/rules/`: not present.
- `.github/copilot-instructions.md`: not present.
- This `AGENTS.md` is currently the only in-repo agent instruction source.

## 4) Setup / Build / Run Commands
Run from repo root: `C:\Users\olive\Documents\develop\Krill`.

Create and activate venv:
```bash
python -m venv .venv
```
Windows PowerShell:
```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
macOS/Linux:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Run server locally:
```bash
uvicorn app.main:app --reload
```

Syntax/build sanity check:
```bash
python -m compileall app
```

Notes:
- No packaging/build pipeline exists yet.
- `compileall` is the current lightweight backend gate.

## 5) Test Commands (Current + Future)
Current state:
- No `tests/` directory yet.
- No `pytest` config file yet.

Install test runner when needed:
```bash
pip install pytest
```

Run all tests:
```bash
pytest
```

Run a single test file:
```bash
pytest tests/test_settings_api.py
```

Run a single test function (important):
```bash
pytest tests/test_settings_api.py::test_post_settings_rejects_long_bot_name
```

Useful options:
```bash
pytest -k settings
pytest -x
```

## 6) Lint / Format Commands
Current state:
- No committed lint/format config (`ruff`, `black`, etc.).

Agent policy:
- Match formatting and style used in nearby files.
- Group imports as stdlib -> third-party -> local.
- Run `python -m compileall app` after backend edits.
- Do not add lint tooling unless explicitly requested.

If linting is requested later, prefer:
- `ruff` for lint + import order.
- `black` or `ruff format` for formatting.

## 7) Code Style Guidelines
Python imports:
- Ordered groups: stdlib, third-party, local.
- Prefer explicit imports of used symbols.
- Avoid wildcard imports.

Typing:
- Type function parameters and returns.
- Keep explicit return types (`-> Settings`, `-> None`).
- Prefer concrete types over `Any`.

Naming:
- `snake_case` for variables/functions.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.
- Use verb-focused route names (`get_settings`, `update_settings`).

Validation and models:
- Keep API schema in Pydantic models.
- Put constraints/defaults in `Field(...)`.
- Prefer FastAPI/Pydantic default 422 behavior.

Error handling:
- Fail fast on invalid state.
- Do not silently swallow exceptions.
- Prefer framework defaults over custom branches unless required.

Async + IO:
- Keep file IO off the event loop using `asyncio.to_thread(...)`.
- Ensure parent directories exist before writes.
- Keep startup initialization idempotent.

Frontend (vanilla):
- No frontend frameworks.
- Keep JS functions small and focused.
- Prefer `const`; use `let` only for reassignment.
- Keep DOM IDs aligned with payload keys when practical.
- Provide clear success/failure UI feedback.
- Keep CSS tokenized via `:root` variables.
- Preserve basic accessibility (`label for`, semantic tags, `aria-live`).

## 8) API and State Conventions
- `GET /` serves `static/index.html`.
- `GET /api/settings` returns current settings.
- `POST /api/settings` validates and persists full settings payload.
- `data/braindump.json` is the runtime source of truth.
- Create `braindump.json` with defaults on startup if missing.

## 9) Agent Change Management
- Keep scope tight to requested task.
- Do not add chat/provider/MCP/Docker work unless requested.
- Preserve dependency-free frontend approach.
- Avoid new dependencies unless needed; explain why when added.
- Never commit secrets or real API keys.
- Respect unrelated user changes in the working tree.

## 10) Pre-PR Checklist
- Run `python -m compileall app`.
- Smoke test `/` and one load/save cycle.
- If tests exist, run targeted tests then full suite.
- Keep diffs focused and call out behavior changes.

## 11) Upadte Readme
- After changes noticable for the user, update README.md to keep it up to date with the current code state
