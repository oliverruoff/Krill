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
    from app.providers import get_provider  # pylint: disable=import-outside-toplevel

    openai_provider = get_provider("openai")
    original_openai_models = list(openai_provider.available_models) if openai_provider is not None else []
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
        openai_line = next(
            (
                line
                for line in listed.text.splitlines()
                if "openai/gpt-5.5 - GPT-5.5" in line
            ),
            "",
        )
        if not openai_line or not openai_line.partition(".")[0].strip().isdigit():
            raise RuntimeError(f"Model list did not include connected OpenAI GPT-5.5: {listed.text}")
        if "openrouter/" in listed.text:
            raise RuntimeError(f"Model list included unconnected OpenRouter provider: {listed.text}")
        if "Use /model <number> or /model <provider>/<model> to switch." not in listed.text:
            raise RuntimeError(f"Model list did not include indexed command help: {listed.text}")

        indexed_switch = await execute_model_command("1")
        if not indexed_switch.ok:
            raise RuntimeError(f"Expected indexed model switch to succeed: {indexed_switch}")
        if "Switched active model to gemini/gemini-3.1-pro-preview" not in indexed_switch.text:
            raise RuntimeError(f"Unexpected indexed switch response: {indexed_switch.text}")
        persisted = await load_settings()
        if persisted.active_provider_id != "gemini" or persisted.active_model_id != "gemini-3.1-pro-preview":
            raise RuntimeError(
                f"Indexed switch did not select first listed model: {persisted.active_provider_id}/{persisted.active_model_id}"
            )

        invalid_indexes = ["0", "-1", "999", "2.5"]
        for invalid_index in invalid_indexes:
            before_invalid = await load_settings()
            invalid_result = await execute_model_command(invalid_index)
            if invalid_result.ok:
                raise RuntimeError(f"Invalid index unexpectedly succeeded for {invalid_index}: {invalid_result}")
            after_invalid = await load_settings()
            if (
                after_invalid.active_provider_id != before_invalid.active_provider_id
                or after_invalid.active_model_id != before_invalid.active_model_id
            ):
                raise RuntimeError(f"Invalid index {invalid_index} changed active provider/model.")

        unknown_provider = await execute_model_command("openrouter/openai/gpt-5.4")
        if unknown_provider.ok or "Provider 'openrouter' is not connected." not in unknown_provider.text:
            raise RuntimeError(f"Unexpected unknown-provider result: {unknown_provider}")
        unchanged = await load_settings()
        if unchanged.active_provider_id != "gemini" or unchanged.active_model_id != "gemini-3.1-pro-preview":
            raise RuntimeError("Unknown-provider command changed active provider/model.")

        unknown_model = await execute_model_command("openai/not-real")
        if unknown_model.ok or "Model 'not-real' is not available for provider 'openai'." not in unknown_model.text:
            raise RuntimeError(f"Unexpected unknown-model result: {unknown_model}")
        unchanged = await load_settings()
        if unchanged.active_provider_id != "gemini" or unchanged.active_model_id != "gemini-3.1-pro-preview":
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

        if openai_provider is None:
            raise RuntimeError("OpenAI provider was not registered.")
        dynamic_model = {
            "id": "gpt-dynamic-index-test",
            "label": "GPT Dynamic Index Test",
            "token_limit": 12345,
            "supports_images": False,
        }
        openai_provider.available_models.append(dynamic_model)
        dynamic_listed = await execute_model_command("")
        dynamic_line = next(
            (
                line
                for line in dynamic_listed.text.splitlines()
                if "openai/gpt-dynamic-index-test - GPT Dynamic Index Test" in line
            ),
            "",
        )
        if not dynamic_line:
            raise RuntimeError(f"Dynamic provider model was not listed with an index: {dynamic_listed.text}")
        dynamic_index = dynamic_line.partition(".")[0].strip()
        if not dynamic_index.isdigit():
            raise RuntimeError(f"Dynamic provider model line did not start with a numeric index: {dynamic_line}")

        dynamic_index_switch = await execute_model_command(dynamic_index)
        if not dynamic_index_switch.ok:
            raise RuntimeError(f"Expected dynamic indexed model switch to succeed: {dynamic_index_switch}")
        persisted = await load_settings()
        if persisted.active_provider_id != "openai" or persisted.active_model_id != "gpt-dynamic-index-test":
            raise RuntimeError(
                f"Dynamic indexed switch failed: {persisted.active_provider_id}/{persisted.active_model_id}"
            )

        exact_dynamic_switch = await execute_model_command("openai/gpt-dynamic-index-test")
        if not exact_dynamic_switch.ok:
            raise RuntimeError(f"Expected exact dynamic model switch to succeed: {exact_dynamic_switch}")
    finally:
        if openai_provider is not None:
            openai_provider.available_models = original_openai_models
        db_path.unlink(missing_ok=True)
        db_path.with_suffix(".db.bak").unlink(missing_ok=True)


def main() -> None:
    asyncio.run(_run_scenario())
    print("PASS: /model command helper works.")


if __name__ == "__main__":
    main()
