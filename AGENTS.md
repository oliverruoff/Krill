# AGENTS.md
Practical guidance for coding agents working in `Krill`.

## 1) Project Overview
- Stack: Python 3.11+, FastAPI, Uvicorn, Pydantic, vanilla HTML/CSS/JS.
- Entrypoint: `app/main.py`.
- Persistence: single state file `data/braindump.json`.
- Product shape: setup UI + gateway UI + provider registry + tool (MCP) orchestration.

## 2) Important Paths
- `app/main.py`: API routes, SSE chat stream, settings validation.
- `app/config.py`: Pydantic models + legacy normalization + save/load.
- `app/providers/`: provider interface + implementations (`openai`, `gemini`, `openrouter`).
- `app/mcps/`: tool plugins (`brave_search`, `git_ops`, `local_files`) + registry.
- `app/tooling/orchestrator.py`: recursive sequential tool orchestration.
- `static/setup.html`, `static/js/setup.js`: setup and advanced settings.
- `static/gateway.html`, `static/js/gateway.js`: multi-chat gateway and live orchestration UI.
- `static/css/style.css`: shared UI styling.

## 3) External Agent Rule Files
- `.cursorrules`: not present.
- `.cursor/rules/`: not present.
- `.github/copilot-instructions.md`: not present.
- Therefore, this `AGENTS.md` is the canonical in-repo agent guide.

## 4) Build / Run Commands
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

Backend compile sanity check:
```bash
python -m compileall app
```

Frontend JS syntax checks:
```bash
node --check static/js/setup.js
node --check static/js/gateway.js
```

Docker:
```bash
docker build -t krill:latest .
docker run --name krill -p 8055:8055 -v krill_data:/app/data krill:latest
```

## 5) Lint / Format / Test Commands
Current repository state:
- No committed lint config (`ruff`, `flake8`, etc.)
- No committed formatter config (`black`, `prettier`, etc.)
- No committed `tests/` directory yet

If tests are added, use pytest:
```bash
pytest
```

Single test file:
```bash
pytest tests/test_api.py
```

Single test function (important pattern):
```bash
pytest tests/test_api.py::test_chat_stream_returns_sse
```

Useful options:
```bash
pytest -k settings
pytest -x
pytest -q
```

## 6) Code Style Guidelines

### Python
- Use explicit imports; no wildcard imports.
- Prefer `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Type hints are expected on new/changed functions.
- Keep helpers focused and side effects obvious.
- Keep async I/O non-blocking (`asyncio.to_thread` for blocking file operations).
- Do not silently swallow exceptions; return actionable `HTTPException` details.

### FastAPI / Pydantic
- Define explicit request/response models.
- Put constraints/defaults in `Field(...)`.
- Preserve backward compatibility through normalization in `app/config.py`.
- Validate IDs against registries (providers/MCPs) where applicable.

### Frontend (Vanilla JS)
- Prefer `const`; use `let` only for reassignment.
- Keep functions small and composable.
- Keep API payload shape aligned with backend models.
- Preserve accessibility attributes and semantic structure.
- Avoid framework-like abstractions; follow existing style.

### CSS / HTML
- Reuse existing classes/variables before adding new primitives.
- Keep visual changes subtle and consistent with current UI language.
- Maintain responsive behavior (desktop + mobile).

## 7) Naming / Architecture Conventions
- Providers are registered once in `app/providers/registry.py`.
- Tools (MCPs) are registered once in `app/mcps/registry.py`.
- Orchestrator performs sequential recursive tool steps; do not bypass it for normal chat flows.
- Runtime state is persisted via settings API to `braindump.json`.

## 8) Error Handling Conventions
- Fail fast on invalid inputs/state.
- Emit clear user-facing messages for recoverable failures.
- Keep hard tool errors explicit (`MCP hard error: ...`) unless changing behavior is requested.
- Preserve existing SSE event contract unless explicitly changing it.

## 9) Persistence Rules
- `data/braindump.json` is the source of truth.
- Never remove existing keys without migration/normalization support.
- Any new persisted field must be normalized in `_normalize_legacy_settings`.
- Keep setup save path from dropping unrelated state (chats, mcp configs, daily usage, etc.).

## 10) Security / Secrets
- Do not commit real secrets.
- Be careful when logging token/key fields from `provider_configs` or MCP params.
- Git MCP intentionally handles sensitive key material; avoid printing private key content.

## 11) Agent Workflow Checklist
- Read nearby code before editing.
- Keep diffs minimal and scoped to request.
- Do not revert unrelated user changes.
- After backend edits: `python -m compileall app`.
- After frontend JS edits: `node --check` on changed files.
- Update `README.md` when user-facing behavior or architecture changes.
- Prefer incremental, verifiable changes over broad rewrites.
