# AGENTS.md
Guidance for coding agents working in `Krill`.

## 1) Project Snapshot
- Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic, vanilla HTML/CSS/JS.
- Current phase: settings-first MVP with provider registry scaffolding.
- Backend entrypoint: `app/main.py` (`app = FastAPI(...)`).
- Runtime state source: `data/braindump.json`.
- Frontend assets: `static/setup.html`, `static/gateway.html`, `static/css/style.css`, `static/js/setup.js`, `static/js/gateway.js`.
- Architecture direction: keep modular/lightweight; no chat runtime, MCP tools, or Docker yet.

## 2) Repository Layout
- `app/__init__.py`: package marker.
- `app/main.py`: app init, startup initialization, API routes, static mount.
- `app/config.py`: Pydantic settings model + async file IO helpers.
- `app/providers/base.py`: unified provider interface contract.
- `app/providers/dummy.py`: first provider implementation.
- `app/providers/registry.py`: provider registration and lookup helpers.
- `static/`: dependency-free frontend (setup + gateway views).
- `data/`: persisted runtime state (`braindump.json`).
- `requirements.txt`: runtime dependencies (unpinned).

## 3) External Rules Discovery
- `.cursorrules`: not present.
- `.cursor/rules/`: not present.
- `.github/copilot-instructions.md`: not present.
- This `AGENTS.md` is currently the only in-repo agent instruction file.

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

Run local server:
```bash
uvicorn app.main:app --reload
```

Backend syntax/build sanity check:
```bash
python -m compileall app
```

## 5) Test Commands (Current + Future)
Current state:
- No `tests/` directory yet.
- No committed `pytest` config yet.

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
- Do not introduce lint tooling unless explicitly requested.

If linting is requested later, prefer:
- `ruff` for linting + import order.
- `black` or `ruff format` for formatting.

## 7) Code Style Guidelines
Python imports:
- Order groups as stdlib, third-party, local.
- Prefer explicit imports of used symbols.
- Avoid wildcard imports.

Typing:
- Type function parameters and return values.
- Keep explicit return types (for example `-> Settings`, `-> None`).
- Prefer concrete types over `Any`.

Naming:
- `snake_case` for variables/functions.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for module constants.
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

## 8) Provider + API Conventions
- Provider options shown to users come from `app/providers/registry.py`.
- Add each new provider in its own file under `app/providers/`.
- Register new providers in one place (`_PROVIDERS` in registry).
- `GET /` serves setup until complete, then gateway.
- `GET /setup` serves setup UI.
- `GET /gateway` serves gateway UI or redirects to setup.
- `GET /api/providers` returns providers and model lists.
- `POST /api/providers/verify` verifies provider credentials against the upstream API.
- `GET /api/settings` returns current settings.
- `POST /api/settings` validates and persists full settings payload.
- `POST /api/reset` resets settings to defaults.
- Validate provider IDs and model IDs against registry-supported values before saving.

## 9) Agent Change Management + Pre-PR
- Keep scope tight to requested tasks.
- Preserve dependency-free frontend approach.
- Avoid new dependencies unless needed; explain why when added.
- Never commit secrets or real API keys.
- Respect unrelated user changes in the working tree.
- Run `python -m compileall app`.
- Smoke test `/` and one complete load/save cycle.
- If tests exist, run targeted tests then full suite.
- Keep diffs focused and call out behavior changes.
- Update `README.md` after user-visible behavior changes.
