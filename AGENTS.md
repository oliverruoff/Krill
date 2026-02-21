# AGENTS.md
Agent guidance for contributors and coding agents in `Krill`.
## 1) Project Snapshot
- Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic, vanilla HTML/CSS/JS.
- Entrypoint: `app/main.py`.
- Runtime state: `data/braindump.json`.
- Key frontend files: `static/setup.html`, `static/gateway.html`, `static/css/style.css`, `static/js/setup.js`, `static/js/gateway.js`.
- Image assets: `static/img/*`.
- Architecture: lightweight monolith with provider-registry pattern.
## 2) Repository Layout
- `app/main.py`: API routes, static serving, chat stream, chat compaction.
- `app/config.py`: settings models, persistence, normalization.
- `app/providers/base.py`: provider interface.
- `app/providers/openai.py`: OpenAI metadata/behavior.
- `app/providers/gemini.py`: Gemini metadata/behavior.
- `app/providers/openrouter.py`: OpenRouter metadata/behavior.
- `app/providers/registry.py`: registration and lookup.
- `static/`: setup/gateway UIs and scripts.
- `data/`: persisted `braindump.json`.
- `Dockerfile`, `docker-entrypoint.sh`: container runtime.
## 3) External Instruction Files
- `.cursorrules`: not present.
- `.cursor/rules/`: not present.
- `.github/copilot-instructions.md`: not present.
- This `AGENTS.md` is the only in-repo agent rule file.
## 4) Setup / Build / Run Commands
Run from repo root: `C:\Users\olive\Documents\develop\Krill`
Create venv:
```bash
python -m venv .venv
```
Install deps (PowerShell):
```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Install deps (macOS/Linux):
```bash
source .venv/bin/activate
pip install -r requirements.txt
```
Run app:
```bash
uvicorn app.main:app --reload --port 8055
```
Backend sanity check:
```bash
python -m compileall app
```
Frontend JS syntax checks:
```bash
node --check static/js/setup.js
node --check static/js/gateway.js
```
Docker build/run:
```bash
docker build -t krill:latest .
docker run --name krill -p 8055:8055 -v krill_data:/app/data krill:latest
```
## 5) Test Commands
Current state:
- No committed `tests/` directory yet.
- No committed `pytest` config yet.
Install pytest when needed:
```bash
pip install pytest
```
Run full test suite:
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
Useful filters:
```bash
pytest -k settings
pytest -x
```
## 6) Lint / Formatting
Current state:
- No committed lint/formatter config.
Agent policy:
- Match local style in nearby files.
- Keep imports grouped `stdlib -> third-party -> local`.
- Run `python -m compileall app` after backend edits.
- Run `node --check` for changed frontend JS files.
- Do not add lint tooling unless explicitly requested.
If linting is requested, prefer:
- `ruff` for lint + import sorting.
- `black` or `ruff format` for formatting.
## 7) Code Style Guidelines
Python:
- Use explicit imports; avoid wildcard imports.
- Type parameters and return values.
- Prefer concrete types over `Any`.
- Keep helpers focused and side effects clear.
- Use verb-oriented route/helper names.
Naming:
- `snake_case` for variables/functions.
- `PascalCase` for classes/Pydantic models.
- `UPPER_SNAKE_CASE` for constants.
FastAPI / Pydantic:
- Define request/response models explicitly.
- Put constraints/defaults in `Field(...)`.
- Prefer default FastAPI 422 behavior when possible.
- Validate provider/model IDs against registry metadata.
Error handling:
- Fail fast on invalid state.
- Do not silently swallow exceptions.
- Return actionable HTTP error details.
- Preserve existing behavior unless a change is requested.
Async + IO:
- Keep blocking file IO in `asyncio.to_thread(...)`.
- Ensure parent directories exist before writes.
- Keep startup initialization idempotent.
Frontend:
- No frameworks.
- Keep JS functions small/composable.
- Prefer `const`; use `let` only when reassignment is required.
- Keep IDs/selectors stable and payload-aligned.
- Preserve accessibility (`label`, semantic structure, `aria-live`).
- Reuse existing CSS variables/classes.
## 8) Provider + API Conventions
- Provider metadata comes from `app/providers/registry.py`.
- Add new providers in `app/providers/<provider>.py` and register once.
- Setup model selection is dropdown-only from registered models.
- Token limits are provider/model-defined.
- `GET /` serves setup until complete, else gateway.
- `GET /setup`, `GET /gateway` serve setup/gateway views.
- `GET /api/providers` returns provider list + models.
- `POST /api/providers/verify` verifies API key/model upstream.
- `GET /api/settings` and `POST /api/settings` read/write persisted settings.
- `POST /api/reset` resets defaults.
- `POST /api/braindump/import` replaces state.
- `GET /api/braindump/download` downloads `braindump.json`.
- `POST /api/chat/stream` streams chat events.
- `POST /api/chat/compact` performs memory compaction.
## 9) Persistence Expectations
- Persist both `active_provider_id` and `active_model_id` in settings.
- Store provider API keys and selected models in `provider_configs`.
- Normalize legacy payloads safely in `app/config.py`.
- Never commit real API keys or secrets.
## 10) Agent Workflow Checklist
- Keep scope tight to user request.
- Respect unrelated local changes; do not revert user work.
- Prefer minimal diffs; preserve existing architecture.
- After backend edits: run `python -m compileall app`.
- After frontend JS edits: run `node --check` on changed files.
- Smoke-test setup -> save -> gateway for behavior changes.
- Update `README.md` for user-visible behavior changes.
