"""Home Assistant MCP plugin for entity control and automation management."""

from __future__ import annotations

import asyncio
import difflib
import json
import re
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
    description = "Full Home Assistant control: read/search entities, call any service, manage automations, and reach any REST API endpoint."
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
                id="search_entities",
                label="Search Entities",
                description=(
                    "Searches all Home Assistant entities by name or entity_id fragment. "
                    "Use this first when you need to find an entity and don't know its exact id. "
                    "Returns ranked matches with state, friendly_name, and entity_id."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "domain": {"type": "string", "description": "Optional domain filter (e.g. 'light', 'switch', 'sensor')."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "include_attributes": {"type": "boolean"},
                    },
                    "required": ["query"],
                },
            ),
            McpToolSpec(
                id="list_entities",
                label="List Entities",
                description=(
                    "Lists Home Assistant entities. Optionally filter by domain and/or a search string. "
                    "Returns total_count so you know if results were truncated. "
                    "Prefer search_entities when looking for specific entities by name."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "search": {"type": "string", "description": "Optional substring filter on entity_id and friendly_name."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
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
                description=(
                    "Calls any Home Assistant service with optional service_data and target, "
                    "then verifies target entity state when possible. "
                    "Set return_response=true for services that return data (e.g. todo.get_items, "
                    "calendar.get_events); omit it for fire-and-forget services. "
                    "If HA responds with '400: Bad Request', check that service_data fields match "
                    "the expected schema for that domain/service."
                ),
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
                id="get_services",
                label="Get Services",
                description=(
                    "Returns all available Home Assistant services grouped by domain, including their "
                    "field schemas. Use this to discover what services exist and what parameters they accept "
                    "before calling call_service."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Optional: filter to a single domain (e.g. 'light')."},
                    },
                },
            ),
            McpToolSpec(
                id="ha_api",
                label="Home Assistant API",
                description=(
                    "Calls any Home Assistant REST API endpoint directly. "
                    "Use this for anything not covered by the other tools: history, logbook, "
                    "areas, devices, floors, labels, config checks, templates, events, scenes, scripts, "
                    "calendars, etc. "
                    "path examples: '/api/history/period/2024-01-01T00:00:00', '/api/logbook', "
                    "'/api/config', '/api/states', '/api/template'. "
                    "method is GET or POST. payload is optional JSON body for POST requests."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": ["GET", "POST"]},
                        "path": {"type": "string", "minLength": 1, "description": "API path starting with /api/..."},
                        "payload": {"type": "object", "description": "Optional JSON body for POST requests."},
                    },
                    "required": ["method", "path"],
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
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id in {
            "search_entities",
            "list_entities",
            "get_entity_state",
            "get_services",
            "ha_api",
            "get_todo_items",
            "list_automations",
            "find_automations",
            "get_automation",
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
            if tool_id == "search_entities":
                return await asyncio.to_thread(_search_entities, base_url, token, arguments)

            if tool_id == "list_entities":
                return await asyncio.to_thread(_list_entities, base_url, token, arguments)

            if tool_id == "get_entity_state":
                return await asyncio.to_thread(_get_entity_state, base_url, token, arguments)

            if tool_id == "trigger_entity":
                return await asyncio.to_thread(_trigger_entity, base_url, token, arguments)

            if tool_id == "call_service":
                return await asyncio.to_thread(_call_service, base_url, token, arguments)

            if tool_id == "get_services":
                return await asyncio.to_thread(_get_services, base_url, token, arguments)

            if tool_id == "ha_api":
                return await asyncio.to_thread(_ha_api, base_url, token, arguments)

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

        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            raise RuntimeError(f"Home Assistant API request failed ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            reason = _url_error_reason(exc)
            raise RuntimeError(f"Network error while contacting Home Assistant: {reason}") from exc

        raise RuntimeError(f"Unsupported Home Assistant tool: {tool_id}")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _base_url(params: dict[str, str]) -> str:
    raw = str(params.get(BASE_URL_PARAM, "")).strip() or DEFAULT_BASE_URL
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "http://" + raw
    return raw.rstrip("/")


def _required_token(params: dict[str, str]) -> str:
    return str(params.get(TOKEN_PARAM, "")).strip()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

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
        if isinstance(loaded, (dict, list)):
            return loaded
        return {"value": loaded}


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


# ---------------------------------------------------------------------------
# Entity tools
# ---------------------------------------------------------------------------

def _fetch_all_states(base_url: str, token: str) -> list[dict[str, object]]:
    payload = _ha_request_json("GET", f"{base_url}/api/states", token, None)
    return [raw for raw in (payload if isinstance(payload, list) else []) if isinstance(raw, dict)]


def _entity_search_score(query: str, entity_id: str, friendly_name: str) -> float:
    q = query.strip().lower()
    eid = entity_id.lower()
    fname = friendly_name.lower()
    if not q:
        return 0.0
    score = 0.0
    if q == eid or q == fname:
        score += 1.5
    if fname and q in fname:
        score += 1.0
    if q in eid:
        score += 0.6
    tokens = [t for t in re.split(r"[^a-z0-9]+", q) if t]
    for token in tokens:
        if token in fname:
            score += 0.15
        if token in eid:
            score += 0.08
    score += max(
        difflib.SequenceMatcher(None, q, fname).ratio(),
        difflib.SequenceMatcher(None, q, eid).ratio(),
    ) * 0.4
    return round(score, 4)


def _format_entity(raw: dict[str, object], include_attributes: bool) -> dict[str, object]:
    entity_id = str(raw.get("entity_id", "")).strip()
    item: dict[str, object] = {
        "entity_id": entity_id,
        "domain": entity_id.split(".", 1)[0] if "." in entity_id else "",
        "state": str(raw.get("state", "")),
        "last_changed": str(raw.get("last_changed", "")),
        "friendly_name": _friendly_name(raw),
    }
    if include_attributes:
        attrs = raw.get("attributes")
        item["attributes"] = attrs if isinstance(attrs, dict) else {}
    return item


def _search_entities(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    query = _required_str(arguments, "query")
    domain_filter = _optional_str(arguments, "domain", "")
    include_attributes = bool(arguments.get("include_attributes", False))
    limit = _optional_int(arguments, "limit", 20, 1, 100)

    states = _fetch_all_states(base_url, token)

    scored: list[tuple[float, dict[str, object]]] = []
    for raw in states:
        entity_id = str(raw.get("entity_id", "")).strip()
        if not entity_id:
            continue
        if domain_filter and entity_id.split(".", 1)[0] != domain_filter:
            continue
        fname = _friendly_name(raw)
        score = _entity_search_score(query, entity_id, fname)
        if score <= 0:
            continue
        entry = _format_entity(raw, include_attributes)
        entry["score"] = score
        scored.append((score, entry))

    scored.sort(key=lambda t: t[0], reverse=True)
    results = [entry for _, entry in scored[:limit]]
    return {
        "query": query,
        "domain_filter": domain_filter,
        "count": len(results),
        "matches": results,
    }


def _list_entities(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    domain = _optional_str(arguments, "domain", "")
    search = _optional_str(arguments, "search", "").lower()
    include_attributes = bool(arguments.get("include_attributes", False))
    limit = _optional_int(arguments, "limit", 2000, 1, 5000)

    try:
        states = _fetch_all_states(base_url, token)
    except error.HTTPError as exc:
        if exc.code in {500, 502, 503, 504}:
            detail = _read_http_error(exc)
            return {
                "error": True,
                "error_code": exc.code,
                "error_message": f"Home Assistant temporarily unavailable ({exc.code}): {detail}. Try again later.",
                "total_count": 0,
                "count": 0,
                "domain_filter": domain,
                "entities": [],
            }
        raise

    all_matching: list[dict[str, object]] = []
    for raw in states:
        entity_id = str(raw.get("entity_id", "")).strip()
        if not entity_id:
            continue
        entity_domain = entity_id.split(".", 1)[0]
        if domain and entity_domain != domain:
            continue
        if search:
            fname = _friendly_name(raw).lower()
            if search not in entity_id.lower() and search not in fname:
                continue
        all_matching.append(_format_entity(raw, include_attributes))

    total = len(all_matching)
    truncated = all_matching[:limit]
    return {
        "total_count": total,
        "count": len(truncated),
        "truncated": total > limit,
        "domain_filter": domain,
        "search_filter": search,
        "entities": truncated,
    }


def _get_entity_state(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    encoded_id = parse.quote(entity_id, safe="")
    try:
        payload = _ha_request_json("GET", f"{base_url}/api/states/{encoded_id}", token, None)
    except error.HTTPError as exc:
        if exc.code == 404:
            return {
                "entity_id": entity_id,
                "error": True,
                "error_code": 404,
                "error_message": f"Entity '{entity_id}' not found in Home Assistant. Use search_entities to find the correct entity_id.",
            }
        if exc.code in {500, 502, 503, 504}:
            detail = _read_http_error(exc)
            return {
                "entity_id": entity_id,
                "error": True,
                "error_code": exc.code,
                "error_message": f"Home Assistant temporarily unavailable ({exc.code}): {detail}. Try again later.",
            }
        raise
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
            payload = {"entity_id": entity_id}
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

    payload = {"entity_id": entity_id}
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
    import logging as _logging
    _log = _logging.getLogger(__name__)

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

    try:
        result = _ha_service_call(base_url, token, domain, service, payload, return_response=return_response)
    except error.HTTPError as exc:
        detail = _read_http_error(exc)
        _log.debug(
            "call_service failed: domain=%s service=%s return_response=%s payload_keys=%s status=%s detail=%r",
            domain,
            service,
            return_response,
            list(payload.keys()),
            exc.code,
            detail,
        )
        if exc.code == 400 and "return_response" in detail:
            raise RuntimeError(
                f"Home Assistant requires return_response=true for {domain}.{service} "
                f"because this service returns data. Retry with return_response=true."
            ) from exc
        raise
    entity_ids = _extract_entity_ids_from_payload(payload)
    expected_state = "on" if service == "turn_on" else ("off" if service == "turn_off" else "")
    expected_by_entity = {eid: expected_state for eid in entity_ids} if expected_state else {}
    verification = _verify_entity_states(base_url, token, entity_ids, expected_states=expected_by_entity)
    return {
        "domain": domain,
        "service": service,
        "return_response": return_response,
        "result": result,
        "verification": verification,
    }


def _get_services(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    domain_filter = _optional_str(arguments, "domain", "")
    payload = _ha_request_json("GET", f"{base_url}/api/services", token, None)
    services = payload if isinstance(payload, list) else []

    if domain_filter:
        services = [
            entry for entry in services
            if isinstance(entry, dict) and str(entry.get("domain", "")) == domain_filter
        ]

    return {
        "domain_filter": domain_filter,
        "count": len(services),
        "services": services,
    }


def _ha_api(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    method = _optional_str(arguments, "method", "GET").upper()
    path = _required_str(arguments, "path")
    payload_arg = arguments.get("payload")

    if method not in {"GET", "POST"}:
        raise RuntimeError("method must be GET or POST.")

    if not path.startswith("/"):
        path = "/" + path

    url = base_url + path
    payload: Mapping[str, object] | None = None
    if method == "POST" and isinstance(payload_arg, dict):
        payload = payload_arg

    result = _ha_request_json(method, url, token, payload)

    # Summarise very large list results so they don't flood the context.
    if isinstance(result, list) and len(result) > 200:
        return {
            "total_count": len(result),
            "truncated": True,
            "note": f"Result list has {len(result)} items; returning first 200. Refine the query or add filters.",
            "items": result[:200],
        }

    return {"result": result} if not isinstance(result, dict) else result


# ---------------------------------------------------------------------------
# Todo tools
# ---------------------------------------------------------------------------

def _get_todo_items(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    entity_id = _required_str(arguments, "entity_id")
    payload: dict[str, object] = {"entity_id": entity_id}
    status = _normalize_todo_status(arguments.get("status"))
    if status:
        payload["status"] = status

    try:
        result = _ha_service_call(base_url, token, "todo", "get_items", payload, return_response=True)
    except error.HTTPError as exc:
        if exc.code in {500, 502, 503, 504}:
            detail = _read_http_error(exc)
            return {
                "entity_id": entity_id,
                "error": True,
                "error_code": exc.code,
                "error_message": f"Home Assistant temporarily unavailable ({exc.code}): {detail}. Try again later.",
                "items": [],
                "count": 0,
            }
        raise
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


# ---------------------------------------------------------------------------
# Automation tools
# ---------------------------------------------------------------------------

def _list_automations(base_url: str, token: str, arguments: dict[str, object]) -> dict[str, object]:
    include_attributes = bool(arguments.get("include_attributes", False))
    include_disabled = bool(arguments.get("include_disabled", True))
    limit = _optional_int(arguments, "limit", 500, 1, 1000)

    try:
        states = _fetch_all_states(base_url, token)
    except error.HTTPError as exc:
        if exc.code in {500, 502, 503, 504}:
            detail = _read_http_error(exc)
            return {
                "error": True,
                "error_code": exc.code,
                "error_message": f"Home Assistant temporarily unavailable ({exc.code}): {detail}. Try again later.",
                "count": 0,
                "automations": [],
            }
        raise

    automations: list[dict[str, object]] = []
    for raw in states:
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

        entry: dict[str, object] = {
            "entity_id": candidate["entity_id"],
            "automation_id": candidate["automation_id"],
            "friendly_name": candidate["friendly_name"],
            "alias": candidate["alias"],
            "state": candidate["state"],
            "score": score,
        }
        if include_attributes:
            entry["attributes"] = item.get("attributes", {})
        if include_config:
            try:
                conf = _ha_request_json(
                    "GET",
                    f"{base_url}/api/config/automation/config/{parse.quote(candidate['automation_id'], safe='')}",
                    token,
                    None,
                )
                entry["config"] = conf if isinstance(conf, dict) else {}
            except error.HTTPError as exc:
                if exc.code not in {400, 404, 405}:
                    raise
                entry["config"] = {}
            except Exception:
                entry["config"] = {}

        scored.append(entry)

    scored.sort(
        key=lambda e: (_score_value(e.get("score", 0.0)), str(e.get("friendly_name", "")).lower()),
        reverse=True,
    )
    top = scored[:limit]
    ambiguous = (
        len(top) > 1
        and abs(_score_value(top[0].get("score", 0.0)) - _score_value(top[1].get("score", 0.0))) < 0.08
    )
    return {
        "query": query,
        "count": len(top),
        "ambiguous": ambiguous,
        "matches": top,
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


# ---------------------------------------------------------------------------
# Automation search helpers
# ---------------------------------------------------------------------------

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
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _automation_query_score(query: str, candidate: dict[str, str]) -> float:
    query_clean = query.strip().lower()
    if not query_clean:
        return 0.0

    entity_id = candidate.get("entity_id", "").lower()
    automation_id = candidate.get("automation_id", "").lower()
    friendly_name = candidate.get("friendly_name", "").lower()
    alias = candidate.get("alias", "").lower()

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


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------

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
            failures.append({"entity_id": entity_id, "detail": str(exc)})

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


# ---------------------------------------------------------------------------
# Todo helpers
# ---------------------------------------------------------------------------

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


def _extract_todo_items_from_service_response(
    result: dict[str, object] | list[object],
    entity_id: str,
) -> list[dict[str, object]]:
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
    return [item for item in maybe_items if isinstance(item, dict)]


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


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

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
