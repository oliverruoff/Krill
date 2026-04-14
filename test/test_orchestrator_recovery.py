"""Regression checks for orchestration recovery and tool-argument hardening."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.tooling.execution import rank_tools_for_intent  # pylint: disable=import-outside-toplevel
    from app.tooling.orchestrator import (  # pylint: disable=import-outside-toplevel
        _parse_planner_response,
        _repair_tool_arguments,
        _should_keep_rewritten_arguments,
    )

    gmail_schema = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "minLength": 1},
            "format": {"type": "string", "enum": ["metadata", "full"]},
            "query": {"type": "string"},
        },
        "required": ["message_id"],
    }
    original_gmail_arguments = {"message_id": "abc123", "format": "full"}
    rewritten_gmail_arguments = {"q": "from:makerworld.com", "max_results": 20}
    repaired_gmail_arguments = _repair_tool_arguments(
        mcp_id="google_services",
        tool_id="gmail_get_message",
        input_schema=gmail_schema,
        original_arguments=original_gmail_arguments,
        candidate_arguments=rewritten_gmail_arguments,
    )
    if repaired_gmail_arguments.get("message_id") != "abc123":
        raise RuntimeError(f"Expected gmail message_id to be preserved. Got: {repaired_gmail_arguments}")
    if repaired_gmail_arguments.get("query") != "from:makerworld.com":
        raise RuntimeError(f"Expected q alias to normalize to query. Got: {repaired_gmail_arguments}")
    if not _should_keep_rewritten_arguments(gmail_schema, original_gmail_arguments, repaired_gmail_arguments):
        raise RuntimeError("Expected repaired gmail arguments to remain acceptable after preserving required fields.")

    scripts_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "input_json": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "repo": {"type": "string"},
                },
            },
            "timeout_ms": {"type": "integer"},
        },
        "required": ["title"],
    }
    original_script_arguments = {
        "title": "github-issue-create-edit-delete",
        "input_json": {"operation": "list", "repo": "oliverruoff/krill"},
        "timeout_ms": 59000,
    }
    rewritten_script_arguments = {
        "title": "github-issue-create-edit-delete",
        "input_json": {"operation": "validate", "repo": "oliverruoff/krill"},
        "timeout_ms": 59000,
    }
    repaired_script_arguments = _repair_tool_arguments(
        mcp_id="scripts",
        tool_id="execute_script",
        input_schema=scripts_schema,
        original_arguments=original_script_arguments,
        candidate_arguments=rewritten_script_arguments,
    )
    if repaired_script_arguments.get("input_json", {}).get("operation") != "list":
        raise RuntimeError(f"Expected script operation to stay stable. Got: {repaired_script_arguments}")

    wrapped_tool_call = _parse_planner_response(
        '[TOOL_CALL] {tool => "gmail_list_messages", args => { --query "from:makerworld.com" --max_results 20 }} [/TOOL_CALL]'
    )
    wrapped_plan = wrapped_tool_call["plan"]
    if wrapped_plan.get("action") != "call_tool" or wrapped_plan.get("tool_id") != "gmail_list_messages":
        raise RuntimeError(f"Expected wrapped tool call recovery. Got: {wrapped_plan}")
    if wrapped_plan.get("mcp_id") != "google_services":
        raise RuntimeError(f"Expected gmail wrapper to map to google_services. Got: {wrapped_plan}")
    wrapped_arguments = wrapped_plan.get("arguments")
    if not isinstance(wrapped_arguments, dict) or wrapped_arguments.get("query") != "from:makerworld.com":
        raise RuntimeError(f"Expected wrapped query arguments to be recovered. Got: {wrapped_plan}")
    if wrapped_arguments.get("max_results") != 20:
        raise RuntimeError(f"Expected wrapped max_results argument to be recovered. Got: {wrapped_plan}")

    plain_text = _parse_planner_response("Ja, heute kam genau eine MakerWorld-Mail rein.")
    plain_plan = plain_text["plan"]
    if plain_plan.get("action") != "respond" or not str(plain_plan.get("final_answer", "")).strip():
        raise RuntimeError(f"Expected plain text planner output to salvage as respond. Got: {plain_plan}")

    ranked = rank_tools_for_intent(
        [
            {"mcp_id": "shell_access", "tool_id": "execute_shell"},
            {"mcp_id": "google_services", "tool_id": "gmail_list_messages"},
            {"mcp_id": "brave_search", "tool_id": "search"},
        ],
        {
            "categories": ["structured_data_fetch"],
            "preferred_mcp_ids": ["google_services", "shell_access", "brave_search"],
            "fallback_mcp_ids": [],
        },
    )
    ranked_mcp_ids = [str(entry.get("mcp_id", "")) for entry in ranked]
    if ranked_mcp_ids.index("shell_access") < ranked_mcp_ids.index("brave_search"):
        raise RuntimeError(f"Expected shell_access to be demoted for normal fetch tasks. Got: {ranked_mcp_ids}")

    print("PASS: orchestration recovery hardening checks succeeded.")


if __name__ == "__main__":
    asyncio.run(main())
