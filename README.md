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
- Switch provider/model from the gateway header while preserving chat context
- Use built-in tools ("MCPs") for real actions:
  - Brave Search (web search)
  - Git Operations (clone, status, branch, commit, pull/push, PR via `gh`)
  - Local Files (directory listing, glob/grep/search, file reads/writes/edits, copy/move/delete, command execution)
- Use integrations for chat ingress channels:
  - Telegram (bot token based Telegram chat ingress)
- Schedule timed jobs (daily/weekly/monthly/one-time) with hidden prompts and channel fan-out (Gateway, Telegram)
- Let Krill orchestrate multi-step tool flows automatically (sequential recursive tool calls)
- See live tool/system trace messages while execution runs
- Stop running tool chains and clear queued work for the active chat
- Track token usage per chat and per day

## How Krill Works (Technical)

### 1) Single Source of Truth: `braindump.db`

Krill persists runtime state in a normalized SQLite database at `data/braindump.db`, including:

- setup + provider settings
- core and normal memories
- chat sessions and messages
- tool configs
- daily token usage
- advanced tool execution settings

Because all important runtime state is in one file, backup/restore is simple:

- backup: download `braindump.db` via Gateway menu or copy `data/braindump.db`
- restore: replace file or import through setup UI

### 2) Providers (LLM layer)

Krill is provider-agnostic through a registry pattern:

- `openai`
- `gemini`
- `openrouter`

Provider modules live in `app/providers/`, with shared interface in `app/providers/base.py` and registration in `app/providers/registry.py`.

### 3) Tools (MCP layer)

Tool integrations live in `app/mcps/` and are registered once in `app/mcps/registry.py`.

Current tools:

- `brave_search`
- `git_ops`
- `home_assistant` (token-based Home Assistant access; defaults base URL to `http://homeassistant.local:8123`)
- `google_services` (disabled by default, OAuth login, read-only/read-write modes for Gmail, Calendar, and Drive)
- `local_files` (enabled by default)
- `memory_access` (enabled by default)
- `opencode` (disabled by default, delegates coding work to `npx opencode run`)
- `timed_jobs` (manage timed jobs via tools: list/get/create/update/delete/trigger)

OpenCode MCP notes:

- select the OpenCode provider and model directly in the tool card
- replies are delivered in the same channel where the request was triggered (Gateway stays in Gateway, Telegram stays in Telegram)
- exposes planning/build tools (`opencode_plan`, `opencode_build`)
- uses active Krill provider/model automatically (`openai`, `gemini`, `openrouter`)
- Gemini integration for OpenCode uses API key env vars (`GEMINI_API_KEY` + `GOOGLE_API_KEY`)
- OpenCode sessions are kept in-memory per channel/chat and reset on app/container restart

Home Assistant MCP notes:

- configure a Home Assistant long-lived token in the tool card
- base URL defaults to `http://homeassistant.local:8123` if left empty
- supports listing entities, checking state, triggering/calling services, listing automations, and creating/updating automations

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
- if Google OAuth shows private-IP redirect errors in Docker, set `KRILL_PUBLIC_BASE_URL` to a reachable host URL (for local host-browser use: `http://localhost:8055`)
- OAuth tokens and resolved client credentials are persisted in `braindump.db` (`mcp_config_params`), so export/import keeps the connection usable

Current integrations:

- `telegram`

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
- Gateway menu includes Timed Jobs for scheduled prompt automation with per-job channels
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
