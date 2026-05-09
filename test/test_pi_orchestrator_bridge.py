#!/usr/bin/env python3
"""Focused checks for the Pi runtime bridge and Krill MCP callbacks."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any


FAKE_SIDECAR = r'''
import json
import sys

pending_tool = False
for line in sys.stdin:
    payload = json.loads(line)
    if payload.get("type") == "tool_result":
        print(json.dumps({"type": "event", "event": {"type": "tool_execution_end", "toolName": "krill_brain_access_probe", "toolCallId": payload.get("id"), "isError": not payload.get("ok", False)}}), flush=True)
        print(json.dumps({"type": "event", "event": {"type": "agent_end", "messages": [{"role": "assistant", "content": "done"}]}}), flush=True)
        print(json.dumps({"type": "result", "text": "Pi final answer", "stats": {"tokens": {"total": 321}, "contextUsage": {"tokens": 321, "contextWindow": 1000, "percent": 32.1}}}), flush=True)
        break
    if payload.get("type") != "run":
        continue
    request = payload.get("request", {})
    print(json.dumps({"type": "event", "event": {"type": "agent_start"}}), flush=True)
    tools = request.get("krill_tools") or []
    if tools:
        tool = tools[0]
        print(json.dumps({"type": "tool_call", "id": "call-1", "mcp_id": tool["mcp_id"], "mcp_label": tool["mcp_label"], "tool_id": tool["tool_id"], "tool_label": tool["tool_label"], "arguments": {"value": "hello"}}), flush=True)
    else:
        print(json.dumps({"type": "result", "text": "Pi final answer", "stats": {"tokens": {"total": 321}}}), flush=True)
        break
'''


class FakeToolSpec:
    def __init__(self, tool_id: str, label: str = "Probe Tool") -> None:
        self.id = tool_id
        self.label = label
        self.description = "Probe tool description"
        self.input_schema: dict[str, object] = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        }


class FakePlugin:
    mcp_id = "brain_access"
    display_name = "Brain Access"
    description = "Fake brain access"
    config_fields: list[Any] = []
    default_enabled = False

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def tool_specs(self) -> list[FakeToolSpec]:
        return [FakeToolSpec("probe")]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return True, "ok"

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        self.calls.append((tool_id, arguments, params))
        return {"ok": True, "echo": arguments.get("value")}

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        return ""


class NativeOverlapPlugin(FakePlugin):
    mcp_id = "shell_access"
    display_name = "Shell Access"

    def tool_specs(self) -> list[FakeToolSpec]:
        return [FakeToolSpec("execute_shell", "Execute Shell")]


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.config import McpConfig, ProviderConfig, Settings  # pylint: disable=import-outside-toplevel
    from app.tooling.runtime_context import reset_runtime_context, set_runtime_context  # pylint: disable=import-outside-toplevel
    import app.tooling.pi_orchestrator as pi_orchestrator  # pylint: disable=import-outside-toplevel

    fake_sidecar_path = repo_root / "tmp_verify_data" / "fake_pi_sidecar.py"
    fake_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    fake_sidecar_path.write_text(FAKE_SIDECAR, encoding="utf-8")

    original_command = os.environ.get("KRILL_PI_SIDECAR_COMMAND")
    original_registry = pi_orchestrator.get_all_mcps
    fake_plugin = FakePlugin()
    native_plugin = NativeOverlapPlugin()
    pi_orchestrator.get_all_mcps = lambda: {
        "brain_access": fake_plugin,
        "shell_access": native_plugin,
    }
    os.environ["KRILL_PI_SIDECAR_COMMAND"] = f'"{sys.executable}" "{fake_sidecar_path}"'

    context_token = set_runtime_context(
        source_channel="gateway",
        source_chat_id="chat-1",
        source_request_id="request-1",
    )
    try:
        settings = Settings(
            active_provider_id="openai",
            provider_configs={"openai": ProviderConfig(api_key="test-key", model="gpt-5.1")},
            mcp_configs={
                "brain_access": McpConfig(enabled=True, params={"mode": "test"}),
                "shell_access": McpConfig(enabled=True, params={}),
            },
        )
        tools = pi_orchestrator.collect_pi_krill_tools(settings)
        tool_ids = {(entry["mcp_id"], entry["tool_id"]) for entry in tools}
        if ("brain_access", "probe") not in tool_ids:
            raise RuntimeError(f"Expected app-specific Krill MCP to be exposed. Got: {tool_ids}")
        if any(mcp_id == "shell_access" for mcp_id, _tool_id in tool_ids):
            raise RuntimeError(f"Expected Pi-native shell_access to be hidden. Got: {tool_ids}")

        events = []

        async def on_event(event: dict[str, object]) -> None:
            events.append(event)

        result = await pi_orchestrator.generate_with_pi(
            settings=settings,
            prompt="hello",
            system_prompt="system",
            model="",
            api_key="",
            history=[],
            provider_id="openai",
            on_execution_event=on_event,
        )
    finally:
        reset_runtime_context(context_token)
        pi_orchestrator.get_all_mcps = original_registry
        if original_command is None:
            os.environ.pop("KRILL_PI_SIDECAR_COMMAND", None)
        else:
            os.environ["KRILL_PI_SIDECAR_COMMAND"] = original_command

    if result["text"] != "Pi final answer":
        raise RuntimeError(f"Unexpected Pi bridge text: {result}")
    if result["used_tokens"] != 321:
        raise RuntimeError(f"Expected Pi token stats to map to used_tokens. Got: {result}")
    if fake_plugin.calls != [("probe", {"value": "hello"}, {"mode": "test"})]:
        raise RuntimeError(f"Expected MCP callback with saved params. Got: {fake_plugin.calls}")
    if not any(event.get("event_type") == "tool_call_started" for event in events):
        raise RuntimeError(f"Expected tool progress events. Got: {events}")

    try:
        pi_orchestrator._resolve_pi_provider(
            settings=Settings(active_provider_id="google_gemini_oauth"),
            provider_id="google_gemini_oauth",
            model="gemini-2.5-flash",
            api_key="token",
        )
    except RuntimeError as exc:
        if "not supported" not in str(exc):
            raise RuntimeError(f"Unsupported provider error was not actionable: {exc}") from exc
    else:
        raise RuntimeError("Expected unsupported Pi provider mapping to fail clearly.")

    print("PASS: Pi orchestrator bridge checks succeeded.")


if __name__ == "__main__":
    asyncio.run(main())
