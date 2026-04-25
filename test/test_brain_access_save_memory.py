"""Standalone tests for explicit Brain Access memory saves."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_brain_access_memory_test_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    try:
        from app.config import ProviderConfig, ensure_settings_file, load_settings, save_settings  # pylint: disable=import-outside-toplevel
        import app.mcps.brain_access as brain_access_module  # pylint: disable=import-outside-toplevel
        from app.mcps.brain_access import BrainAccessMCP  # pylint: disable=import-outside-toplevel

        await ensure_settings_file()
        plugin = BrainAccessMCP()

        core_result = await plugin.call_tool(
            "save_memory",
            {
                "memory_text": "The user prefers direct answers.",
                "memory_type": "core",
            },
            {},
        )
        if core_result.get("ok") is not True or core_result.get("memory_type") != "core":
            raise RuntimeError(f"Core memory save returned unexpected result: {core_result!r}")

        normal_result = await plugin.call_tool(
            "save_memory",
            {
                "memory_text": "The user is currently testing deterministic memory saves.",
                "memory_type": "normal",
            },
            {},
        )
        if normal_result.get("ok") is not True or normal_result.get("memory_type") != "normal":
            raise RuntimeError(f"Normal memory save returned unexpected result: {normal_result!r}")

        phrased_result = await plugin.call_tool(
            "save_memory",
            {
                "memory_text": "Remember as core memory: The user likes memory saves to be visible immediately.",
            },
            {},
        )
        if phrased_result.get("ok") is not True or phrased_result.get("memory_type") != "core":
            raise RuntimeError(f"Explicitly phrased core memory save returned unexpected result: {phrased_result!r}")
        if phrased_result.get("memory_text") != "The user likes memory saves to be visible immediately.":
            raise RuntimeError(f"Command phrasing was not stripped: {phrased_result!r}")

        settings = await load_settings()
        settings.active_provider_id = "gemini"
        settings.provider_configs["gemini"] = ProviderConfig(api_key="fake-key", model="gemini-2.5-flash")
        await save_settings(settings)

        original_generate_with_retries = brain_access_module.generate_with_retries

        async def fake_generate_with_retries(**kwargs):
            prompt = str(kwargs.get("prompt", ""))
            if "Bitte als Kern-Erinnerung speichern" not in prompt:
                return '{"memory_text": "", "requested_memory_type": "", "confidence": "low", "reason": ""}', 0
            return (
                '{"memory_text": "Der Nutzer mag semantische Speichererkennung.", '
                '"requested_memory_type": "core", "confidence": "high", '
                '"reason": "The user explicitly requested a core memory semantically."}',
                0,
            )

        brain_access_module.generate_with_retries = fake_generate_with_retries
        try:
            semantic_result = await plugin.call_tool(
                "save_memory",
                {
                    "memory_text": "Bitte als Kern-Erinnerung speichern: Der Nutzer mag semantische Speichererkennung.",
                },
                {},
            )
        finally:
            brain_access_module.generate_with_retries = original_generate_with_retries

        if semantic_result.get("ok") is not True or semantic_result.get("memory_type") != "core":
            raise RuntimeError(f"Semantic core memory save returned unexpected result: {semantic_result!r}")
        if semantic_result.get("memory_text") != "Der Nutzer mag semantische Speichererkennung.":
            raise RuntimeError(f"Semantic memory text extraction failed: {semantic_result!r}")

        duplicate_result = await plugin.call_tool(
            "save_memory",
            {
                "memory_text": "The user prefers direct answers.",
                "memory_type": "core",
            },
            {},
        )
        if duplicate_result.get("ok") is not True or duplicate_result.get("status") != "duplicate_skipped":
            raise RuntimeError(f"Duplicate memory save returned unexpected result: {duplicate_result!r}")

        settings = await load_settings()
        core_memories = [memory.content for memory in settings.core_memories]
        normal_memories = [memory.content for memory in settings.normal_memories]

        if core_memories.count("The user prefers direct answers.") != 1:
            raise RuntimeError(f"Explicit core memory was not persisted exactly once: {core_memories!r}")
        if "The user likes memory saves to be visible immediately." not in core_memories:
            raise RuntimeError(f"Explicitly phrased core memory was not persisted: {core_memories!r}")
        if "Der Nutzer mag semantische Speichererkennung." not in core_memories:
            raise RuntimeError(f"Semantic core memory was not persisted: {core_memories!r}")
        if normal_memories != ["The user is currently testing deterministic memory saves."]:
            raise RuntimeError(f"Explicit normal memory was not persisted correctly: {normal_memories!r}")

        print("Brain Access explicit memory save tests passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
