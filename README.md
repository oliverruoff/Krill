![Krill](krill_icon.png)

# Krill
Hi, I am **Krill**: a lightweight, modular, and LLM-agnostic chatbot gateway in progress.

Right now, I am in my first MVP stage. I focus on one job: managing bot settings through a clean web UI and a simple FastAPI backend. I store everything in a single `braindump.json` file so state handling stays transparent and backup-friendly.

## What I Do Today

- Serve a dependency-free settings UI (`HTML/CSS/JS`)
- Expose settings APIs via FastAPI
- Expose provider registry APIs via FastAPI
- Validate settings with Pydantic
- Persist runtime state in `data/braindump.json`

## What I Will Do Next

As Krill grows, the plan is to expand into a full chatbot gateway while keeping the architecture clean and modular:

- Add real provider integrations (OpenAI, Gemini, others)
- Add conversation handling and history in the same state model
- Add backup/restore workflow around `braindump.json`
- Add MCP-based tool capabilities
- Package for lightweight container deployment

## Tech Stack

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- Vanilla HTML/CSS/JavaScript

## Quick Start

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` to access the settings page.

## Current API

- `GET /` -> serves setup page until complete, then serves gateway page
- `GET /setup` -> setup and provider management view
- `GET /gateway` -> main gateway view (redirects to setup if incomplete)
- `GET /api/providers` -> returns available providers and model lists from registry
- `POST /api/providers/verify` -> verifies provider credentials with a live test call
- `GET /api/settings` -> returns current settings
- `POST /api/settings` -> validates and saves settings
- `POST /api/reset` -> resets all settings to defaults

## Provider Architecture (LLM-Agnostic)

Krill now includes a simple provider structure designed for easy extension:

- `app/providers/base.py` -> unified provider interface
- `app/providers/dummy.py` -> first provider implementation
- `app/providers/gemini.py` -> Gemini provider metadata + model list
- `app/providers/registry.py` -> list of currently available providers

To add a provider, add one new file in `app/providers/` and register it in `app/providers/registry.py`.

## Current UI Flow

- Setup appears until first valid provider/model/api-key is saved
- Gateway becomes the default home page after setup completion
- Gateway supports switching active provider/model quickly
- Gateway allows reset and links back to setup for deeper adjustments
- Add/Update provider verifies API key + model before accepting provider config

## Project Status

Krill is intentionally small right now: no chat engine, no MCP tools, and no Docker setup yet. A provider registry is in place with a `dummy` provider so future provider integrations can stay clean and modular.
