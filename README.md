![Krill](static/img/krill_banner.png)

[![Build and Publish Docker Image](https://github.com/oliverruoff/Krill/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/oliverruoff/Krill/actions/workflows/docker-publish.yml)

# Krill
Hi, I am **Krill** - your local AI gateway and tool-using coding companion.

Think of me as the compact, practical sibling: I keep your data in one place, run locally, and help with real tasks. My bigger brother **Open Claw** may be louder at parties, but I keep the workshop clean and the `braindump.json` tidy.

## What You Can Do With Krill

- Chat with your configured LLM provider and keep persistent multi-chat history
- Switch provider/model from the gateway header while preserving chat context
- Use built-in tools ("MCPs") for real actions:
  - Brave Search (web search)
  - Git Operations (clone, status, branch, commit, pull/push, PR via `gh`)
  - Local Files (directory listing, glob, grep/content search, file reads)
- Use integrations for chat ingress channels:
  - Telegram (bot token based Telegram chat ingress)
- Let Krill orchestrate multi-step tool flows automatically (sequential recursive tool calls)
- See live tool/system trace messages while execution runs
- Stop running tool chains and clear queued work for the active chat
- Track token usage per chat and per day

## How Krill Works (Technical)

### 1) Single Source of Truth: `braindump.json`

Krill persists runtime state in `data/braindump.json`, including:

- setup + provider settings
- chat sessions and messages
- tool configs
- daily token usage
- advanced tool execution settings

Because all important runtime state is in one file, backup/restore is simple:

- backup: copy `data/braindump.json`
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
- `local_files` (enabled by default)

Current integrations:

- `telegram`

Telegram integration notes:

- configure only the bot token in Gateway -> Integrations
- first Telegram sender is auto-bound as owner
- owner can use private chats and group chats
- in group chats, Krill responds only to explicit mentions/replies to the bot
- non-owner messages are silently ignored
- Telegram chat sessions are ephemeral and isolated from Gateway chats
- Telegram chat history is not written to `braindump.json`

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

### 5) API + Streaming

Core chat endpoint: `POST /api/chat/stream`

Gateway and Telegram both use the shared chat execution module `app/chat_engine.py` (`generate_chat_response(...)`).

Exact message workflow (Gateway):

1. User sends a message in Gateway (`static/js/gateway.js`)
2. Gateway posts `POST /api/chat/stream` with message, chat history, and memory block
3. `app/main.py` calls shared engine `generate_chat_response(...)`
4. Shared engine composes runtime system prompt via `compose_runtime_system_prompt(...)` in `app/runtime_prompt.py`
5. Composed prompt includes bot identity (`bot_name`), configured `system_prompt`, and optional `memory_block`
6. Shared engine calls orchestrator `generate_with_tools(...)`
7. SSE streams back `tool_step`, `meta`, `token`, then `done` (or `error`)
8. Gateway finalizes assistant message, tool usage, and token counters, then persists Gateway chat state

Exact message workflow (Telegram):

1. Telegram worker (`app/integrations/telegram/worker.py`) receives bot update
2. Owner and mention/reply rules are enforced
3. Telegram message is added to Telegram's in-memory chat session (ephemeral)
4. Worker calls shared engine `generate_chat_response(...)`
5. Shared engine uses the same runtime system prompt composition and `generate_with_tools(...)` path as Gateway
6. Worker appends assistant result to Telegram in-memory chat and replies via Telegram Bot API
7. Telegram chat history is not written to Gateway chats or `braindump.json`

SSE events include:

- `tool_step` (live system progress)
- `meta` (token usage, tools used, trace payload)
- `token` (streamed answer text)
- `done` / `error`

## Current UI Flow

- Setup first, then Gateway
- Gateway has three panes: chats (left), chat view (center), tools/integrations (right)
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

## API Overview

- `GET /` -> setup or gateway depending on completion state
- `GET /setup` -> setup page
- `GET /gateway` -> gateway page
- `GET /api/providers` -> provider + model metadata
- `POST /api/providers/verify` -> provider credential/model verification
- `GET /api/mcps` -> available tools metadata
- `POST /api/mcps/verify` -> tool verification (when applicable)
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
- `POST /api/chat/stream` -> streaming chat + tool orchestration
- `POST /api/chat/compact` -> compact memory block
- `GET /api/chat/state` -> chat list + active chat id for near-real-time sync
