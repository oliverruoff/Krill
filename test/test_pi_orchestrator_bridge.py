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

pending = {}
for line in sys.stdin:
    payload = json.loads(line)
    request_id = payload.get("request_id", "")
    if payload.get("type") == "health":
        print(json.dumps({"type": "ready", "request_id": request_id}), flush=True)
        continue
    if payload.get("type") == "shutdown":
        break
    if payload.get("type") == "tool_result":
        call_id = payload.get("id")
        request_id = pending.pop(call_id, request_id)
        print(json.dumps({"type": "event", "request_id": request_id, "event": {"type": "tool_execution_end", "toolName": "krill_brain_access_probe", "toolCallId": call_id, "isError": not payload.get("ok", False)}}), flush=True)
        print(json.dumps({"type": "event", "request_id": request_id, "event": {"type": "agent_end", "messages": [{"role": "assistant", "content": "done"}]}}), flush=True)
        print(json.dumps({"type": "result", "request_id": request_id, "text": f"Pi final answer {request_id}", "stats": {"tokens": {"total": 321}, "contextUsage": {"tokens": 321, "contextWindow": 1000, "percent": 32.1}}}), flush=True)
        continue
    if payload.get("type") != "run":
        continue
    request = payload.get("request", {})
    request_id = payload.get("request_id", request.get("request_id", ""))
    print(json.dumps({"type": "event", "request_id": request_id, "event": {"type": "agent_start"}}), flush=True)
    if request.get("message") == "history-check":
        roles = ",".join([entry.get("role", "") for entry in request.get("history", [])])
        print(json.dumps({"type": "result", "request_id": request_id, "text": f"history roles: {roles}", "stats": {"tokens": {"total": 321}}}), flush=True)
        continue
    tools = request.get("krill_tools") or []
    if tools:
        tool = tools[0]
        call_id = f"call-{request_id}"
        pending[call_id] = request_id
        print(json.dumps({"type": "tool_call", "request_id": request_id, "id": call_id, "mcp_id": tool["mcp_id"], "mcp_label": tool["mcp_label"], "tool_id": tool["tool_id"], "tool_label": tool["tool_label"], "arguments": {"value": request.get("message", "")}}), flush=True)
    else:
        print(json.dumps({"type": "result", "request_id": request_id, "text": f"Pi final answer {request_id}", "stats": {"tokens": {"total": 321}}}), flush=True)
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
    original_manager = pi_orchestrator._PI_MANAGER
    fake_plugin = FakePlugin()
    native_plugin = NativeOverlapPlugin()
    pi_orchestrator.get_all_mcps = lambda: {
        "brain_access": fake_plugin,
        "shell_access": native_plugin,
    }
    os.environ["KRILL_PI_SIDECAR_COMMAND"] = f'"{sys.executable}" "{fake_sidecar_path}"'
    pi_orchestrator._PI_MANAGER = pi_orchestrator.PiSidecarManager()

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

        await pi_orchestrator.start_pi_runtime()
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

        second_result, third_result = await asyncio.gather(
            pi_orchestrator.generate_with_pi(
                settings=settings,
                prompt="second",
                system_prompt="system",
                model="",
                api_key="",
                history=[],
                provider_id="openai",
            ),
            pi_orchestrator.generate_with_pi(
                settings=settings,
                prompt="third",
                system_prompt="system",
                model="",
                api_key="",
                history=[],
                provider_id="openai",
            ),
        )
        history_result = await pi_orchestrator.generate_with_pi(
            settings=settings,
            prompt="history-check",
            system_prompt="system",
            model="",
            api_key="",
            history=[
                {"role": "system", "content": "Call the user Oli."},
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ],
            provider_id="openai",
        )
    finally:
        await pi_orchestrator.stop_pi_runtime()
        pi_orchestrator._PI_MANAGER = original_manager
        reset_runtime_context(context_token)
        pi_orchestrator.get_all_mcps = original_registry
        if original_command is None:
            os.environ.pop("KRILL_PI_SIDECAR_COMMAND", None)
        else:
            os.environ["KRILL_PI_SIDECAR_COMMAND"] = original_command

    if not result["text"].startswith("Pi final answer "):
        raise RuntimeError(f"Unexpected Pi bridge text: {result}")
    if second_result["text"] == third_result["text"]:
        raise RuntimeError(f"Expected concurrent requests to route by request_id. Got: {second_result}, {third_result}")
    if "system,user,assistant" not in history_result["text"]:
        raise RuntimeError(f"Expected Krill chat history to be sent to Pi. Got: {history_result}")
    if result["used_tokens"] != 321:
        raise RuntimeError(f"Expected Pi token stats to map to used_tokens. Got: {result}")
    if any(event.get("message") == "Pi finished the agent run." for event in result["execution_events"]):
        raise RuntimeError(f"Pi agent_end leaked as user-visible progress. Got: {result['execution_events']}")
    expected_values = ["hello", "second", "third"]
    actual_values = [str(call[1].get("value", "")) for call in fake_plugin.calls]
    if actual_values != expected_values:
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
