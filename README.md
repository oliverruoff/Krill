![Krill](static/img/krill_banner.png)

[![Build and Publish Docker Image](https://github.com/oliverruoff/Krill/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/oliverruoff/Krill/actions/workflows/docker-publish.yml)

# Krill
Hi, I am **Krill** - your local AI gateway and tool-using coding companion.

Think of me as the compact, practical sibling: I keep your data in one place, run locally, and help with real tasks. My bigger brother **Open Claw** may be louder at parties, but I keep the workshop clean and the `braindump.db` tidy.

## Gateway

The Krill gateway is the main window, used for chatting, tool selection and main settings.

![Krill Gateway](static/img/gateway_screenshot.png)

## What You Can Do With Krill

- Chat with your configured LLM provider and keep persistent multi-chat history
- Keep your current chat selection stable while other chats receive queued or completed messages
- Queue messages with immediate composer clearing to reduce accidental duplicate sends
- Switch provider/model from the gateway header while preserving chat context
- Use built-in tools ("MCPs") for real actions:
  - Brave Search (web search)
  - Git Operations (clone, status, branch, commit, pull/push, PR via `gh`)
  - Local Files (directory listing, glob/grep/search, file reads/writes/edits, copy/move/delete, command execution)
- Use integrations for chat ingress channels:
  - Telegram (bot token based Telegram chat ingress)
  - WhatsApp Web (allowlisted inbound messages bridged into Gateway automation chats)
- Schedule timed jobs (daily/weekly/monthly/one-time/hourly/every 2h/every 30m/15m/10m/5m) with hidden prompts, channel fan-out (Gateway, Telegram), and optional AI output-decision mode
- Browse timed jobs in collapsed cards by default, then expand a job on demand to inspect its full prompt and details
- Timed-job auth failures are de-noised: Krill sends one reconnect warning, suppresses repeated auth-expired spam, and advances the schedule instead of tight-loop retries
- Gateway and Setup show a visible warning banner while timed-job auth-expiry suppression is active
- Reconnecting the affected OAuth provider clears the timed-job auth warning immediately, without waiting for the next successful scheduled run
- Let Krill orchestrate multi-step tool flows automatically (sequential recursive tool calls)
- See live tool/system trace messages while execution runs
- Stop running tool chains and clear queued work for the active chat
- Attach one image in Gateway/Telegram messages for transient vision analysis (no image file persistence)
- Track token usage per chat and per day
- Manage core/normal memories with per-type compaction in Memory Management (timestamp-preserving, lossless-oriented summarization)
- Switch between professional light/dark themes from Gateway settings popovers (desktop + mobile); selection is persisted in `braindump.db`

## How Krill Works (Technical)

### 1) Single Source of Truth: `braindump.db`

Krill persists runtime state in a normalized SQLite database at `data/braindump.db`, including:

- setup + provider settings
- core and normal memories
- chat sessions and messages
- tool configs
- daily token usage
- advanced tool execution settings
- UI theme preference (`light`/`dark`)
- authentication state (admin user hash, login sessions, and login-attempt IP locks)

Authentication bootstrap behavior:

- if no auth user exists in `braindump.db`, Krill automatically redirects to `/auth/setup`
- create the first admin username/password once; it is stored as a password hash
- after bootstrap, all app/API routes require login (except `/login` and `/api/auth/*`)
- failed logins are tracked by client IP and automatically ban for 1 hour after 5 wrong attempts
- password changes are available from Gateway settings (old password + new password + confirmation)
- session cookies follow the request scheme: HTTPS requests get `Secure` cookies, plain HTTP requests do not
- this allows both direct `http://<server-ip>:8055` access and HTTPS reverse-proxy/Tailscale access to work side by side
- if Krill sits behind a reverse proxy, make sure Uvicorn receives trusted forwarded scheme headers so HTTPS requests are detected correctly

Because all important runtime state is in one file, backup/restore is simple:

- backup: download `braindump.db` via Gateway menu or copy `data/braindump.db`
- restore: replace file or import through setup UI

### 2) Providers (LLM layer)

Krill is provider-agnostic through a registry pattern:

- `openai`
- `openai_codex_oauth` (ChatGPT/Codex OAuth)
- `google_gemini_oauth` (Gemini OAuth, unofficial)
- `gemini`
- `openrouter`

Provider modules live in `app/providers/`, with shared interface in `app/providers/base.py` and registration in `app/providers/registry.py`.

OpenAI OAuth provider notes:

- choose `openai_codex_oauth` in Setup and click **Connect OpenAI**
- Krill opens an OAuth popup and stores subscription credentials in `provider_configs`
- no owner-managed OAuth client id/secret required for this provider flow
- automatic callback mode uses `KRILL_PUBLIC_BASE_URL` if set; manual mode is also supported by pasting the final redirect URL/code
- this uses ChatGPT/Codex OAuth tokens (subscription auth), not OpenAI Platform API keys
- OpenAI OAuth API routes are isolated in `app/routers/openai_oauth.py` and mounted from `app/main.py`

Google OAuth MCP note:

- Google OAuth API routes are isolated in `app/routers/google_oauth.py` and mounted from `app/main.py`

Gemini OAuth provider notes:

- choose `google_gemini_oauth` in Setup and click **Connect Gemini OAuth**
- Krill tries to import local Gemini CLI credentials from `~/.gemini/oauth_creds.json` or `~/.gemini/settings.json`
- if import fails, paste OAuth JSON (or file path) in the manual completion field
- this is an unofficial integration and may carry account-policy risk; use at your own risk
- Gemini OAuth provider routes are isolated in `app/routers/gemini_oauth.py` and mounted from `app/main.py`

### 3) Tools (MCP layer)

Tool integrations live in `app/mcps/` and are registered once in `app/mcps/registry.py`.

Current tools:

- `browser_control` (disabled by default, browser automation for navigation, form interactions, waiting, and extraction)
- `brave_search`
- `git_ops`
- `home_assistant` (token-based Home Assistant access; defaults base URL to `http://homeassistant.local:8123`)
- `google_services` (disabled by default, OAuth login, read-only/read-write modes for Gmail, Calendar, and Drive)
- `local_files` (enabled by default)
- `memory_access` (enabled by default)
- `opencode` (disabled by default, delegates coding work to `npx opencode run`)
- `scripts` (disabled by default, creates DB-backed Python scripts with metadata comments in `data/scripts`)
- `ssh_control` (disabled by default, chat-driven SSH connect/execute/session management)
- `timed_jobs` (manage timed jobs via tools: list/get/create/update/delete/trigger)
- `youtube_summarizer` (enabled by default, fetches YouTube transcripts and summarizes videos)

Memory Access MCP notes:

- enabled by default
- supports `lookup_memories` for memory-grounded recall questions
- supports `save_memory` for explicit remember intents (for example: remember, don't forget, memorize)
- `save_memory` accepts optional `memory_type` (`core` or `normal`); if omitted, it defaults to `normal` unless the content is high-confidence long-term identity/preference/constraint

OpenCode MCP notes:

- configure one OpenCode Zen API key directly in the tool card
- replies are delivered in the same channel where the request was triggered (Gateway stays in Gateway, Telegram stays in Telegram)
- exposes planning/build tools (`opencode_plan`, `opencode_build`)
- always uses the fixed free model `opencode/minimax-m2.5-free`
- OpenCode sessions are kept in-memory per channel/chat and reset on app/container restart

Scripts MCP notes:

- disabled by default
- tools: `create_script`, `list_scripts`, `edit_script`, `check_script_requirements`, `install_script_requirements`, `execute_script`, `remove_script`
- every script is one Python file under `data/scripts` with required metadata comment rows:
  - `# krill-script-title: ...`
  - `# krill-script-description: ...`
  - `# krill-script-instructions: ...`
  - `# krill-script-python-requirements: ...`
- script definitions are also persisted in `braindump.db` (`scripts` table), so braindump import/export restores script files
- `list_scripts` returns the current stored script catalog (title/metadata/path)
- `edit_script` updates metadata and/or body for an existing script title
- `check_script_requirements` validates installed Python dependencies for a script
- `install_script_requirements` installs dependencies from `python_requirements` using pip
- `execute_script` auto-installs missing Python dependencies, then runs the script by title using server Python (supports optional `input_json` and `timeout_ms`)
- `remove_script` deletes a stored script from `braindump.db` and removes its file from `data/scripts`

#### Scripts MCP: Agent Skills pendant for Python files

Krill `scripts` is the Python-file pendant to Agent Skills:

- Agent Skills: one skill folder with `SKILL.md` frontmatter + instructions
- Krill Scripts: one `.py` file with top metadata comment rows + script body

This gives Krill a progressive-disclosure-like flow:

1. the orchestrator gets lightweight script discovery context (`title`, `description`, `path`)
2. when relevant, it can call `scripts.execute_script`
3. script execution is explicit and observable through MCP tool traces

How script persistence works:

- source of truth is `braindump.db` (`scripts` table)
- script files are materialized in `data/scripts`
- on startup and after braindump import, Krill rehydrates files from DB so scripts survive export/import cycles

Crucial script metadata comments (required at the top of each script file):

- `# krill-script-title: ...`
  - stable script identifier
  - constraints: lowercase slug format `^[a-z0-9]+(?:-[a-z0-9]+)*$`, max 64 chars
- `# krill-script-description: ...`
  - discovery text used by orchestration/planning to decide when a script is relevant
  - constraint: max 1024 chars
- `# krill-script-instructions: ...`
  - concise runtime intent and usage guidance for the script
  - constraint: max 5000 chars
- `# krill-script-python-requirements: ...`
  - optional comma-separated Python package requirements (for example: `pandas>=2.2, requests==2.32.3`)
  - single-line, comma-separated format; constraint: max 500 chars

Why these comments matter:

- they make each script self-describing and auditable like a skill file
- they provide the script execution contract and dependency context in the script itself
- they keep behavior portable: one file contains both metadata and executable logic

Execution contract for script authors:

- `execute_script` checks `python_requirements` and auto-installs missing dependencies before executing
- `execute_script` passes optional `input_json` to the script via `stdin` as JSON text
- scripts should parse `stdin`, run deterministically, print result to `stdout`, and use `stderr` for errors
- `timeout_ms` is enforced by the MCP tool; long-running scripts should be designed with that bound in mind

Browser Control MCP notes:

- disabled by default
- supports session-based browsing actions: start/navigate/snapshot/click/fill/select/press/wait/extract/close
- uses in-memory per-channel+chat sessions (not persisted to `braindump.db`)
- local runtime setup requires Playwright browser install once: `playwright install chromium`

SSH Control MCP notes:

- disabled by default
- no tool-card config fields; connection details are supplied directly in tool arguments by the planner
- supports password auth and private-key auth (with optional key passphrase)
- default host key behavior is permissive (`strict_host_key_checking=false`) and accepts unknown keys automatically
- keeps one in-memory SSH session per channel+chat until disconnected or restart

Home Assistant MCP notes:

- configure a Home Assistant long-lived token in the tool card
- base URL defaults to `http://homeassistant.local:8123` if left empty
- supports listing entities, checking state, triggering/calling services (with optional `return_response`), full todo list item management, listing automations, finding automations by query, and creating/updating automations
- includes automation YAML workflows: list configured automation YAML files, read one automation YAML block, update an existing automation YAML block, and create a new automation from YAML
- automation YAML tools prefer filesystem mode when enabled (`Config Root Path` and/or `Automations File Path`), and gracefully fall back to Home Assistant API config endpoints when files are unavailable

Google Services MCP notes:

- configure OAuth client credentials directly in the Google Services tool card
- enable Gmail API, Google Calendar API, and Google Drive API in your Google Cloud project
- optional: server env vars can still be used as defaults:
  - `GOOGLE_OAUTH_CLIENT_ID` (fallback: `GOOGLE_CLIENT_ID`)
  - `GOOGLE_OAUTH_CLIENT_SECRET` (fallback: `GOOGLE_CLIENT_SECRET`)
  - `KRILL_PUBLIC_BASE_URL` (optional OAuth callback base URL override; useful in Docker/reverse-proxy setups)
- choose access mode:
  - unchecked **Add write access**: read Gmail, Calendar, and Drive files
  - checked **Add write access**: also send emails, create/update calendar events, and upload files to Drive
- click **Login Google** to complete OAuth consent
- Gmail tools support attachments: list/download/save attachments from messages, and send email with base64 or local-file attachments (write mode required for sending)
- Drive local uploads (`drive_upload_local_file`) now allow `max_bytes` up to 1GB
- Drive document reading now supports `drive_read_file` for Google Docs, Google Sheets, PDFs, DOCX files, and text-like files so the model can pull file contents into context without passing raw base64 blobs through the prompt
- if Google OAuth shows private-IP redirect errors in Docker, set `KRILL_PUBLIC_BASE_URL` to a reachable host URL (for local host-browser use: `http://localhost:8055`)
- OAuth tokens and resolved client credentials are persisted in `braindump.db` (`mcp_config_params`), so export/import keeps the connection usable

YouTube Summarizer MCP notes:

- enabled by default
- uses `youtube-transcript-api` to fetch transcript text from a YouTube URL or video id
- supports summary depth levels via tool argument: `brief`, `standard`, `detailed`
- returns transcript metadata plus summary and key points

Current integrations:

- `telegram`
- `whatsapp`

WhatsApp integration notes:

- optional and disabled by default
- if unused, it can be ignored without affecting Gateway/Telegram/provider behavior
- WhatsApp API endpoints are present, but runtime polling/auto-reply only runs when the WhatsApp integration and MCP are enabled
- uses a local sidecar (`whatsapp-web.js`) with QR connect popup and allowlist filtering
- the QR popup now advances to explicit post-scan progress states and clears stale QR images after a successful scan or failed attempt
- Gateway/system trace messages are session-only now; they stay visible while the page is open but are no longer persisted into `braindump.db`
- `Allowed numbers (Send / Read)` controls who the model can message and whose recent chat history it can load
- `Allowed numbers (Trigger)` controls who can trigger WhatsApp auto-answer when Auto answer is enabled
- auto-answer delay window is configurable via `Auto-reply min delay (s)` and `Auto-reply max delay (s)`
- session auth is persisted in `braindump.db` (`whatsapp_state.session_blob`) for restart recovery

Telegram integration notes:

- configure only the bot token in Gateway -> Integrations
- first Telegram sender is auto-bound as owner
- owner can use private chats and group chats
- in group chats, Krill responds only to explicit mentions/replies to the bot
- non-owner messages are silently ignored
- Telegram chat sessions are ephemeral and isolated from Gateway chats
- Telegram chat history is not written to `braindump.db`
- Telegram chats inject the same runtime identity/behavior/core-memory seed used by Gateway
- Telegram replies include a context-window warning when usage reaches 75% of model limit (suggesting `/new`)
- Telegram supports `/usage` (shows session context fill vs model window) and `/compaction` (manual chat compaction into a fresh chat)
- Telegram accepts image messages (photo/image document) and emits an "Image analysis" assistant message before the final reply

### 4) Orchestrator (reason + act loop)

The orchestrator (`app/tooling/orchestrator.py`) runs a sequential recursive loop:

1. decide whether to call a tool or respond
2. call one tool (with timeout)
3. feed result back into next planning step
4. repeat up to max recursion
5. produce final answer

This allows multi-step workflows like:

- clone repo with Git tool
- inspect files with Local Files tool
- summarize project for user

Advanced controls (setup -> Advanced Settings):

- max tool recursion
- tool timeout in seconds
- memory extraction interval (defaults to 10 user messages)

Recommended baseline for autonomous web-heavy flows (Browser Control + integrations):

- max tool recursion: `8`
- tool timeout in seconds: `90`

Notes:

- new installations use these defaults automatically
- existing installations keep their current saved values until you change them in Advanced Settings

### 5) API + Streaming

Core chat endpoint: `POST /api/chat/stream`

Gateway and Telegram both use the shared chat execution module `app/chat_engine.py` (`generate_chat_response(...)`).

Exact message workflow (Gateway):

1. User sends a message in Gateway (`static/js/gateway.js`)
2. Gateway posts `POST /api/chat/stream` with message, chat history, and memory block
3. `app/main.py` calls shared engine `generate_chat_response(...)`
4. Shared engine composes runtime system prompt via `compose_runtime_system_prompt(...)` in `app/runtime_prompt.py`
5. Runtime prompt includes current local server time (+ optional compacted `memory_block`); identity/behavior/core-memory instructions are seeded into chat history at chat start and after compaction
6. Shared engine calls orchestrator `generate_with_tools(...)` (which can select `memory_access` for memory-grounded recall)
7. SSE streams back `tool_step`, `meta`, `token`, then `done` (or `error`)
8. Gateway finalizes assistant message, tool usage, and token counters, then persists Gateway chat state

Exact message workflow (Telegram):

1. Telegram worker (`app/integrations/telegram/worker.py`) receives bot update
2. Owner and mention/reply rules are enforced
3. Telegram message is added to Telegram's in-memory chat session (ephemeral), and runtime seed context is ensured
4. Worker calls shared engine `generate_chat_response(...)`
5. Shared engine uses the same runtime system prompt composition and `generate_with_tools(...)` path as Gateway
6. Worker appends assistant result to Telegram in-memory chat and replies via Telegram Bot API (adds a `/new` hint if context usage is >= 75%)
7. Telegram chat history is not written to Gateway chats or `braindump.db`

SSE events include:

- `tool_step` (live system progress)
- `meta` (token usage, tools used, trace payload)
- `token` (streamed answer text)
- `done` / `error`

## Current UI Flow

### Init Screen
- start from scratch or from a backed up braindump.db
![Krill Init Screen](static/img/init_screenshot.png)

- Setup first, then Gateway
- Setup supports Core Memories for persistent personal context
- Setup Advanced Settings includes "View Brain" to inspect SQLite tables/columns/rows for debugging
- Gateway has three panes: chats (left), chat view (center), tools/integrations (right)
- On smartphones (<= 900px), the chat view takes the full screen and side panels become swipe-in drawers (left: header/provider/model/chat history, right: settings + tools/integrations)
- Gateway menu includes Memory Management for searchable core/normal memory editing
- Gateway menu includes Short Term Memory for confirming/declining auto-detected memory suggestions
- Gateway menu includes Timed Jobs for scheduled prompt automation with per-job channels and optional output-decision filtering
- Chat execution supports per-chat queueing and cross-chat parallel background processing
- Assistant/tool progress is visible through system trace messages
- Tool usage is displayed below assistant responses (`used Tools: ...`)
- Stop button interrupts active execution and clears queued messages in that chat
- Daily token usage for the current day is shown in the header

## Quick Start

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8055
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8055
```

Open `http://127.0.0.1:8055`.

## Docker

Build:

```bash
docker build -t krill:latest .
```

Run:

```bash
docker run --name krill -p 8055:8055 -v krill_data:/app/data krill:latest
```

The container image includes Node.js/npm and Git tooling (`git`, `ssh`, `ssh-keygen`, `gh`) so OpenCode/Git MCP workflows run end-to-end.
It also starts `Xvfb` by default (`KRILL_ENABLE_XVFB=1`) so Browser Control headed mode can run inside Docker without a host X server.

Optional (disable virtual display/Xvfb):

```bash
docker run --name krill -p 8055:8055 -e KRILL_ENABLE_XVFB=0 -v krill_data:/app/data krill:latest
```

### Updating Krill (Docker)

If you use the provided updater script `scripts/update-krill.sh`, it now handles safe updates with data carry-over:

1. pulls the latest image from GHCR
2. copies current `/app/data/braindump.db` from the running container to `backups/braindump.db`
3. recreates the container with the new image
4. restores `braindump.db` into the new container and restarts once

Run it with:

```bash
./scripts/update-krill.sh
```

Optional (recommended for OAuth in Docker/reverse-proxy setups):

```bash
KRILL_PUBLIC_BASE_URL="http://localhost" ./scripts/update-krill.sh
```

Why `KRILL_PUBLIC_BASE_URL` matters:

- Google OAuth can reject callback URLs that use private LAN IPs (for example `http://192.168.x.x/...`) with `invalid_request`
- Krill uses this env var to build a stable callback URL for OAuth (`/api/mcps/google/oauth/callback`)
- use a browser-reachable host URL (local host-browser: `http://localhost`, production: your public `https://...` domain)
- do not set it to `localhost` if you access Krill from another device (phone/laptop), because callback on that device will point to itself

Google OAuth deployment matrix (important):

- Krill + browser on same machine (no Docker or Docker): use `http://localhost` (or `http://localhost:8055`) and register that exact callback URL in Google Cloud
- Krill on machine A, browser on machine B via LAN IP (`192.168.x.x`): Google blocks private-IP callbacks; use a public HTTPS domain/tunnel for Krill and set `KRILL_PUBLIC_BASE_URL` to that URL
- Temporary workaround for LAN setups: perform Google login once from machine A (host running Krill) via `localhost`; tokens are then stored in `braindump.db` and usable from other clients

Important:

- if your external port is not `80`, include it (for example `http://localhost:8055`)
- the exact callback URL must also be added to your Google OAuth client in Google Cloud Console

### Docker E2E API Test

Run a full end-to-end API flow against Docker using existing public endpoints only:

```bash
python test/e2e_docker_test.py --env-file .env_test
```

Expected `.env_test` key:

- `GEMINI_API_KEY` (fallback: `GOOGLE_API_KEY`)

The script builds the image, starts fresh containers, configures setup with Gemini (`gemini-2.5-flash`), runs one chat turn (`"hi"`), exports/imports braindump, and validates restored chat state.

## API Overview

- `GET /` -> setup or gateway depending on completion state
- `GET /setup` -> setup page
- `GET /gateway` -> gateway page
- `GET /api/providers` -> provider + model metadata
- `POST /api/providers/verify` -> provider credential/model verification
- `GET /api/mcps` -> available tools metadata
- `POST /api/mcps/verify` -> tool verification (when applicable)
- `GET /api/mcps/google/oauth/status` -> Google OAuth connection status
- `GET /api/mcps/google/oauth/start` -> start Google OAuth login redirect flow
- `GET /api/mcps/google/oauth/callback` -> OAuth callback endpoint
- `POST /api/mcps/google/oauth/disconnect` -> revoke/clear Google OAuth tokens
- `GET /api/integrations` -> available integration metadata
- `POST /api/integrations/verify` -> integration verification
- `GET /api/integrations/status` -> lightweight integration runtime status
- `GET /api/mcps/git/ssh-key` -> generate/load Git SSH public key
- `POST /api/mcps/git/verify-ssh` -> verify GitHub SSH access
- `GET /api/settings` -> load settings
- `POST /api/settings` -> validate + persist settings
- `POST /api/reset` -> reset defaults
- `POST /api/braindump/import` -> full state import
- `GET /api/braindump/download` -> download full state
- `GET /api/braindump/view` -> inspect SQLite tables/columns/rows
- `POST /api/memory/user-message` -> increment global user message counter and trigger extraction checks
- `POST /api/memory/turn-complete` -> register completed user+assistant turn for extraction context
- `GET /api/memory/short-term` -> list pending short-term memory suggestions
- `POST /api/memory/short-term/resolve` -> accept/decline suggestions
- `POST /api/chat/stream` -> streaming chat + tool orchestration
- `POST /api/chat/compact` -> compact memory block
- `GET /api/chat/state` -> chat list + active chat id for near-real-time sync
