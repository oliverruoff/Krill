"""Home Assistant MCP plugin for entity control and automation management."""

from __future__ import annotations

import asyncio
import difflib
import json
import re
import tempfile
from pathlib import Path
from typing import Mapping
from urllib import error, parse, request

from .base import MCPPlugin, McpConfigField, McpToolSpec


HOME_ASSISTANT_MCP_ID = "home_assistant"
BASE_URL_PARAM = "base_url"
TOKEN_PARAM = "long_lived_token"
CONFIG_ROOT_PATH_PARAM = "config_root_path"
AUTOMATIONS_FILE_PATH_PARAM = "automations_file_path"
PREFER_FILE_MODE_PARAM = "prefer_file_mode"
DEFAULT_BASE_URL = "http://homeassistant.local:8123"


class HomeAssistantMCP(MCPPlugin):
    mcp_id = HOME_ASSISTANT_MCP_ID
    display_name = "Home Assistant"
    description = "Read entities, check states, call services, and manage automations via Home Assistant API."
    config_fields = [
        McpConfigField(
            id=BASE_URL_PARAM,
            label="Base URL",
            type="text",
            required=False,
            placeholder=DEFAULT_BASE_URL,
            description="Home Assistant base URL. Defaults to http://homeassistant.local:8123.",
        ),
        McpConfigField(
            id=TOKEN_PARAM,
            label="Long-Lived Access Token",
            type="password",
            required=True,
            placeholder="eyJ0eXAiOi...",
            description="Create in Home Assistant user profile under Long-Lived Access Tokens.",
        ),
        McpConfigField(
            id=CONFIG_ROOT_PATH_PARAM,
            label="Config Root Path",
            type="text",
            required=False,
            placeholder="/config",
            description="Optional Home Assistant config root for direct YAML file access.",
        ),
        McpConfigField(
            id=AUTOMATIONS_FILE_PATH_PARAM,
            label="Automations File Path",
            type="text",
            required=False,
            placeholder="/config/automations.yaml",
            description="Optional explicit automations YAML file path. Overrides Config Root Path default.",
        ),
        McpConfigField(
            id=PREFER_FILE_MODE_PARAM,
            label="Prefer YAML File Mode",
            type="checkbox",
            required=False,
            description="When enabled, automation read/write tools prioritize local YAML files and fall back to API if unavailable.",
        ),
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="list_entities",
                label="List Entities",
                description="Lists Home Assistant entities, optionally filtered by domain.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
                        "include_attributes": {"type": "boolean"},
                    },
                },
            ),
            McpToolSpec(
                id="get_entity_state",
                label="Get Entity State",
                description="Fetches current state for one entity.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["entity_id"],
                },
            ),
            McpToolSpec(
                id="trigger_entity",
                label="Trigger Entity",
                description="Triggers an entity action (toggle, turn_on, turn_off, or automation trigger) and verifies resulting state.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                        "action": {"type": "string", "enum": ["toggle", "turn_on", "turn_off", "trigger"]},
                        "skip_condition": {"type": "boolean"},
                    },
                    "required": ["entity_id"],
                },
            ),
            McpToolSpec(
                id="call_service",
                label="Call Service",
                description="Calls any Home Assistant service with optional service_data and target, then verifies target entity state when possible.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "minLength": 1},
                        "service": {"type": "string", "minLength": 1},
                        "service_data": {"type": "object"},
                        "target": {"type": "object"},
                        "return_response": {"type": "boolean"},
                    },
                    "required": ["domain", "service"],
                },
            ),
            McpToolSpec(
                id="get_todo_items",
                label="Get Todo Items",
                description="Reads items from a Home Assistant todo list entity.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                        "status": {
                            "oneOf": [
                                {"type": "string", "enum": ["needs_action", "completed"]},
                                {
                                    "type": "array",
                                    "items": {"type": "string", "enum": ["needs_action", "completed"]},
                                    "minItems": 1,
                                },
                            ]
                        },
                    },
                    "required": ["entity_id"],
                },
            ),
            McpToolSpec(
                id="add_todo_item",
                label="Add Todo Item",
                description="Adds one item to a Home Assistant todo list and verifies the list afterward.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                        "item": {"type": "string", "minLength": 1},
                        "due_date": {"type": "string"},
                        "due_datetime": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["entity_id", "item"],
                },
            ),
            McpToolSpec(
                id="update_todo_item",
                label="Update Todo Item",
                description="Updates one item in a Home Assistant todo list and verifies the list afterward.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                        "item": {"type": "string", "minLength": 1},
                        "rename": {"type": "string"},
                        "status": {"type": "string", "enum": ["needs_action", "completed"]},
                        "due_date": {"type": "string"},
                        "due_datetime": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["entity_id", "item"],
                },
            ),
            McpToolSpec(
                id="remove_todo_item",
                label="Remove Todo Item",
                description="Removes one item from a Home Assistant todo list and verifies the list afterward.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                        "item": {"type": "string", "minLength": 1},
                    },
                    "required": ["entity_id", "item"],
                },
            ),
            McpToolSpec(
                id="remove_completed_todo_items",
                label="Remove Completed Todo Items",
                description="Removes all completed items from a Home Assistant todo list and verifies the list afterward.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["entity_id"],
                },
            ),
            McpToolSpec(
                id="list_automations",
                label="List Automations",
                description="Lists automation entities currently in Home Assistant.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_attributes": {"type": "boolean"},
                        "include_disabled": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                    },
                },
            ),
            McpToolSpec(
                id="find_automations",
                label="Find Automations",
                description="Finds likely matching automations by name/id query and returns ranked candidates.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "include_attributes": {"type": "boolean"},
                        "include_config": {"type": "boolean"},
                    },
                    "required": ["query"],
                },
            ),
            McpToolSpec(
                id="get_automation",
                label="Get Automation",
                description="Fetches one automation by automation_id or automation entity_id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "automation_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["automation_id"],
                },
            ),
            McpToolSpec(
                id="create_or_update_automation",
                label="Create/Update Automation",
                description="Creates or updates automation config by automation_id and verifies resulting automation state.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "automation_id": {"type": "string", "minLength": 1},
                        "automation": {"type": "object"},
                        "reload": {"type": "boolean"},
                    },
                    "required": ["automation_id", "automation"],
                },
            ),
            McpToolSpec(
                id="list_automation_yaml_files",
                label="List Automation YAML Files",
                description="Lists configured Home Assistant automation YAML files and whether they are readable.",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
            ),
            McpToolSpec(
                id="read_automation_yaml",
                label="Read Automation YAML",
                description="Finds and reads one automation YAML block from file mode (preferred) or API config fallback.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "automation_id": {"type": "string", "minLength": 1},
                        "name_query": {"type": "string", "minLength": 1},
                        "prefer_file_mode": {"type": "boolean"},
                        "max_candidates": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                },
            ),
            McpToolSpec(
                id="update_automation_yaml",
                label="Update Automation YAML",
                description="Updates an existing automation YAML block in file mode or API fallback and verifies state.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "automation_id": {"type": "string", "minLength": 1},
                        "name_query": {"type": "string", "minLength": 1},
                        "yaml": {"type": "string", "minLength": 1},
                        "prefer_file_mode": {"type": "boolean"},
                        "reload": {"type": "boolean"},
                        "create_if_missing": {"type": "boolean"},
                        "backup": {"type": "boolean"},
                    },
                    "required": ["yaml"],
                },
            ),
            McpToolSpec(
                id="create_automation_yaml",
                label="Create Automation YAML",
                description="Creates a new automation from YAML in file mode or API fallback and verifies state.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "automation_id": {"type": "string", "minLength": 1},
                        "yaml": {"type": "string", "minLength": 1},
                        "prefer_file_mode": {"type": "boolean"},
                        "target_file": {"type": "string"},
                        "reload": {"type": "boolean"},
                        "backup": {"type": "boolean"},
                    },
                    "required": ["yaml"],
                },
            ),
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id in {
            "list_entities",
            "get_entity_state",
            "get_todo_items",
            "list_automations",
            "find_automations",
            "get_automation",
            "list_automation_yaml_files",
            "read_automation_yaml",
        }:
            return ""
        return (
            "Home Assistant safety reminder:\n"
            "- Execute only actions explicitly requested by the user in this chat.\n"
            "- Confirm exact entity IDs and service intent before making device or automation changes.\n"
            "- For automation writes, if multiple matches are plausible, return ambiguity details instead of guessing.\n"
            "- If request is ambiguous or could affect security/safety devices, ask for clarification.\n"
            "- Return JSON only with this shape: {\"arguments\":{...}}"
        )

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        token = _required_token(params)
        if not token:
            return False, "Home Assistant long-lived token is required."

        base_url = _base_url(params)
        try:
            payload = await asyncio.to_thread(_ha_request_json, "GET", f"{base_url}/api/", token, None)
        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            if exc.code in {401, 403}:
                return False, "Home Assistant rejected the token (unauthorized)."
            return False, f"Home Assistant verification failed ({exc.code}): {detail}"
        except error.URLError as exc:
            reason = _url_error_reason(exc)
            return False, f"Network error while contacting Home Assistant at {base_url}: {reason}"
        except Exception:
            return False, "Unexpected error while verifying Home Assistant connection."

        message = payload.get("message") if isinstance(payload, dict) else ""
        if isinstance(message, str) and message.strip():
            return True, f"Home Assistant connected: {message.strip()}"
        return True, f"Home Assistant connected at {base_url}."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        token = _required_token(params)
        if not token:
            raise RuntimeError("Home Assistant long-lived token is missing.")
        base_url = _base_url(params)

        try:
            if tool_id == "list_entities":
                return await asyncio.to_thread(_list_entities, base_url, token, arguments)

            if tool_id == "get_entity_state":
                return await asyncio.to_thread(_get_entity_state, base_url, token, arguments)

            if tool_id == "trigger_entity":
                return await asyncio.to_thread(_trigger_entity, base_url, token, arguments)

            if tool_id == "call_service":
                return await asyncio.to_thread(_call_service, base_url, token, arguments)

            if tool_id == "get_todo_items":
                return await asyncio.to_thread(_get_todo_items, base_url, token, arguments)

            if tool_id == "add_todo_item":
                return await asyncio.to_thread(_add_todo_item, base_url, token, arguments)

            if tool_id == "update_todo_item":
                return await asyncio.to_thread(_update_todo_item, base_url, token, arguments)

            if tool_id == "remove_todo_item":
                return await asyncio.to_thread(_remove_todo_item, base_url, token, arguments)

            if tool_id == "remove_completed_todo_items":
                return await asyncio.to_thread(_remove_completed_todo_items, base_url, token, arguments)

            if tool_id == "list_automations":
                return await asyncio.to_thread(_list_automations, base_url, token, arguments)

            if tool_id == "find_automations":
                return await asyncio.to_thread(_find_automations, base_url, token, arguments)

            if tool_id == "get_automation":
                return await asyncio.to_thread(_get_automation, base_url, token, arguments)

            if tool_id == "create_or_update_automation":
                return await asyncio.to_thread(_create_or_update_automation, base_url, token, arguments)

            if tool_id == "list_automation_yaml_files":
                return await asyncio.to_thread(_list_automation_yaml_files, params)

            if tool_id == "read_automation_yaml":
                return await asyncio.to_thread(_read_automation_yaml, base_url, token, arguments, params)

            if tool_id == "update_automation_yaml":
                return await asyncio.to_thread(_update_automation_yaml, base_url, token, arguments, params)

            if tool_id == "create_automation_yaml":
                return await asyncio.to_thread(_create_automation_yaml, base_url, token, arguments, params)
        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            raise RuntimeError(f"Home Assistant API request failed ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            reason = _url_error_reason(exc)
            raise RuntimeError(f"Network error while contacting Home Assistant: {reason}") from exc

        raise RuntimeError(f"Unsupported Home Assistant tool: {tool_id}")


def _base_url(params: dict[str, str]) -> str:
    raw = str(params.get(BASE_URL_PARAM, "")).strip() or DEFAULT_BASE_URL
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "http://" + raw
    return raw.rstrip("/")


def _required_token(params: dict[str, str]) -> str:
    return str(params.get(TOKEN_PARAM, "")).strip()


def _ha_request_json(
    method: str,
    url: str,
    token: str,
    payload: Mapping[str, object] | None,
) -> dict[str, object] | list[object]:
    body: bytes | None = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return {}
        loaded = json.loads(raw)
        if isinstance(loaded, dict) or isinstance(loaded, list):
            return loaded
        return {"value": loaded}


def _list_entities(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    domain = _optional_str(arguments, "domain", "")
    include_attributes = bool(arguments.get("include_attributes", False))
    limit = _optional_int(arguments, "limit", 500, 1, 2000)
    payload = _ha_request_json("GET", f"{base_url}/api/states", token, None)

    states = payload if isinstance(payload, list) else []
    entities: list[dict[str, object]] = []
    for raw in states:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("entity_id", "")).strip()
        if not entity_id:
            continue
        entity_domain = entity_id.split(".", 1)[0]
        if domain and entity_domain != domain:
            continue

        item: dict[str, object] = {
            "entity_id": entity_id,
            "domain": entity_domain,
            "state": str(raw.get("state", "")),
            "last_changed": str(raw.get("last_changed", "")),
            "friendly_name": _friendly_name(raw),
        }
        if include_attributes:
            attrs = raw.get("attributes")
            item["attributes"] = attrs if isinstance(attrs, dict) else {}
        entities.append(item)
        if len(entities) >= limit:
            break

    return {
        "count": len(entities),
        "domain_filter": domain,
        "entities": entities,
    }


def _get_entity_state(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    encoded_id = parse.quote(entity_id, safe="")
    payload = _ha_request_json("GET", f"{base_url}/api/states/{encoded_id}", token, None)
    if not isinstance(payload, dict):
        raise RuntimeError("Home Assistant returned invalid state payload.")
    return {
        "entity_id": entity_id,
        "state": str(payload.get("state", "")),
        "last_changed": str(payload.get("last_changed", "")),
        "last_updated": str(payload.get("last_updated", "")),
        "attributes": payload.get("attributes", {}),
    }


def _trigger_entity(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    domain = entity_id.split(".", 1)[0]
    action = _optional_str(arguments, "action", "")
    skip_condition = bool(arguments.get("skip_condition", False))

    if not action:
        action = "trigger" if domain == "automation" else "toggle"

    if action == "trigger":
        if domain == "automation":
            payload: dict[str, object] = {
                "entity_id": entity_id,
                "skip_condition": skip_condition,
            }
            result = _ha_request_json("POST", f"{base_url}/api/services/automation/trigger", token, payload)
            verification = _verify_entity_states(base_url, token, [entity_id])
            return {
                "entity_id": entity_id,
                "action": action,
                "result": result,
                "verification": verification,
            }
        if domain == "script":
            payload: dict[str, object] = {"entity_id": entity_id}
            result = _ha_request_json("POST", f"{base_url}/api/services/script/turn_on", token, payload)
            verification = _verify_entity_states(base_url, token, [entity_id])
            return {
                "entity_id": entity_id,
                "action": action,
                "result": result,
                "verification": verification,
            }
        raise RuntimeError("Action 'trigger' is supported for automation.* and script.* entities.")

    if action not in {"toggle", "turn_on", "turn_off"}:
        raise RuntimeError("Invalid action. Use one of: toggle, turn_on, turn_off, trigger.")

    payload: dict[str, object] = {"entity_id": entity_id}
    result = _ha_request_json("POST", f"{base_url}/api/services/homeassistant/{action}", token, payload)
    expected_state = "on" if action == "turn_on" else ("off" if action == "turn_off" else "")
    expected_by_entity = {entity_id: expected_state} if expected_state else {}
    verification = _verify_entity_states(base_url, token, [entity_id], expected_states=expected_by_entity)
    return {
        "entity_id": entity_id,
        "action": action,
        "result": result,
        "verification": verification,
    }


def _call_service(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    domain = _required_str(arguments, "domain")
    service = _required_str(arguments, "service")
    return_response = bool(arguments.get("return_response", False))
    service_data = arguments.get("service_data")
    target = arguments.get("target")

    payload: dict[str, object] = {}
    if isinstance(service_data, dict):
        payload.update(service_data)
    if isinstance(target, dict):
        for key in ("entity_id", "device_id", "area_id"):
            value = target.get(key)
            if value is None:
                continue
            if key not in payload:
                payload[key] = value

    result = _ha_service_call(base_url, token, domain, service, payload, return_response=return_response)
    entity_ids = _extract_entity_ids_from_payload(payload)
    expected_state = "on" if service == "turn_on" else ("off" if service == "turn_off" else "")
    expected_by_entity = {entity_id: expected_state for entity_id in entity_ids} if expected_state else {}
    verification = _verify_entity_states(base_url, token, entity_ids, expected_states=expected_by_entity)
    return {
        "domain": domain,
        "service": service,
        "return_response": return_response,
        "result": result,
        "verification": verification,
    }


def _get_todo_items(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    payload: dict[str, object] = {"entity_id": entity_id}
    status = _normalize_todo_status(arguments.get("status"))
    if status:
        payload["status"] = status

    result = _ha_service_call(base_url, token, "todo", "get_items", payload, return_response=True)
    items = _extract_todo_items_from_service_response(result, entity_id)
    return {
        "entity_id": entity_id,
        "status_filter": status,
        "count": len(items),
        "items": items,
        "result": result,
    }


def _add_todo_item(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    item = _required_str(arguments, "item")
    payload: dict[str, object] = {"entity_id": entity_id, "item": item}
    _assign_optional_string(payload, arguments, "due_date")
    _assign_optional_string(payload, arguments, "due_datetime")
    _assign_optional_string(payload, arguments, "description")
    _validate_todo_due_fields(payload)

    result = _ha_service_call(base_url, token, "todo", "add_item", payload)
    verification = _verify_todo_entity(
        base_url,
        token,
        entity_id,
        expected_item=item,
        should_exist=True,
        operation_label="add_item",
    )
    return {
        "entity_id": entity_id,
        "item": item,
        "result": result,
        "verification": verification,
    }


def _update_todo_item(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    item = _required_str(arguments, "item")
    payload: dict[str, object] = {"entity_id": entity_id, "item": item}
    _assign_optional_string(payload, arguments, "rename")
    _assign_optional_string(payload, arguments, "status")
    _assign_optional_string(payload, arguments, "due_date")
    _assign_optional_string(payload, arguments, "due_datetime")
    _assign_optional_string(payload, arguments, "description")
    _validate_todo_due_fields(payload)
    _validate_todo_status_field(payload, "status")

    update_fields = {"rename", "status", "due_date", "due_datetime", "description"}
    if not any(field in payload for field in update_fields):
        raise RuntimeError("At least one update field is required: rename, status, due_date, due_datetime, or description.")

    result = _ha_service_call(base_url, token, "todo", "update_item", payload)
    expected_item = str(payload.get("rename", item)).strip() or item
    verification = _verify_todo_entity(
        base_url,
        token,
        entity_id,
        expected_item=expected_item,
        should_exist=True,
        operation_label="update_item",
    )
    return {
        "entity_id": entity_id,
        "item": item,
        "result": result,
        "verification": verification,
    }


def _remove_todo_item(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    item = _required_str(arguments, "item")
    payload: dict[str, object] = {"entity_id": entity_id, "item": item}
    result = _ha_service_call(base_url, token, "todo", "remove_item", payload)
    verification = _verify_todo_entity(
        base_url,
        token,
        entity_id,
        expected_item=item,
        should_exist=False,
        operation_label="remove_item",
    )
    return {
        "entity_id": entity_id,
        "item": item,
        "result": result,
        "verification": verification,
    }


def _remove_completed_todo_items(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    payload: dict[str, object] = {"entity_id": entity_id}
    result = _ha_service_call(base_url, token, "todo", "remove_completed_items", payload)
    verification = _verify_todo_no_completed_items(base_url, token, entity_id)
    return {
        "entity_id": entity_id,
        "result": result,
        "verification": verification,
    }


def _ha_service_call(
    base_url: str,
    token: str,
    domain: str,
    service: str,
    payload: dict[str, object],
    *,
    return_response: bool = False,
) -> dict[str, object] | list[object]:
    endpoint = f"{base_url}/api/services/{parse.quote(domain, safe='')}/{parse.quote(service, safe='')}"
    if return_response:
        endpoint += "?return_response"
    return _ha_request_json("POST", endpoint, token, payload)


def _extract_todo_items_from_service_response(result: dict[str, object] | list[object], entity_id: str) -> list[dict[str, object]]:
    if not isinstance(result, dict):
        return []
    service_response = result.get("service_response")
    if not isinstance(service_response, dict):
        return []

    entity_payload = service_response.get(entity_id)
    if not isinstance(entity_payload, dict):
        return []

    maybe_items = entity_payload.get("items")
    if not isinstance(maybe_items, list):
        return []

    items: list[dict[str, object]] = []
    for raw_item in maybe_items:
        if isinstance(raw_item, dict):
            items.append(raw_item)
    return items


def _extract_entity_ids_from_payload(payload: Mapping[str, object]) -> list[str]:
    raw_value = payload.get("entity_id")
    candidates: list[str] = []
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        if cleaned:
            candidates.append(cleaned)
    elif isinstance(raw_value, list):
        for item in raw_value:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for entity_id in candidates:
        if entity_id in seen:
            continue
        seen.add(entity_id)
        deduped.append(entity_id)
    return deduped


def _verify_entity_states(
    base_url: str,
    token: str,
    entity_ids: list[str],
    *,
    expected_states: dict[str, str] | None = None,
) -> dict[str, object]:
    if not entity_ids:
        return {
            "status": "skipped",
            "detail": "No explicit entity_id target was provided, so post-action state verification was skipped.",
            "entities": [],
        }

    checks: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    expected_states = expected_states or {}

    for entity_id in entity_ids:
        encoded_id = parse.quote(entity_id, safe="")
        try:
            payload = _ha_request_json("GET", f"{base_url}/api/states/{encoded_id}", token, None)
            if not isinstance(payload, dict):
                raise RuntimeError("Invalid state payload.")
            actual_state = str(payload.get("state", ""))
            expected_state = str(expected_states.get(entity_id, "")).strip()
            matches_expected = True
            if expected_state:
                matches_expected = actual_state.lower() == expected_state.lower()
            checks.append(
                {
                    "entity_id": entity_id,
                    "state": actual_state,
                    "last_changed": str(payload.get("last_changed", "")),
                    "last_updated": str(payload.get("last_updated", "")),
                    "friendly_name": _friendly_name(payload),
                    "expected_state": expected_state,
                    "matches_expected_state": matches_expected,
                    "attributes": payload.get("attributes", {}),
                }
            )
        except error.HTTPError as exc:
            failures.append(
                {
                    "entity_id": entity_id,
                    "detail": f"Home Assistant API request failed ({exc.code}): {_read_http_error(exc)}",
                }
            )
        except error.URLError as exc:
            failures.append(
                {
                    "entity_id": entity_id,
                    "detail": f"Network error while contacting Home Assistant: {_url_error_reason(exc)}",
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "entity_id": entity_id,
                    "detail": str(exc),
                }
            )

    has_expectation_mismatch = any(
        check.get("expected_state") and not bool(check.get("matches_expected_state"))
        for check in checks
    )
    if checks and not failures and not has_expectation_mismatch:
        return {
            "status": "verified",
            "detail": "Post-action entity state verification succeeded.",
            "entities": checks,
            "failures": failures,
        }
    if checks:
        return {
            "status": "partial",
            "detail": "Action executed, but some post-action entity checks were incomplete or mismatched expected states.",
            "entities": checks,
            "failures": failures,
        }
    return {
        "status": "failed",
        "detail": "Action executed, but post-action entity verification could not read target states.",
        "entities": checks,
        "failures": failures,
    }


def _fetch_todo_items(base_url: str, token: str, entity_id: str) -> list[dict[str, object]]:
    payload: dict[str, object] = {"entity_id": entity_id}
    result = _ha_service_call(base_url, token, "todo", "get_items", payload, return_response=True)
    return _extract_todo_items_from_service_response(result, entity_id)


def _todo_item_text(item: dict[str, object]) -> str:
    for key in ("summary", "item", "name", "title"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _verify_todo_entity(
    base_url: str,
    token: str,
    entity_id: str,
    *,
    expected_item: str,
    should_exist: bool,
    operation_label: str,
) -> dict[str, object]:
    normalized_expected = expected_item.strip().lower()
    try:
        items = _fetch_todo_items(base_url, token, entity_id)
    except Exception as exc:
        return {
            "status": "failed",
            "detail": f"{operation_label}: action executed, but todo verification failed: {exc}",
            "entity_id": entity_id,
            "expected_item": expected_item,
            "item_present": None,
            "items": [],
        }

    present = any(_todo_item_text(item).lower() == normalized_expected for item in items if isinstance(item, dict))
    verified = present if should_exist else (not present)
    detail = (
        f"{operation_label}: verification succeeded."
        if verified
        else f"{operation_label}: action executed, but verification did not observe expected todo list outcome."
    )
    return {
        "status": "verified" if verified else "partial",
        "detail": detail,
        "entity_id": entity_id,
        "expected_item": expected_item,
        "item_present": present,
        "items": items,
    }


def _verify_todo_no_completed_items(base_url: str, token: str, entity_id: str) -> dict[str, object]:
    try:
        items = _fetch_todo_items(base_url, token, entity_id)
    except Exception as exc:
        return {
            "status": "failed",
            "detail": f"remove_completed_items: action executed, but todo verification failed: {exc}",
            "entity_id": entity_id,
            "remaining_completed_count": None,
            "items": [],
        }

    remaining_completed = [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("status", "")).strip().lower() == "completed"
    ]
    verified = len(remaining_completed) == 0
    return {
        "status": "verified" if verified else "partial",
        "detail": (
            "remove_completed_items: verification succeeded."
            if verified
            else "remove_completed_items: action executed, but completed items still remain."
        ),
        "entity_id": entity_id,
        "remaining_completed_count": len(remaining_completed),
        "items": items,
    }


def _normalize_todo_status(value: object) -> list[str]:
    if value is None:
        return []
    allowed = {"needs_action", "completed"}
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise RuntimeError("Invalid todo status. Use one of: needs_action, completed.")
        return [normalized]
    if isinstance(value, list):
        normalized_statuses: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise RuntimeError("Invalid todo status list. Values must be strings.")
            normalized = item.strip().lower()
            if normalized not in allowed:
                raise RuntimeError("Invalid todo status. Use one of: needs_action, completed.")
            if normalized not in normalized_statuses:
                normalized_statuses.append(normalized)
        return normalized_statuses
    raise RuntimeError("Invalid todo status. Use a string or list of strings.")


def _assign_optional_string(payload: dict[str, object], arguments: dict[str, object], key: str) -> None:
    value = arguments.get(key)
    if isinstance(value, str) and value.strip():
        payload[key] = value.strip()


def _validate_todo_due_fields(payload: dict[str, object]) -> None:
    if "due_date" in payload and "due_datetime" in payload:
        raise RuntimeError("Only one of 'due_date' or 'due_datetime' may be provided.")


def _validate_todo_status_field(payload: dict[str, object], key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str):
        return
    normalized = value.strip().lower()
    if normalized not in {"needs_action", "completed"}:
        raise RuntimeError("Invalid todo status. Use one of: needs_action, completed.")
    payload[key] = normalized


def _list_automations(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    include_attributes = bool(arguments.get("include_attributes", False))
    include_disabled = bool(arguments.get("include_disabled", True))
    limit = _optional_int(arguments, "limit", 500, 1, 1000)

    payload = _ha_request_json("GET", f"{base_url}/api/states", token, None)
    states = payload if isinstance(payload, list) else []
    automations: list[dict[str, object]] = []

    for raw in states:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("entity_id", "")).strip()
        if not entity_id.startswith("automation."):
            continue
        state = str(raw.get("state", "")).strip()
        if not include_disabled and state.lower() in {"off", "unavailable", "unknown"}:
            continue
        item: dict[str, object] = {
            "entity_id": entity_id,
            "automation_id": entity_id.split(".", 1)[1],
            "state": state,
            "last_changed": str(raw.get("last_changed", "")),
            "friendly_name": _friendly_name(raw),
        }
        if include_attributes:
            attrs = raw.get("attributes")
            item["attributes"] = attrs if isinstance(attrs, dict) else {}
        automations.append(item)
        if len(automations) >= limit:
            break

    return {
        "count": len(automations),
        "automations": automations,
    }


def _find_automations(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    query = _required_str(arguments, "query")
    include_attributes = bool(arguments.get("include_attributes", False))
    include_config = bool(arguments.get("include_config", False))
    limit = _optional_int(arguments, "limit", 10, 1, 50)

    listed = _list_automations(
        base_url,
        token,
        {
            "include_attributes": True,
            "include_disabled": True,
            "limit": 1000,
        },
    )
    raw_automations = listed.get("automations", [])
    if not isinstance(raw_automations, list):
        raw_automations = []

    scored: list[dict[str, object]] = []
    for item in raw_automations:
        if not isinstance(item, dict):
            continue
        candidate = _automation_search_candidate(item)
        score = _automation_query_score(query, candidate)
        if score <= 0:
            continue

        payload: dict[str, object] = {
            "entity_id": candidate["entity_id"],
            "automation_id": candidate["automation_id"],
            "friendly_name": candidate["friendly_name"],
            "alias": candidate["alias"],
            "state": candidate["state"],
            "score": score,
        }
        if include_attributes:
            payload["attributes"] = item.get("attributes", {})
        if include_config:
            try:
                conf = _ha_request_json(
                    "GET",
                    f"{base_url}/api/config/automation/config/{parse.quote(candidate['automation_id'], safe='')}",
                    token,
                    None,
                )
                payload["config"] = conf if isinstance(conf, dict) else {}
            except error.HTTPError as exc:
                if exc.code not in {400, 404, 405}:
                    raise
                payload["config"] = {}
            except Exception:
                payload["config"] = {}

        scored.append(payload)

    scored.sort(key=lambda entry: (_score_value(entry.get("score", 0.0)), str(entry.get("friendly_name", "")).lower()), reverse=True)
    top = scored[:limit]
    ambiguous = len(top) > 1 and abs(_score_value(top[0].get("score", 0.0)) - _score_value(top[1].get("score", 0.0))) < 0.08
    return {
        "query": query,
        "count": len(top),
        "ambiguous": ambiguous,
        "matches": top,
    }


def _list_automation_yaml_files(params: dict[str, str]) -> dict[str, object]:
    paths = _configured_automation_file_paths(params)
    files: list[dict[str, object]] = []
    for path in paths:
        files.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "is_file": path.is_file(),
                "readable": path.is_file(),
            }
        )
    return {
        "count": len(files),
        "files": files,
    }


def _read_automation_yaml(
    base_url: str,
    token: str,
    arguments: dict[str, object],
    params: dict[str, str],
) -> dict[str, object]:
    prefer_file_mode = _effective_prefer_file_mode(arguments, params)
    max_candidates = _optional_int(arguments, "max_candidates", 5, 1, 20)
    selected_id = _optional_str(arguments, "automation_id", "")
    name_query = _optional_str(arguments, "name_query", "")

    if prefer_file_mode:
        file_result = _read_automation_yaml_from_files(selected_id, name_query, max_candidates, params)
        if bool(file_result.get("ok", False)):
            return file_result

    return _read_automation_yaml_from_api(base_url, token, selected_id, name_query, max_candidates)


def _update_automation_yaml(
    base_url: str,
    token: str,
    arguments: dict[str, object],
    params: dict[str, str],
) -> dict[str, object]:
    yaml_text = _required_str(arguments, "yaml")
    prefer_file_mode = _effective_prefer_file_mode(arguments, params)
    reload_automations = bool(arguments.get("reload", True))
    create_if_missing = bool(arguments.get("create_if_missing", False))
    backup = bool(arguments.get("backup", True))
    selected_id = _optional_str(arguments, "automation_id", "")
    name_query = _optional_str(arguments, "name_query", "")

    automation_payload = _parse_automation_yaml_block(yaml_text)
    normalized_yaml = _normalize_mapping_yaml_text(yaml_text)

    if prefer_file_mode:
        file_result = _update_automation_yaml_in_files(
            base_url,
            token,
            selected_id,
            name_query,
            normalized_yaml,
            reload_automations,
            create_if_missing,
            backup,
            params,
        )
        if bool(file_result.get("ok", False)):
            return file_result

    return _update_automation_via_api(
        base_url,
        token,
        selected_id,
        name_query,
        automation_payload,
        reload_automations,
        create_if_missing,
    )


def _create_automation_yaml(
    base_url: str,
    token: str,
    arguments: dict[str, object],
    params: dict[str, str],
) -> dict[str, object]:
    yaml_text = _required_str(arguments, "yaml")
    prefer_file_mode = _effective_prefer_file_mode(arguments, params)
    reload_automations = bool(arguments.get("reload", True))
    backup = bool(arguments.get("backup", True))
    selected_id = _optional_str(arguments, "automation_id", "")
    target_file = _optional_str(arguments, "target_file", "")

    automation_payload = _parse_automation_yaml_block(yaml_text)
    if selected_id:
        automation_payload["id"] = _normalize_automation_entity_id(selected_id).split(".", 1)[1]
    normalized_yaml = _dump_yaml_text(automation_payload)

    if prefer_file_mode:
        file_result = _create_automation_yaml_in_files(
            base_url,
            token,
            normalized_yaml,
            reload_automations,
            backup,
            params,
            target_file,
        )
        if bool(file_result.get("ok", False)):
            return file_result

    automation_id = str(automation_payload.get("id", "")).strip()
    if not automation_id:
        raise RuntimeError("Automation YAML must include a non-empty 'id' for API fallback mode.")
    return _create_or_update_automation(
        base_url,
        token,
        {
            "automation_id": automation_id,
            "automation": automation_payload,
            "reload": reload_automations,
        },
    )


def _automation_search_candidate(payload: dict[str, object]) -> dict[str, str]:
    entity_id = str(payload.get("entity_id", "")).strip()
    automation_id = entity_id.split(".", 1)[1] if entity_id.startswith("automation.") else entity_id
    attrs = payload.get("attributes")
    attrs_map = attrs if isinstance(attrs, dict) else {}
    alias = str(attrs_map.get("friendly_name", "")).strip()
    friendly_name = str(payload.get("friendly_name", "")).strip() or alias
    return {
        "entity_id": entity_id,
        "automation_id": automation_id,
        "friendly_name": friendly_name,
        "alias": alias,
        "state": str(payload.get("state", "")).strip(),
    }


def _tokenize_query(text: str) -> list[str]:
    tokens = [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]
    return tokens


def _automation_query_score(query: str, candidate: dict[str, str]) -> float:
    query_clean = query.strip().lower()
    if not query_clean:
        return 0.0

    entity_id = candidate.get("entity_id", "").lower()
    automation_id = candidate.get("automation_id", "").lower()
    friendly_name = candidate.get("friendly_name", "").lower()
    alias = candidate.get("alias", "").lower()
    combined = " ".join([entity_id, automation_id, friendly_name, alias]).strip()
    if not combined:
        return 0.0

    score = 0.0
    if query_clean == automation_id:
        score += 1.2
    if query_clean == entity_id:
        score += 1.2
    if query_clean in {friendly_name, alias}:
        score += 1.0
    if query_clean in friendly_name:
        score += 0.8
    if query_clean in alias:
        score += 0.8
    if query_clean in automation_id:
        score += 0.6
    if query_clean in entity_id:
        score += 0.4

    tokens = _tokenize_query(query_clean)
    if tokens:
        fields = [friendly_name, alias, automation_id, entity_id]
        for token in tokens:
            if any(token and token in field for field in fields):
                score += 0.12

    similarity = max(
        difflib.SequenceMatcher(None, query_clean, friendly_name).ratio(),
        difflib.SequenceMatcher(None, query_clean, alias).ratio(),
        difflib.SequenceMatcher(None, query_clean, automation_id).ratio(),
        difflib.SequenceMatcher(None, query_clean, entity_id).ratio(),
    )
    score += similarity * 0.5
    return round(score, 4)


def _score_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _effective_prefer_file_mode(arguments: dict[str, object], params: dict[str, str]) -> bool:
    if "prefer_file_mode" in arguments:
        return bool(arguments.get("prefer_file_mode", False))
    raw = str(params.get(PREFER_FILE_MODE_PARAM, "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _configured_automation_file_paths(params: dict[str, str]) -> list[Path]:
    explicit_file = str(params.get(AUTOMATIONS_FILE_PATH_PARAM, "")).strip()
    config_root = str(params.get(CONFIG_ROOT_PATH_PARAM, "")).strip()

    candidates: list[Path] = []
    if explicit_file:
        candidates.append(Path(explicit_file).expanduser())
    if config_root:
        root = Path(config_root).expanduser()
        candidates.append(root / "automations.yaml")

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        normalized = str(path.resolve() if path.exists() else path.absolute())
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _read_automation_yaml_from_files(
    automation_id: str,
    name_query: str,
    max_candidates: int,
    params: dict[str, str],
) -> dict[str, object]:
    paths = _configured_automation_file_paths(params)
    if not paths:
        return {
            "ok": False,
            "mode": "file",
            "reason": "No Home Assistant automation YAML file paths are configured.",
        }

    records = _load_automation_records_from_files(paths)
    selected = _select_automation_record(records, automation_id, name_query, max_candidates)
    if not bool(selected.get("ok", False)):
        selected["mode"] = "file"
        return selected

    record = selected.get("record")
    if not isinstance(record, dict):
        return {
            "ok": False,
            "mode": "file",
            "reason": "Resolved automation record is invalid.",
        }

    mapping_yaml = str(record.get("yaml", "")).strip()
    yaml_text = mapping_yaml + ("\n" if mapping_yaml else "")
    automation_obj: dict[str, object] = {}
    try:
        parsed = _parse_automation_yaml_block(yaml_text)
        if isinstance(parsed, dict):
            automation_obj = parsed
    except Exception:
        automation_obj = {}

    return {
        "ok": True,
        "mode": "file",
        "path": str(record.get("path", "")),
        "entity_id": str(record.get("entity_id", "")),
        "automation_id": str(record.get("automation_id", "")),
        "friendly_name": str(record.get("friendly_name", "")),
        "yaml": yaml_text,
        "automation": automation_obj,
    }


def _read_automation_yaml_from_api(
    base_url: str,
    token: str,
    automation_id: str,
    name_query: str,
    max_candidates: int,
) -> dict[str, object]:
    resolved_id = ""
    if automation_id:
        resolved_id = _normalize_automation_entity_id(automation_id).split(".", 1)[1]
    elif name_query:
        found = _find_automations(
            base_url,
            token,
            {
                "query": name_query,
                "limit": max_candidates,
                "include_attributes": False,
                "include_config": False,
            },
        )
        matches = found.get("matches", [])
        if not isinstance(matches, list) or not matches:
            return {
                "ok": False,
                "mode": "api",
                "reason": "No automation matched the provided name query.",
                "matches": [],
            }
        if len(matches) > 1 and _score_value(matches[0].get("score")) - _score_value(matches[1].get("score")) < 0.08:
            return {
                "ok": False,
                "mode": "api",
                "reason": "Multiple automations match this query. Please specify automation_id.",
                "matches": matches,
            }
        top = matches[0]
        resolved_id = str(top.get("automation_id", "")).strip()
    else:
        raise RuntimeError("Provide either 'automation_id' or 'name_query'.")

    if not resolved_id:
        raise RuntimeError("Could not resolve automation id.")

    response = _get_automation(base_url, token, {"automation_id": resolved_id})
    config = response.get("config", {})
    config_dict = config if isinstance(config, dict) else {}
    return {
        "ok": True,
        "mode": "api",
        "entity_id": response.get("entity_id", ""),
        "automation_id": response.get("automation_id", ""),
        "friendly_name": _friendly_name({"attributes": response.get("attributes", {})}),
        "yaml": _dump_yaml_text(config_dict),
        "automation": config_dict,
    }


def _update_automation_yaml_in_files(
    base_url: str,
    token: str,
    automation_id: str,
    name_query: str,
    automation_yaml: str,
    reload_automations: bool,
    create_if_missing: bool,
    backup: bool,
    params: dict[str, str],
) -> dict[str, object]:
    paths = _configured_automation_file_paths(params)
    if not paths:
        return {
            "ok": False,
            "mode": "file",
            "reason": "No Home Assistant automation YAML file paths are configured.",
        }

    records = _load_automation_records_from_files(paths)
    selected = _select_automation_record(records, automation_id, name_query, 5)

    if bool(selected.get("ok", False)):
        record = selected.get("record")
        if not isinstance(record, dict):
            raise RuntimeError("Resolved automation record is invalid.")
        target_path = Path(str(record.get("path", "")))
        target_index = int(record.get("index", -1))
        if target_index < 0:
            raise RuntimeError("Resolved automation index is invalid.")
    else:
        if not create_if_missing:
            return {
                "ok": False,
                "mode": "file",
                "reason": str(selected.get("reason", "Automation not found in YAML files.")),
                "matches": selected.get("matches", []),
            }
        target_path = paths[0]
        target_index = -1

    normalized_block = _normalize_mapping_yaml_text(automation_yaml)
    resolved_id = _resolved_automation_id_for_write(selected, automation_id, name_query)
    if resolved_id:
        normalized_block = _ensure_top_level_yaml_key(normalized_block, "id", resolved_id)

    write_meta = _write_or_append_automation_block(target_path, target_index, normalized_block, backup)

    final_id = _extract_top_level_yaml_key(normalized_block, "id")
    reload_result: dict[str, object] | list[object] | None = None
    if reload_automations:
        reload_result = _ha_request_json("POST", f"{base_url}/api/services/automation/reload", token, {})

    entity_id = _normalize_automation_entity_id(final_id) if final_id else ""
    verification = _verify_entity_states(base_url, token, [entity_id] if entity_id else [])
    return {
        "ok": True,
        "mode": "file",
        "automation_id": final_id,
        "entity_id": entity_id,
        "path": str(target_path),
        "reloaded": bool(reload_automations),
        "reload_result": reload_result if reload_automations else {},
        "verification": verification,
        "write": write_meta,
    }


def _update_automation_via_api(
    base_url: str,
    token: str,
    automation_id: str,
    name_query: str,
    automation_payload: dict[str, object],
    reload_automations: bool,
    create_if_missing: bool,
) -> dict[str, object]:
    resolved_id = ""
    if automation_id:
        resolved_id = _normalize_automation_entity_id(automation_id).split(".", 1)[1]
    elif name_query:
        found = _find_automations(base_url, token, {"query": name_query, "limit": 5})
        matches = found.get("matches", [])
        if not isinstance(matches, list) or not matches:
            if not create_if_missing:
                return {
                    "ok": False,
                    "mode": "api",
                    "reason": "No automation matched the provided name query.",
                    "matches": [],
                }
            maybe_id = str(automation_payload.get("id", "")).strip()
            if not maybe_id:
                raise RuntimeError("No automation matched name_query. Provide 'automation_id' or set id in YAML.")
            resolved_id = maybe_id
        elif len(matches) > 1 and _score_value(matches[0].get("score")) - _score_value(matches[1].get("score")) < 0.08:
            return {
                "ok": False,
                "mode": "api",
                "reason": "Multiple automations match this query. Please specify automation_id.",
                "matches": matches,
            }
        else:
            resolved_id = str(matches[0].get("automation_id", "")).strip()
    else:
        resolved_id = str(automation_payload.get("id", "")).strip()

    if not resolved_id:
        raise RuntimeError("Could not resolve automation id for update.")

    payload = dict(automation_payload)
    payload["id"] = resolved_id
    result = _create_or_update_automation(
        base_url,
        token,
        {
            "automation_id": resolved_id,
            "automation": payload,
            "reload": reload_automations,
        },
    )
    result["mode"] = "api"
    result["ok"] = True
    return result


def _create_automation_yaml_in_files(
    base_url: str,
    token: str,
    automation_yaml: str,
    reload_automations: bool,
    backup: bool,
    params: dict[str, str],
    target_file: str,
) -> dict[str, object]:
    paths = _configured_automation_file_paths(params)
    if target_file.strip():
        paths = [Path(target_file).expanduser()] + [path for path in paths if str(path) != target_file.strip()]
    if not paths:
        return {
            "ok": False,
            "mode": "file",
            "reason": "No Home Assistant automation YAML file paths are configured.",
        }

    target_path = paths[0]
    records = _load_automation_records_from_files([target_path])
    normalized_block = _normalize_mapping_yaml_text(automation_yaml)
    automation_id = _extract_top_level_yaml_key(normalized_block, "id")
    if not automation_id:
        raise RuntimeError("Automation YAML must include a non-empty top-level 'id' in file mode.")

    for existing in records:
        existing_id = str(existing.get("automation_id", "")).strip()
        if existing_id and existing_id == automation_id:
            raise RuntimeError(f"Automation id already exists in YAML file: {automation_id}")

    write_meta = _write_or_append_automation_block(target_path, -1, normalized_block, backup)

    reload_result: dict[str, object] | list[object] | None = None
    if reload_automations:
        reload_result = _ha_request_json("POST", f"{base_url}/api/services/automation/reload", token, {})

    entity_id = _normalize_automation_entity_id(automation_id)
    verification = _verify_entity_states(base_url, token, [entity_id])
    return {
        "ok": True,
        "mode": "file",
        "action": "created",
        "automation_id": automation_id,
        "entity_id": entity_id,
        "path": str(target_path),
        "reloaded": bool(reload_automations),
        "reload_result": reload_result if reload_automations else {},
        "verification": verification,
        "write": write_meta,
    }


def _load_automation_records_from_files(paths: list[Path]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        parsed = _extract_automation_blocks(text)
        blocks = parsed.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_record = {
                "path": str(path),
                "index": block.get("index", -1),
                "start_line": block.get("start_line", -1),
                "end_line": block.get("end_line", -1),
                "yaml": block.get("yaml", ""),
                "automation_id": block.get("automation_id", ""),
                "entity_id": block.get("entity_id", ""),
                "friendly_name": block.get("alias", ""),
                "alias": block.get("alias", ""),
            }
            records.append(block_record)
    return records


def _select_automation_record(
    records: list[dict[str, object]],
    automation_id: str,
    name_query: str,
    max_candidates: int,
) -> dict[str, object]:
    if automation_id:
        target = _normalize_automation_entity_id(automation_id).split(".", 1)[1]
        for record in records:
            current_id = str(record.get("automation_id", "")).strip()
            if current_id and current_id == target:
                return {"ok": True, "record": record}
        return {
            "ok": False,
            "reason": f"Automation id not found in YAML files: {target}",
            "matches": [],
        }

    if not name_query:
        return {
            "ok": False,
            "reason": "Provide either 'automation_id' or 'name_query'.",
            "matches": [],
        }

    scored: list[dict[str, object]] = []
    for record in records:
        candidate = {
            "entity_id": str(record.get("entity_id", "")).strip(),
            "automation_id": str(record.get("automation_id", "")).strip(),
            "friendly_name": str(record.get("friendly_name", "")).strip(),
            "alias": str(record.get("alias", "")).strip(),
            "state": "",
        }
        score = _automation_query_score(name_query, candidate)
        if score <= 0:
            continue
        scored.append(
            {
                "score": score,
                "record": record,
                "path": record.get("path", ""),
                "entity_id": candidate["entity_id"],
                "automation_id": candidate["automation_id"],
                "friendly_name": candidate["friendly_name"],
            }
        )

    scored.sort(key=lambda entry: (_score_value(entry.get("score")), str(entry.get("friendly_name", "")).lower()), reverse=True)
    if not scored:
        return {
            "ok": False,
            "reason": "No automation matched the provided name query in YAML files.",
            "matches": [],
        }
    if len(scored) > 1 and _score_value(scored[0].get("score")) - _score_value(scored[1].get("score")) < 0.08:
        return {
            "ok": False,
            "reason": "Multiple automations match this query in YAML files. Please specify automation_id.",
            "matches": scored[:max_candidates],
        }
    return {"ok": True, "record": scored[0]["record"]}


def _resolved_automation_id_for_write(selected: dict[str, object], automation_id: str, name_query: str) -> str:
    if automation_id:
        return _normalize_automation_entity_id(automation_id).split(".", 1)[1]
    if bool(selected.get("ok", False)):
        record = selected.get("record")
        if isinstance(record, dict):
            return str(record.get("automation_id", "")).strip()
    if name_query:
        return ""
    return ""


def _parse_automation_yaml_block(yaml_text: str) -> dict[str, object]:
    parsed_lines = _prepare_yaml_lines(_normalize_mapping_yaml_text(yaml_text))
    if not parsed_lines:
        raise RuntimeError("Automation YAML cannot be empty.")
    value, next_index = _parse_yaml_node(parsed_lines, 0)
    if next_index != len(parsed_lines):
        raise RuntimeError("Automation YAML contains unexpected trailing content.")
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    raise RuntimeError("Automation YAML must parse to one object (or a single-item list containing one object).")


def _dump_yaml_text(value: object) -> str:
    lines: list[str] = []
    _emit_yaml(value, 0, lines)
    dumped = "\n".join(lines).rstrip("\n")
    return dumped + "\n"


def _extract_automation_blocks(file_text: str) -> dict[str, object]:
    lines = file_text.splitlines()
    starts: list[int] = []
    for index, line in enumerate(lines):
        if line.startswith("-") and (len(line) == 1 or line[1] in {" ", "\t"}):
            starts.append(index)

    blocks: list[dict[str, object]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines) - 1
        block_lines = lines[start : end + 1]
        mapping_yaml = _list_item_lines_to_mapping_yaml(block_lines)
        automation_id = _extract_top_level_yaml_key(mapping_yaml, "id")
        alias = _extract_top_level_yaml_key(mapping_yaml, "alias")
        blocks.append(
            {
                "index": index,
                "start_line": start,
                "end_line": end,
                "yaml": mapping_yaml,
                "automation_id": automation_id,
                "entity_id": _normalize_automation_entity_id(automation_id) if automation_id else "",
                "alias": alias,
            }
        )

    return {
        "lines": lines,
        "blocks": blocks,
    }


def _list_item_lines_to_mapping_yaml(block_lines: list[str]) -> str:
    if not block_lines:
        return ""
    first = block_lines[0]
    if first == "-":
        first_content = ""
    elif first.startswith("- "):
        first_content = first[2:]
    else:
        first_content = first[1:].lstrip()

    normalized: list[str] = []
    if first_content:
        normalized.append(first_content)
    for line in block_lines[1:]:
        normalized.append(line[2:] if line.startswith("  ") else line)

    text = "\n".join(normalized).strip("\n")
    return text + ("\n" if text else "")


def _mapping_yaml_to_list_item_lines(mapping_yaml: str) -> list[str]:
    cleaned = _normalize_mapping_yaml_text(mapping_yaml)
    raw_lines = cleaned.splitlines()
    if not raw_lines:
        return ["-"]

    output: list[str] = []
    output.append("- " + raw_lines[0] if raw_lines[0].strip() else "-")
    for line in raw_lines[1:]:
        output.append("  " + line if line else "")
    return output


def _write_or_append_automation_block(path: Path, target_index: int, mapping_yaml: str, backup: bool) -> dict[str, object]:
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    extracted = _extract_automation_blocks(existing_text)
    lines = extracted.get("lines", [])
    blocks = extracted.get("blocks", [])
    if not isinstance(lines, list) or not isinstance(blocks, list):
        raise RuntimeError("Failed to parse automation YAML file structure.")

    replacement_lines = _mapping_yaml_to_list_item_lines(mapping_yaml)

    updated_lines: list[str]
    if target_index >= 0:
        if target_index >= len(blocks):
            raise RuntimeError("Target automation index was out of range for YAML replacement.")
        target = blocks[target_index]
        start = int(target.get("start_line", -1))
        end = int(target.get("end_line", -1))
        if start < 0 or end < start:
            raise RuntimeError("Invalid automation block range in YAML file.")
        updated_lines = [*lines[:start], *replacement_lines, *lines[end + 1 :]]
    else:
        updated_lines = list(lines)
        while updated_lines and not str(updated_lines[-1]).strip():
            updated_lines.pop()
        if updated_lines:
            updated_lines.append("")
        updated_lines.extend(replacement_lines)

    updated_text = "\n".join(str(line) for line in updated_lines).rstrip("\n") + "\n"
    return _write_text_atomic(path, updated_text, backup)


def _normalize_mapping_yaml_text(yaml_text: str) -> str:
    lines = [line.rstrip() for line in str(yaml_text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""

    first = lines[0].lstrip()
    if first.startswith("-"):
        return _list_item_lines_to_mapping_yaml(lines)
    return "\n".join(lines) + "\n"


def _extract_top_level_yaml_key(mapping_yaml: str, key: str) -> str:
    target = key.strip()
    for raw_line in mapping_yaml.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent != 0:
            continue
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
        candidate_key, candidate_value = stripped.split(":", 1)
        if candidate_key.strip() != target:
            continue
        return _normalize_inline_yaml_value(candidate_value.strip())
    return ""


def _ensure_top_level_yaml_key(mapping_yaml: str, key: str, value: str) -> str:
    lines = _normalize_mapping_yaml_text(mapping_yaml).splitlines()
    if not lines:
        return f"{key}: {_yaml_quote_string(value)}\n"

    replaced = False
    output: list[str] = []
    for raw_line in lines:
        if not replaced:
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            stripped = raw_line.strip()
            if indent == 0 and ":" in stripped:
                candidate_key, _ = stripped.split(":", 1)
                if candidate_key.strip() == key:
                    output.append(f"{key}: {_yaml_quote_string(value)}")
                    replaced = True
                    continue
        output.append(raw_line)

    if not replaced:
        output.insert(0, f"{key}: {_yaml_quote_string(value)}")
    return "\n".join(output).rstrip("\n") + "\n"


def _prepare_yaml_lines(yaml_text: str) -> list[tuple[int, str]]:
    parsed: list[tuple[int, str]] = []
    for raw_line in yaml_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped_right = raw_line.rstrip()
        if not stripped_right.strip():
            continue
        left_trimmed = stripped_right.lstrip(" ")
        if left_trimmed.startswith("#"):
            continue
        indent = len(stripped_right) - len(left_trimmed)
        parsed.append((indent, left_trimmed))
    return parsed


def _parse_yaml_node(lines: list[tuple[int, str]], start_index: int) -> tuple[object, int]:
    if start_index >= len(lines):
        raise RuntimeError("Unexpected end of YAML content.")
    indent, text = lines[start_index]
    if text.startswith("-"):
        return _parse_yaml_list(lines, start_index, indent)
    return _parse_yaml_map(lines, start_index, indent)


def _parse_yaml_map(lines: list[tuple[int, str]], start_index: int, base_indent: int) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {}
    index = start_index
    while index < len(lines):
        indent, text = lines[index]
        if indent < base_indent:
            break
        if indent > base_indent:
            raise RuntimeError("Invalid YAML indentation in mapping.")
        if text.startswith("-"):
            break
        if ":" not in text:
            raise RuntimeError(f"Invalid YAML mapping line: '{text}'")

        key_text, value_text = text.split(":", 1)
        key = key_text.strip()
        value_inline = value_text.strip()
        index += 1
        if value_inline:
            result[key] = _parse_yaml_scalar(value_inline)
            continue

        if index < len(lines) and lines[index][0] > indent:
            nested_value, index = _parse_yaml_node(lines, index)
            result[key] = nested_value
        else:
            result[key] = {}
    return result, index


def _parse_yaml_list(lines: list[tuple[int, str]], start_index: int, base_indent: int) -> tuple[list[object], int]:
    result: list[object] = []
    index = start_index
    while index < len(lines):
        indent, text = lines[index]
        if indent < base_indent:
            break
        if indent > base_indent:
            raise RuntimeError("Invalid YAML indentation in list.")
        if not text.startswith("-"):
            break

        item_inline = text[1:].strip()
        index += 1
        if not item_inline:
            if index < len(lines) and lines[index][0] > indent:
                nested_value, index = _parse_yaml_node(lines, index)
                result.append(nested_value)
            else:
                result.append(None)
            continue

        if ":" in item_inline and not item_inline.startswith(("'", '"')):
            key_text, value_text = item_inline.split(":", 1)
            item_map: dict[str, object] = {}
            key = key_text.strip()
            value_inline = value_text.strip()
            if value_inline:
                item_map[key] = _parse_yaml_scalar(value_inline)
            elif index < len(lines) and lines[index][0] > indent:
                nested_value, index = _parse_yaml_node(lines, index)
                item_map[key] = nested_value
            else:
                item_map[key] = {}

            while index < len(lines) and lines[index][0] > indent:
                nested_indent = lines[index][0]
                nested_map, next_index = _parse_yaml_map(lines, index, nested_indent)
                if not nested_map:
                    break
                item_map.update(nested_map)
                index = next_index
            result.append(item_map)
            continue

        result.append(_parse_yaml_scalar(item_inline))
    return result, index


def _parse_yaml_scalar(text: str) -> object:
    cleaned = text.strip()
    lower = cleaned.lower()
    if lower in {"null", "~"}:
        return None
    if lower == "true":
        return True
    if lower == "false":
        return False
    if re.fullmatch(r"-?\d+", cleaned):
        try:
            return int(cleaned)
        except ValueError:
            pass
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        try:
            return float(cleaned)
        except ValueError:
            pass
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        return _normalize_inline_yaml_value(cleaned)
    return cleaned


def _normalize_inline_yaml_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1]
    return value


def _emit_yaml(value: object, indent: int, lines: list[str]) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            lines.append(prefix + "{}")
            return
        for key, nested in value.items():
            key_text = str(key)
            if _is_yaml_scalar(nested):
                lines.append(prefix + f"{key_text}: {_yaml_scalar_text(nested)}")
            else:
                lines.append(prefix + f"{key_text}:")
                _emit_yaml(nested, indent + 2, lines)
        return

    if isinstance(value, list):
        if not value:
            lines.append(prefix + "[]")
            return
        for item in value:
            if _is_yaml_scalar(item):
                lines.append(prefix + f"- {_yaml_scalar_text(item)}")
            elif isinstance(item, dict) and item:
                keys = list(item.keys())
                first_key = str(keys[0])
                first_value = item[keys[0]]
                if _is_yaml_scalar(first_value):
                    lines.append(prefix + f"- {first_key}: {_yaml_scalar_text(first_value)}")
                else:
                    lines.append(prefix + f"- {first_key}:")
                    _emit_yaml(first_value, indent + 4, lines)

                for extra_key in keys[1:]:
                    extra_value = item[extra_key]
                    extra_prefix = " " * (indent + 2)
                    key_text = str(extra_key)
                    if _is_yaml_scalar(extra_value):
                        lines.append(extra_prefix + f"{key_text}: {_yaml_scalar_text(extra_value)}")
                    else:
                        lines.append(extra_prefix + f"{key_text}:")
                        _emit_yaml(extra_value, indent + 4, lines)
            else:
                lines.append(prefix + "-")
                _emit_yaml(item, indent + 2, lines)
        return

    lines.append(prefix + _yaml_scalar_text(value))


def _is_yaml_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _yaml_scalar_text(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _yaml_quote_string(value)
    return _yaml_quote_string(str(value))


def _yaml_quote_string(value: str) -> str:
    text = value.replace("\\", "\\\\").replace('"', '\\"')
    if text == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", text):
        lowered = text.lower()
        if lowered not in {"true", "false", "null", "~"}:
            return text
    return f'"{text}"'


def _write_text_atomic(path: Path, content: str, backup: bool) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)

    backup_path = Path(f"{path}.bak")
    if backup and path.exists():
        backup_path.write_bytes(path.read_bytes())

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp") as handle:
        handle.write(content)
        temp_path = Path(handle.name)

    temp_path.replace(path)
    return {
        "path": str(path),
        "backup_created": bool(backup and backup_path.exists()),
        "backup_path": str(backup_path) if backup and backup_path.exists() else "",
        "bytes_written": len(content.encode("utf-8")),
    }


def _get_automation(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    raw_automation_id = _required_str(arguments, "automation_id")
    entity_id = _normalize_automation_entity_id(raw_automation_id)
    encoded_id = parse.quote(entity_id, safe="")

    state_payload = _ha_request_json("GET", f"{base_url}/api/states/{encoded_id}", token, None)
    if not isinstance(state_payload, dict):
        raise RuntimeError("Home Assistant returned invalid automation payload.")

    automation_id = entity_id.split(".", 1)[1]
    config_payload: dict[str, object] | list[object] | None = None
    try:
        config_payload = _ha_request_json(
            "GET",
            f"{base_url}/api/config/automation/config/{parse.quote(automation_id, safe='')}",
            token,
            None,
        )
    except error.HTTPError as exc:
        if exc.code not in {400, 404, 405}:
            raise

    return {
        "entity_id": entity_id,
        "automation_id": automation_id,
        "state": str(state_payload.get("state", "")),
        "last_changed": str(state_payload.get("last_changed", "")),
        "attributes": state_payload.get("attributes", {}),
        "config": config_payload if isinstance(config_payload, dict) else {},
    }


def _create_or_update_automation(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    raw_automation_id = _required_str(arguments, "automation_id")
    automation_id = _normalize_automation_entity_id(raw_automation_id).split(".", 1)[1]
    reload_automations = bool(arguments.get("reload", True))

    automation = arguments.get("automation")
    if not isinstance(automation, dict):
        raise RuntimeError("'automation' must be an object.")

    payload = dict(automation)
    if not isinstance(payload.get("id"), str) or not str(payload.get("id", "")).strip():
        payload["id"] = automation_id

    write_result = _ha_request_json(
        "POST",
        f"{base_url}/api/config/automation/config/{parse.quote(automation_id, safe='')}",
        token,
        payload,
    )

    reloaded = False
    reload_result: dict[str, object] | list[object] | None = None
    if reload_automations:
        reload_result = _ha_request_json("POST", f"{base_url}/api/services/automation/reload", token, {})
        reloaded = True

    entity_id = f"automation.{automation_id}"
    state_payload: dict[str, object] = {}
    try:
        maybe_state = _ha_request_json(
            "GET",
            f"{base_url}/api/states/{parse.quote(entity_id, safe='')}",
            token,
            None,
        )
        if isinstance(maybe_state, dict):
            state_payload = maybe_state
    except error.HTTPError as exc:
        if exc.code not in {404}:
            raise

    return {
        "automation_id": automation_id,
        "entity_id": entity_id,
        "saved": True,
        "reloaded": reloaded,
        "write_result": write_result,
        "reload_result": reload_result if reloaded else {},
        "verification": _verify_entity_states(base_url, token, [entity_id]),
        "state": {
            "state": str(state_payload.get("state", "")),
            "last_changed": str(state_payload.get("last_changed", "")),
            "attributes": state_payload.get("attributes", {}),
        },
    }


def _normalize_automation_entity_id(raw_id: str) -> str:
    cleaned = raw_id.strip()
    if cleaned.startswith("automation."):
        return cleaned
    return f"automation.{cleaned}"


def _friendly_name(payload: dict[str, object]) -> str:
    attrs = payload.get("attributes")
    if not isinstance(attrs, dict):
        return ""
    name = attrs.get("friendly_name")
    return str(name).strip() if isinstance(name, str) else ""


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Missing required argument '{key}'.")
    return value.strip()


def _optional_str(arguments: dict[str, object], key: str, default: str) -> str:
    value = arguments.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _optional_int(arguments: dict[str, object], key: str, default: int, min_value: int, max_value: int) -> int:
    value = arguments.get(key)
    if isinstance(value, int):
        return max(min_value, min(max_value, value))
    return default


def _read_http_error(exc: error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="ignore")
    except Exception:
        raw = ""
    if not raw:
        return "No additional details."
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            if "error" in payload:
                return str(payload.get("error")).strip()
    except Exception:
        pass
    cleaned = " ".join(raw.split())
    if len(cleaned) > 240:
        return cleaned[:240] + "..."
    return cleaned


def _url_error_reason(exc: error.URLError) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    if reason is not None:
        text = str(reason).strip()
        if text:
            return text
    return "unknown network error"
