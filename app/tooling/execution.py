"""Execution events, task intent helpers, and cooperative cancellation registry."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, TypedDict


class ExecutionEvent(TypedDict, total=False):
    event_type: str
    stage: str
    message: str
    detail: str
    pipeline_id: str
    categories: list[str]
    mcp_id: str
    mcp_label: str
    tool_id: str
    tool_label: str
    step_index: int
    call_id: str
    reason: str


class TaskIntent(TypedDict, total=False):
    categories: list[str]
    pipeline_id: str
    preferred_mcp_ids: list[str]
    fallback_mcp_ids: list[str]
    completion_criteria: list[str]
    validation_focus: list[str]
    artifact_type: str
    source_type: str


class ValidationResult(TypedDict):
    passed: bool
    validator: str
    detail: str


class RegisteredExecution(TypedDict):
    token: "CancellationToken"
    task: asyncio.Task[Any] | None
    conversation_key: str
    request_id: str


class CancellationToken:
    """Cooperative cancellation token shared across orchestration layers."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.reason = ""

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "") -> None:
        if self._event.is_set():
            return
        self.reason = str(reason or "").strip()
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            detail = self.reason or "Execution cancelled."
            raise asyncio.CancelledError(detail)


_EXECUTION_REGISTRY_LOCK = asyncio.Lock()
_EXECUTIONS_BY_REQUEST_ID: dict[str, RegisteredExecution] = {}
_EXECUTIONS_BY_CONVERSATION: dict[str, set[str]] = {}

_CATEGORY_TOOL_PREFERENCES: dict[str, list[str]] = {
    "repo_modification": ["opencode", "git_ops", "local_files", "browser_control", "ssh_control"],
    "external_file_retrieval": ["google_services", "local_files", "browser_control", "brave_search"],
    "browser_interaction": ["browser_control", "google_services", "brave_search"],
    "structured_data_fetch": ["google_services", "home_assistant", "brave_search", "browser_control"],
    "home_automation_change": ["home_assistant", "ssh_control", "browser_control"],
    "communication_task": ["google_services", "whatsapp", "browser_control"],
    "memory_task": ["memory_access"],
}


def build_conversation_key(source_channel: str, source_chat_id: str) -> str:
    normalized_channel = str(source_channel or "gateway").strip() or "gateway"
    normalized_chat_id = str(source_chat_id or "").strip()
    return f"{normalized_channel}:{normalized_chat_id}"


async def register_execution(
    *,
    conversation_key: str,
    request_id: str,
    token: CancellationToken,
    task: asyncio.Task[Any] | None,
) -> None:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return
    async with _EXECUTION_REGISTRY_LOCK:
        _EXECUTIONS_BY_REQUEST_ID[normalized_request_id] = {
            "token": token,
            "task": task,
            "conversation_key": str(conversation_key or "").strip(),
            "request_id": normalized_request_id,
        }
        if conversation_key:
            keys = _EXECUTIONS_BY_CONVERSATION.setdefault(conversation_key, set())
            keys.add(normalized_request_id)


async def unregister_execution(*, request_id: str, conversation_key: str) -> None:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return
    async with _EXECUTION_REGISTRY_LOCK:
        _EXECUTIONS_BY_REQUEST_ID.pop(normalized_request_id, None)
        if conversation_key:
            keys = _EXECUTIONS_BY_CONVERSATION.get(conversation_key)
            if keys is not None:
                keys.discard(normalized_request_id)
                if not keys:
                    _EXECUTIONS_BY_CONVERSATION.pop(conversation_key, None)


async def cancel_registered_executions(
    *,
    request_ids: list[str] | None = None,
    conversation_key: str = "",
    reason: str = "",
) -> int:
    targets: list[RegisteredExecution] = []
    async with _EXECUTION_REGISTRY_LOCK:
        normalized_ids = [str(item or "").strip() for item in (request_ids or []) if str(item or "").strip()]
        for request_id in normalized_ids:
            execution = _EXECUTIONS_BY_REQUEST_ID.get(request_id)
            if execution is not None:
                targets.append(execution)
        if conversation_key:
            for request_id in sorted(_EXECUTIONS_BY_CONVERSATION.get(conversation_key, set())):
                execution = _EXECUTIONS_BY_REQUEST_ID.get(request_id)
                if execution is not None and execution not in targets:
                    targets.append(execution)

    cancelled = 0
    for execution in targets:
        token = execution["token"]
        task = execution.get("task")
        if not token.is_cancelled:
            token.cancel(reason)
            cancelled += 1
        if task is not None and not task.done():
            task.cancel()
    return cancelled


def classify_task_intent(prompt: str, enabled_tools: list[dict[str, Any]]) -> TaskIntent:
    lowered = str(prompt or "").strip().lower()
    categories: list[str] = []
    artifact_type = "text"
    source_type = "direct_text"

    if any(token in lowered for token in ("commit", "branch", "repo", "repository", "pr", "pull request", "diff", "codebase")):
        categories.append("repo_modification")
        artifact_type = "code_file"
        source_type = "repo_file"
    if any(token in lowered for token in ("download", "fetch file", "replace file", "drive", "attachment", "image", "pdf", "csv", "json", "yaml")):
        categories.append("external_file_retrieval")
        artifact_type = "binary_file" if any(token in lowered for token in ("image", "pdf", "zip", "binary")) else artifact_type
        if "http://" in lowered or "https://" in lowered:
            source_type = "direct_url"
        elif any(token in lowered for token in ("drive", "gmail", "calendar")):
            source_type = "api_backed_remote"
    if any(token in lowered for token in ("browser", "click", "page", "website", "log in", "login", "form", "open the page")):
        categories.append("browser_interaction")
        source_type = "html_page"
    if any(token in lowered for token in ("calendar", "gmail", "email", "drive", "sheet", "spreadsheet", "entity", "state", "weather")):
        categories.append("structured_data_fetch")
    if any(token in lowered for token in ("home assistant", "light", "switch", "thermostat", "automation", "turn on", "turn off")):
        categories.append("home_automation_change")
    if any(token in lowered for token in ("email", "send message", "whatsapp", "calendar invite", "reply to", "draft")):
        categories.append("communication_task")
    if any(token in lowered for token in ("remember", "memorize", "don't forget", "do not forget")):
        categories.append("memory_task")

    if not categories:
        categories.append("structured_data_fetch")

    preferred: list[str] = []
    fallback: list[str] = []
    for category in categories:
        for mcp_id in _CATEGORY_TOOL_PREFERENCES.get(category, []):
            if mcp_id not in preferred:
                preferred.append(mcp_id)
    for mcp_id in [str(entry.get("mcp_id", "")) for entry in enabled_tools]:
        if mcp_id and mcp_id not in preferred and mcp_id not in fallback:
            fallback.append(mcp_id)

    pipeline_id = _select_pipeline_id(categories)
    completion_criteria = _build_completion_criteria(categories)
    validation_focus = _build_validation_focus(categories)
    return {
        "categories": categories,
        "pipeline_id": pipeline_id,
        "preferred_mcp_ids": preferred,
        "fallback_mcp_ids": fallback,
        "completion_criteria": completion_criteria,
        "validation_focus": validation_focus,
        "artifact_type": artifact_type,
        "source_type": source_type,
    }


def rank_tools_for_intent(enabled_tools: list[dict[str, Any]], intent: TaskIntent) -> list[dict[str, Any]]:
    preferred_order = intent.get("preferred_mcp_ids", [])
    fallback_order = intent.get("fallback_mcp_ids", [])
    order_map = {mcp_id: index for index, mcp_id in enumerate(preferred_order + fallback_order, start=1)}

    def sort_key(entry: dict[str, Any]) -> tuple[int, str, str]:
        mcp_id = str(entry.get("mcp_id", ""))
        return (order_map.get(mcp_id, 999), mcp_id, str(entry.get("tool_id", "")))

    return sorted(enabled_tools, key=sort_key)


def build_event_message(event_type: str, payload: dict[str, Any]) -> str:
    mcp_label = str(payload.get("mcp_label", "") or payload.get("mcp_id", "") or "tool").strip()
    tool_label = str(payload.get("tool_label", "") or payload.get("tool_id", "") or "action").strip()
    stage = str(payload.get("stage", "")).strip()
    if event_type == "task_started":
        return str(payload.get("message", "Starting work.")).strip() or "Starting work."
    if event_type == "task_classified":
        pipeline_id = str(payload.get("pipeline_id", "workflow")).strip()
        return f"Planning with the {pipeline_id.replace('_', ' ')} workflow.".strip()
    if event_type == "step_started":
        label = str(payload.get("message", "Working on the next step.")).strip()
        return label or "Working on the next step."
    if event_type == "tool_call_started":
        why = str(payload.get("reason", "")).strip()
        suffix = f" {why}" if why else ""
        return f"Using {mcp_label} ({tool_label}).{suffix}".strip()
    if event_type == "validation_passed":
        return str(payload.get("message", "Validated the result.")).strip() or "Validated the result."
    if event_type == "validation_failed":
        return str(payload.get("message", "Validation failed; trying a fallback path.")).strip() or "Validation failed; trying a fallback path."
    if event_type == "fallback_started":
        return str(payload.get("message", "Trying a fallback route.")).strip() or "Trying a fallback route."
    if event_type == "task_blocked":
        return str(payload.get("message", "Blocked on required input.")).strip() or "Blocked on required input."
    if event_type == "task_completed":
        return str(payload.get("message", "Done.")).strip() or "Done."
    if event_type == "task_cancelled":
        return str(payload.get("message", "Stopped. Ready for the next task.")).strip() or "Stopped. Ready for the next task."
    if stage:
        return stage
    return str(payload.get("message", "Working...")).strip() or "Working..."


def validate_tool_result(
    *,
    mcp_id: str,
    tool_id: str,
    result: dict[str, object],
    intent: TaskIntent,
) -> ValidationResult:
    if not isinstance(result, dict):
        return {
            "passed": False,
            "validator": "result_type_validator",
            "detail": "Tool result is not a structured payload.",
        }

    explicit_ok = result.get("ok")
    if isinstance(explicit_ok, bool):
        return {
            "passed": explicit_ok,
            "validator": "explicit_ok_validator",
            "detail": "Tool returned ok=true." if explicit_ok else "Tool returned ok=false.",
        }

    error_value = str(result.get("error", "")).strip()
    if error_value:
        return {
            "passed": False,
            "validator": "error_field_validator",
            "detail": error_value,
        }

    if mcp_id == "git_ops" and any(token in tool_id for token in ("commit", "push", "diff", "branch", "status")):
        changed = any(key in result for key in ("stdout", "summary", "diff", "commit_sha", "branch", "status"))
        return {
            "passed": changed,
            "validator": "git_artifact_validator",
            "detail": "Git operation produced a visible artifact." if changed else "Git operation returned no visible artifact.",
        }

    if mcp_id == "google_services":
        present = any(key in result for key in ("file_id", "files", "messages", "events", "content", "text"))
        return {
            "passed": present,
            "validator": "google_artifact_validator",
            "detail": "Google result contains a target artifact." if present else "Google result did not contain the expected artifact.",
        }

    if mcp_id == "home_assistant":
        present = any(key in result for key in ("entity_id", "state", "states", "service", "result"))
        return {
            "passed": present,
            "validator": "home_assistant_validator",
            "detail": "Home Assistant result returned state data." if present else "Home Assistant result did not confirm the target state.",
        }

    if intent.get("artifact_type") == "binary_file":
        present = any(key in result for key in ("content_base64", "bytes", "download_url", "mime_type", "path"))
        return {
            "passed": present,
            "validator": "binary_artifact_validator",
            "detail": "Binary artifact metadata is present." if present else "Binary artifact metadata is missing.",
        }

    present = any(
        key in result and result.get(key) not in (None, "", [], {})
        for key in ("text", "content", "items", "result", "data", "path", "url", "stdout")
    )
    return {
        "passed": present,
        "validator": "generic_nonempty_validator",
        "detail": "Tool returned a non-empty artifact." if present else "Tool returned an empty artifact.",
    }


def execution_event(
    event_type: str,
    *,
    message: str = "",
    stage: str = "",
    detail: str = "",
    pipeline_id: str = "",
    categories: list[str] | None = None,
    mcp_id: str = "",
    mcp_label: str = "",
    tool_id: str = "",
    tool_label: str = "",
    step_index: int = 0,
    call_id: str = "",
    reason: str = "",
) -> ExecutionEvent:
    payload: ExecutionEvent = {
        "event_type": event_type,
        "message": message,
    }
    if stage:
        payload["stage"] = stage
    if detail:
        payload["detail"] = detail
    if pipeline_id:
        payload["pipeline_id"] = pipeline_id
    if categories:
        payload["categories"] = list(categories)
    if mcp_id:
        payload["mcp_id"] = mcp_id
    if mcp_label:
        payload["mcp_label"] = mcp_label
    if tool_id:
        payload["tool_id"] = tool_id
    if tool_label:
        payload["tool_label"] = tool_label
    if step_index > 0:
        payload["step_index"] = step_index
    if call_id:
        payload["call_id"] = call_id
    if reason:
        payload["reason"] = reason
    return payload


def _select_pipeline_id(categories: list[str]) -> str:
    if "repo_modification" in categories:
        return "repo_modify_diff_finalize_pipeline"
    if "external_file_retrieval" in categories:
        return "fetch_validate_apply_verify_pipeline"
    if "home_automation_change" in categories:
        return "resolve_target_apply_confirm_pipeline"
    if "communication_task" in categories:
        return "fetch_transform_publish_verify_pipeline"
    return "inspect_route_execute_verify_pipeline"


def _build_completion_criteria(categories: list[str]) -> list[str]:
    criteria = ["the final user objective is completed"]
    if "repo_modification" in categories:
        criteria.extend(["the repo diff reflects the requested change", "any requested repo artifact exists after execution"])
    if "external_file_retrieval" in categories:
        criteria.extend(["the requested file or asset was fetched", "the fetched artifact passed validation"])
    if "home_automation_change" in categories:
        criteria.append("the remote state reflects the requested change")
    if "communication_task" in categories:
        criteria.append("the outbound artifact was created or sent successfully")
    return criteria


def _build_validation_focus(categories: list[str]) -> list[str]:
    focus = ["artifact existence", "non-empty result"]
    if "repo_modification" in categories:
        focus.append("repo artifact visibility")
    if "external_file_retrieval" in categories:
        focus.append("artifact type sanity")
    if "home_automation_change" in categories:
        focus.append("remote state confirmation")
    return focus
