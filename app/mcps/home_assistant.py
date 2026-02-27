"""Home Assistant MCP plugin for entity control and automation management."""

from __future__ import annotations

import asyncio
import json
from typing import Mapping
from urllib import error, parse, request

from .base import MCPPlugin, McpConfigField, McpToolSpec


HOME_ASSISTANT_MCP_ID = "home_assistant"
BASE_URL_PARAM = "base_url"
TOKEN_PARAM = "long_lived_token"
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
                description="Triggers an entity action (toggle, turn_on, turn_off, or automation trigger).",
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
                description="Calls any Home Assistant service with optional service_data and target.",
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
                description="Adds one item to a Home Assistant todo list.",
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
                description="Updates one item in a Home Assistant todo list.",
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
                description="Removes one item from a Home Assistant todo list.",
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
                description="Removes all completed items from a Home Assistant todo list.",
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
                description="Creates or updates automation config by automation_id.",
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
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id in {"list_entities", "get_entity_state", "get_todo_items", "list_automations", "get_automation"}:
            return ""
        return (
            "Home Assistant safety reminder:\n"
            "- Execute only actions explicitly requested by the user in this chat.\n"
            "- Confirm exact entity IDs and service intent before making device or automation changes.\n"
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

            if tool_id == "get_automation":
                return await asyncio.to_thread(_get_automation, base_url, token, arguments)

            if tool_id == "create_or_update_automation":
                return await asyncio.to_thread(_create_or_update_automation, base_url, token, arguments)
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
            return {
                "entity_id": entity_id,
                "action": action,
                "result": result,
            }
        if domain == "script":
            payload: dict[str, object] = {"entity_id": entity_id}
            result = _ha_request_json("POST", f"{base_url}/api/services/script/turn_on", token, payload)
            return {
                "entity_id": entity_id,
                "action": action,
                "result": result,
            }
        raise RuntimeError("Action 'trigger' is supported for automation.* and script.* entities.")

    if action not in {"toggle", "turn_on", "turn_off"}:
        raise RuntimeError("Invalid action. Use one of: toggle, turn_on, turn_off, trigger.")

    payload: dict[str, object] = {"entity_id": entity_id}
    result = _ha_request_json("POST", f"{base_url}/api/services/homeassistant/{action}", token, payload)
    return {
        "entity_id": entity_id,
        "action": action,
        "result": result,
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
    return {
        "domain": domain,
        "service": service,
        "return_response": return_response,
        "result": result,
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
    return {
        "entity_id": entity_id,
        "item": item,
        "result": result,
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
    return {
        "entity_id": entity_id,
        "item": item,
        "result": result,
    }


def _remove_todo_item(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    item = _required_str(arguments, "item")
    payload: dict[str, object] = {"entity_id": entity_id, "item": item}
    result = _ha_service_call(base_url, token, "todo", "remove_item", payload)
    return {
        "entity_id": entity_id,
        "item": item,
        "result": result,
    }


def _remove_completed_todo_items(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    payload: dict[str, object] = {"entity_id": entity_id}
    result = _ha_service_call(base_url, token, "todo", "remove_completed_items", payload)
    return {
        "entity_id": entity_id,
        "result": result,
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
