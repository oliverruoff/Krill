#!/usr/bin/env python3
"""Regression checks for user-facing execution event messages."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.tooling.execution import (  # pylint: disable=import-outside-toplevel
        build_event_message,
        build_step_started_message,
    )

    planning_cases = {
        "repo_modify_diff_finalize_pipeline": "Planning how to update the code.",
        "fetch_validate_apply_verify_pipeline": "Planning how to fetch and apply the requested item.",
        "resolve_target_apply_confirm_pipeline": "Planning how to make and confirm the requested change.",
        "fetch_transform_publish_verify_pipeline": "Planning how to prepare and deliver the requested item.",
        "inspect_route_execute_verify_pipeline": "Planning how to complete this with the right tool.",
    }
    for pipeline_id, expected in planning_cases.items():
        actual = build_event_message("task_classified", {"pipeline_id": pipeline_id})
        if actual != expected:
            raise RuntimeError(f"Unexpected planning message for {pipeline_id}: {actual!r}")

    repo_steps = ["inspect", "modify", "validate diff", "finalize", "verify"]
    repo_messages = [build_step_started_message("repo_modify_diff_finalize_pipeline", step) for step in repo_steps]
    expected_repo_messages = [
        "Looking through the repository.",
        "Making the requested code changes.",
        "Checking the repository changes.",
        "Preparing the final response.",
        "Verifying the result.",
    ]
    if repo_messages != expected_repo_messages:
        raise RuntimeError(f"Unexpected repo step messages: {repo_messages!r}")

    step_cases = {
        ("fetch_validate_apply_verify_pipeline", "validate"): "Checking the fetched result.",
        ("resolve_target_apply_confirm_pipeline", "confirm state"): "Checking that the change took effect.",
        ("fetch_transform_publish_verify_pipeline", "publish"): "Sending or publishing the result.",
        ("inspect_route_execute_verify_pipeline", "route"): "Choosing the best tool for the job.",
        ("inspect_route_execute_verify_pipeline", "execute"): "Preparing to run the selected tool.",
    }
    for (pipeline_id, step_label), expected in step_cases.items():
        direct_message = build_step_started_message(pipeline_id, step_label)
        if direct_message != expected:
            raise RuntimeError(f"Unexpected step message for {pipeline_id}/{step_label}: {direct_message!r}")

        event_message = build_event_message(
            "step_started",
            {"pipeline_id": pipeline_id, "step_label": step_label},
        )
        if event_message != expected:
            raise RuntimeError(f"Unexpected event message for {pipeline_id}/{step_label}: {event_message!r}")

    all_messages = list(planning_cases.values()) + repo_messages + list(step_cases.values())
    confusing_phrase = "Validate diff via repo modify diff finalize pipeline."
    if confusing_phrase in all_messages:
        raise RuntimeError(f"Confusing internal workflow phrase is still visible: {confusing_phrase}")
    if any("pipeline" in message.lower() for message in all_messages):
        raise RuntimeError(f"Internal pipeline wording leaked into user messages: {all_messages!r}")

    tool_call_message = build_event_message(
        "tool_call_started",
        {
            "mcp_label": "Git Operations",
            "tool_label": "Repository Status",
        },
    )
    if tool_call_message != "Running Repository Status with Git Operations.":
        raise RuntimeError(f"Tool call message did not include the selected tool name: {tool_call_message!r}")

    print("PASS: Execution event messages are human-readable.")


if __name__ == "__main__":
    main()
