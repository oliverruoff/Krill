"""Regression checks for orchestration recovery and tool-argument hardening."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.tooling.execution import classify_task_intent, rank_tools_for_intent  # pylint: disable=import-outside-toplevel
    from app.tooling.runtime_context import reset_runtime_context, set_runtime_context  # pylint: disable=import-outside-toplevel
    from app.tooling.orchestrator import (  # pylint: disable=import-outside-toplevel
        _collect_script_catalog,
        _collect_enabled_tools,
        _invalid_planner_reason,
        _parse_planner_response,
        _repair_tool_arguments,
        _resolve_tool_alias,
        _should_keep_rewritten_arguments,
    )
    from app.config import McpConfig, ScriptDefinition, Settings  # pylint: disable=import-outside-toplevel
    from app.runtime_prompt import compose_runtime_system_prompt  # pylint: disable=import-outside-toplevel
    import app.tooling.orchestrator as orchestrator  # pylint: disable=import-outside-toplevel

    gmail_schema = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "minLength": 1},
            "format": {"type": "string", "enum": ["metadata", "full"]},
            "query": {"type": "string"},
        },
        "required": ["message_id"],
    }
    original_gmail_arguments: dict[str, object] = {"message_id": "abc123", "format": "full"}
    rewritten_gmail_arguments: dict[str, object] = {"q": "from:makerworld.com", "max_results": 20}
    repaired_gmail_arguments: dict[str, object] = _repair_tool_arguments(
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
    original_script_arguments: dict[str, object] = {
        "title": "github-issue-create-edit-delete",
        "input_json": {"operation": "list", "repo": "oliverruoff/krill"},
        "timeout_ms": 59000,
    }
    rewritten_script_arguments: dict[str, object] = {
        "title": "github-issue-create-edit-delete",
        "input_json": {"operation": "validate", "repo": "oliverruoff/krill"},
        "timeout_ms": 59000,
    }
    repaired_script_arguments: dict[str, object] = _repair_tool_arguments(
        mcp_id="scripts",
        tool_id="execute_script",
        input_schema=scripts_schema,
        original_arguments=original_script_arguments,
        candidate_arguments=rewritten_script_arguments,
    )
    repaired_script_input = cast(dict[str, object], repaired_script_arguments.get("input_json", {}))
    if repaired_script_input.get("operation") != "list":
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

    xml_tool_call = _parse_planner_response(
        '<function_calls><invoke name="Search_Entities"><arg name="search">EG Flur Licht</arg></invoke></function_calls>'
    )
    xml_plan = xml_tool_call["plan"]
    if xml_plan.get("action") != "call_tool" or xml_plan.get("tool_id") != "search_entities":
        raise RuntimeError(f"Expected XML tool call recovery. Got: {xml_plan}")
    xml_arguments = xml_plan.get("arguments")
    if not isinstance(xml_arguments, dict) or xml_arguments.get("search") != "EG Flur Licht":
        raise RuntimeError(f"Expected XML tool arguments to be recovered. Got: {xml_plan}")

    minimax_xml_tool_call = _parse_planner_response(
        '<minimax:tool_call><invoke name="brave_search">'
        '<parameter name="query">Sofitel Beijing Central hotel reviews pros cons gym 2024 2025</parameter>'
        '<parameter name="count">10</parameter>'
        '</invoke></minimax:tool_call>'
    )
    minimax_xml_plan = minimax_xml_tool_call["plan"]
    if minimax_xml_plan.get("action") != "call_tool" or minimax_xml_plan.get("tool_id") != "brave_search":
        raise RuntimeError(f"Expected MiniMax XML tool call recovery. Got: {minimax_xml_plan}")
    minimax_xml_arguments = minimax_xml_plan.get("arguments")
    if not isinstance(minimax_xml_arguments, dict) or minimax_xml_arguments.get("count") != 10:
        raise RuntimeError(f"Expected MiniMax XML parameter arguments to be recovered. Got: {minimax_xml_plan}")

    brave_alias = _resolve_tool_alias(
        [{"mcp_id": "brave_search", "tool_id": "web_search", "tool_label": "Web Search"}],
        str(minimax_xml_plan.get("mcp_id", "")),
        str(minimax_xml_plan.get("tool_id", "")),
    )
    if brave_alias != ("brave_search", "web_search"):
        raise RuntimeError(f"Expected brave_search wrapper alias to resolve to web_search. Got: {brave_alias}")

    leaked_markup_response = _parse_planner_response("<invoke>brave_search</invoke>")
    leaked_markup_plan = leaked_markup_response["plan"]
    if leaked_markup_response["recovery_mode"] != "unrecovered_tool_markup":
        raise RuntimeError(f"Expected unrecovered tool markup to be rejected. Got: {leaked_markup_response}")
    if not _invalid_planner_reason(leaked_markup_plan):
        raise RuntimeError(f"Expected unrecovered tool markup plan to be invalid. Got: {leaked_markup_plan}")
    explicit_markup_answer = {
        "action": "respond",
        "final_answer": '<minimax:tool_call><invoke name="brave_search"></invoke></minimax:tool_call>',
    }
    if not _invalid_planner_reason(explicit_markup_answer):
        raise RuntimeError("Expected raw tool markup in final_answer to be invalid.")

    home_assistant_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
        },
        "required": ["query"],
    }
    repaired_home_assistant_arguments: dict[str, object] = _repair_tool_arguments(
        mcp_id="home_assistant",
        tool_id="search_entities",
        input_schema=home_assistant_schema,
        original_arguments={},
        candidate_arguments=xml_arguments,
    )
    if repaired_home_assistant_arguments.get("query") != "EG Flur Licht":
        raise RuntimeError(
            "Expected search alias to normalize to query for Home Assistant search_entities. "
            f"Got: {repaired_home_assistant_arguments}"
        )

    assistant_context = set_runtime_context(
        source_channel="telegram",
        source_chat_id="group-1",
        source_user_role="assistant_usage",
        allowed_mcp_ids=["shell_access", "git_ops"],
    )
    try:
        implicit_default_settings = Settings(mcp_configs={"git_ops": McpConfig(enabled=True, params={})})
        assistant_tools = _collect_enabled_tools(implicit_default_settings)
    finally:
        reset_runtime_context(assistant_context)
    assistant_mcp_ids = {str(entry.get("mcp_id", "")) for entry in assistant_tools}
    if "shell_access" in assistant_mcp_ids:
        raise RuntimeError(
            "Expected assistant_usage access to ignore implicitly default-enabled MCPs like shell_access. "
            f"Got: {sorted(assistant_mcp_ids)}"
        )
    if "git_ops" not in assistant_mcp_ids:
        raise RuntimeError(f"Expected explicitly enabled git_ops MCP to remain available. Got: {sorted(assistant_mcp_ids)}")

    assistant_prompt = compose_runtime_system_prompt(
        settings=Settings(
            mcp_configs={
                "brain_access": McpConfig(enabled=True, params={}),
                "git_ops": McpConfig(enabled=True, params={}),
            },
        ),
        source_channel="telegram",
        source_user_role="assistant_usage",
        allowed_mcp_ids=["brain_access"],
    )
    if "`brain_access`" not in assistant_prompt:
        raise RuntimeError("Expected runtime prompt to include explicitly allowed assistant_usage MCP.")
    if "`git_ops`" in assistant_prompt:
        raise RuntimeError("Expected runtime prompt to hide MCPs not allowed for assistant_usage.")

    no_tools_prompt = compose_runtime_system_prompt(
        settings=Settings(mcp_configs={"brain_access": McpConfig(enabled=True, params={})}),
        source_channel="telegram",
        source_user_role="assistant_usage",
        allowed_mcp_ids=[],
    )
    if "Enabled tools and capabilities are available" in no_tools_prompt:
        raise RuntimeError("Expected runtime prompt to omit tool capability summary when assistant_usage allowlist is empty.")

    async def fake_list_scripts() -> list[ScriptDefinition]:
        return [
            ScriptDefinition(
                id="script-1",
                title="Danger Script",
                description="Does something sensitive",
                instructions="Use only when scripts access is allowed.",
                file_name="danger-script.py",
            )
        ]

    original_list_scripts = orchestrator.list_scripts
    orchestrator.list_scripts = fake_list_scripts
    script_context = set_runtime_context(
        source_channel="telegram",
        source_chat_id="group-1",
        source_user_role="assistant_usage",
        allowed_mcp_ids=["brain_access"],
    )
    try:
        scripts_settings = Settings(mcp_configs={"scripts": McpConfig(enabled=True, params={})})
        blocked_scripts_catalog = await _collect_script_catalog(scripts_settings)
    finally:
        reset_runtime_context(script_context)
        orchestrator.list_scripts = original_list_scripts
    if blocked_scripts_catalog:
        raise RuntimeError(
            "Expected assistant_usage script catalog to be hidden when scripts MCP is not allowed. "
            f"Got: {blocked_scripts_catalog}"
        )

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

    hotel_research_intent = classify_task_intent(
        "Recherchiere gründlich pro Hotel und gib uns eine Rangfolge nach Bewertungen und Gym.",
        [{"mcp_id": "brave_search"}, {"mcp_id": "shell_access"}],
    )
    if "repo_modification" in hotel_research_intent.get("categories", []):
        raise RuntimeError(f"Expected German hotel research not to classify as repo work. Got: {hotel_research_intent}")
    if "web_research" not in hotel_research_intent.get("categories", []):
        raise RuntimeError(f"Expected German hotel research to classify as web research. Got: {hotel_research_intent}")
    if hotel_research_intent.get("preferred_mcp_ids", [None])[0] != "brave_search":
        raise RuntimeError(f"Expected web research to prefer Brave Search. Got: {hotel_research_intent}")

    repo_intent = classify_task_intent(
        "Modify this repo and show me the diff.",
        [{"mcp_id": "git_ops"}, {"mcp_id": "brave_search"}],
    )
    if "repo_modification" not in repo_intent.get("categories", []):
        raise RuntimeError(f"Expected explicit repo prompt to classify as repo work. Got: {repo_intent}")

    print("PASS: orchestration recovery hardening checks succeeded.")


if __name__ == "__main__":
    asyncio.run(main())
