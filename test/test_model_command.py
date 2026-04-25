"""Smoke tests for the shared /model slash command helper."""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4
from pathlib import Path


async def _run_scenario() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    scratch_root = repo_root / "tmp_verify_data"
    scratch_root.mkdir(parents=True, exist_ok=True)
    db_path = scratch_root / f"model_command_{uuid4().hex}.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.config import ProviderConfig, ensure_settings_file, load_settings, save_settings  # pylint: disable=import-outside-toplevel
    from app.model_commands import execute_model_command, parse_model_chat_command  # pylint: disable=import-outside-toplevel

    try:
        await ensure_settings_file()
        settings = await load_settings()
        settings.setup_completed = True
        settings.active_provider_id = "gemini"
        settings.active_model_id = "gemini-2.5-flash"
        settings.provider_configs = {
            "gemini": ProviderConfig(api_key="gemini-key", model="gemini-2.5-flash"),
            "openai": ProviderConfig(api_key="openai-key", model="gpt-5.4"),
        }
        await save_settings(settings)

        parsed = parse_model_chat_command("/model openai/gpt-5.5")
        if parsed is None or parsed.argument != "openai/gpt-5.5":
            raise RuntimeError(f"Failed to parse /model command: {parsed}")

        listed = await execute_model_command("")
        if "Active model: gemini/gemini-2.5-flash" not in listed.text:
            raise RuntimeError(f"Model list did not include active model: {listed.text}")
        if "openai/gpt-5.5 - GPT-5.5" not in listed.text:
            raise RuntimeError(f"Model list did not include connected OpenAI GPT-5.5: {listed.text}")
        if "openrouter/" in listed.text:
            raise RuntimeError(f"Model list included unconnected OpenRouter provider: {listed.text}")

        unknown_provider = await execute_model_command("openrouter/openai/gpt-5.4")
        if unknown_provider.ok or "Provider 'openrouter' is not connected." not in unknown_provider.text:
            raise RuntimeError(f"Unexpected unknown-provider result: {unknown_provider}")
        unchanged = await load_settings()
        if unchanged.active_provider_id != "gemini" or unchanged.active_model_id != "gemini-2.5-flash":
            raise RuntimeError("Unknown-provider command changed active provider/model.")

        unknown_model = await execute_model_command("openai/not-real")
        if unknown_model.ok or "Model 'not-real' is not available for provider 'openai'." not in unknown_model.text:
            raise RuntimeError(f"Unexpected unknown-model result: {unknown_model}")
        unchanged = await load_settings()
        if unchanged.active_provider_id != "gemini" or unchanged.active_model_id != "gemini-2.5-flash":
            raise RuntimeError("Unknown-model command changed active provider/model.")

        switched = await execute_model_command("openai/gpt-5.5")
        if not switched.ok:
            raise RuntimeError(f"Expected model switch to succeed: {switched}")
        if "Switched active model to openai/gpt-5.5 (GPT-5.5)." not in switched.text:
            raise RuntimeError(f"Unexpected switch response: {switched.text}")

        persisted = await load_settings()
        if persisted.active_provider_id != "openai":
            raise RuntimeError(f"Active provider was not updated: {persisted.active_provider_id}")
        if persisted.active_model_id != "gpt-5.5":
            raise RuntimeError(f"Active model was not updated: {persisted.active_model_id}")
        if persisted.provider_configs["openai"].model != "gpt-5.5":
            raise RuntimeError(f"Provider config model was not updated: {persisted.provider_configs['openai'].model}")
    finally:
        db_path.unlink(missing_ok=True)
        db_path.with_suffix(".db.bak").unlink(missing_ok=True)


def main() -> None:
    asyncio.run(_run_scenario())
    print("PASS: /model command helper works.")


if __name__ == "__main__":
    main()
