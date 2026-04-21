"""UniFi Network MCP plugin for read-only Site Manager and Network API access."""

from __future__ import annotations

import asyncio
import json
from typing import Mapping
from urllib import error, parse, request

from .base import MCPPlugin, McpConfigField, McpToolSpec


UNIFI_NETWORK_MCP_ID = "unifi_network"
API_KEY_PARAM = "api_key"
CLOUD_BASE_URL_PARAM = "cloud_base_url"
DEFAULT_SITE_ID_PARAM = "default_site_id"
DEFAULT_CONSOLE_ID_PARAM = "default_console_id"
DEFAULT_CLOUD_BASE_URL = "https://api.ui.com"
CONNECTOR_NETWORK_PREFIX = "proxy/network/integration/v1"
_LIST_PAGE_LIMIT_MAX = 200
_MAX_RESULT_ITEMS = 200


class UniFiNetworkMCP(MCPPlugin):
    mcp_id = UNIFI_NETWORK_MCP_ID
    display_name = "UniFi Network"
    description = (
        "Read-only UniFi troubleshooting via Site Manager and Network API: discover sites and consoles, "
        "inspect devices and clients, and query generic UniFi endpoints through the official connector proxy."
    )
    config_fields = [
        McpConfigField(
            id=API_KEY_PARAM,
            label="API Key",
            type="password",
            required=True,
            placeholder="ui_...",
            description="Create a UniFi API key in Site Manager. A setup link is shown in this MCP card.",
        ),
        McpConfigField(
            id=CLOUD_BASE_URL_PARAM,
            label="Cloud Base URL",
            type="text",
            required=False,
            placeholder=DEFAULT_CLOUD_BASE_URL,
            description="UniFi API base URL. Defaults to https://api.ui.com.",
        ),
        McpConfigField(
            id=DEFAULT_SITE_ID_PARAM,
            label="Default Site ID",
            type="text",
            required=False,
            placeholder="UUID from list_sites",
            description="Optional default site ID used when a tool call omits site_id.",
        ),
        McpConfigField(
            id=DEFAULT_CONSOLE_ID_PARAM,
            label="Default Console ID",
            type="text",
            required=False,
            placeholder="host/console id",
            description="Optional default UniFi console ID used for connector proxy calls.",
        ),
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="list_sites",
                label="List Sites",
                description="Lists UniFi sites from Site Manager. Use this first to discover site IDs and linked console IDs.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "page_size": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "next_token": {"type": "string"},
                    },
                },
            ),
            McpToolSpec(
                id="list_hosts",
                label="List Hosts",
                description="Lists UniFi hosts/consoles from Site Manager.",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
            ),
            McpToolSpec(
                id="list_network_sites",
                label="List Local Sites",
                description="Lists local UniFi Network sites from a console through the official connector proxy.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "console_id": {"type": "string"},
                    },
                },
            ),
            McpToolSpec(
                id="list_devices",
                label="List Devices",
                description="Lists adopted UniFi devices for one site with optional filtering and pagination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": _LIST_PAGE_LIMIT_MAX},
                        "filter": {"type": "string", "description": "Optional UniFi API filter expression."},
                    },
                },
            ),
            McpToolSpec(
                id="get_device_details",
                label="Get Device Details",
                description="Fetches detailed UniFi device information for one adopted device.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string", "minLength": 1},
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                    },
                    "required": ["device_id"],
                },
            ),
            McpToolSpec(
                id="list_clients",
                label="List Clients",
                description="Lists connected clients for one site with optional filtering and pagination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": _LIST_PAGE_LIMIT_MAX},
                        "filter": {"type": "string", "description": "Optional UniFi API filter expression."},
                    },
                },
            ),
            McpToolSpec(
                id="list_networks",
                label="List Networks",
                description="Lists UniFi networks and VLAN inventory for one site so WAN incidents can be correlated with affected LANs.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": _LIST_PAGE_LIMIT_MAX},
                        "filter": {"type": "string", "description": "Optional UniFi API filter expression."},
                    },
                },
            ),
            McpToolSpec(
                id="list_wans",
                label="List WAN Interfaces",
                description="Lists WAN interfaces for one UniFi site so the agent can identify uplinks before deeper WAN diagnostics.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": _LIST_PAGE_LIMIT_MAX},
                    },
                },
            ),
            McpToolSpec(
                id="get_isp_metrics",
                label="Get ISP Metrics",
                description=(
                    "Reads account-level UniFi ISP metrics from Site Manager for WAN troubleshooting. "
                    "Use type=5m for short outages or type=1h for longer history."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["5m", "1h"]},
                        "duration": {"type": "string", "description": "For 5m use up to 24h; for 1h use up to 7d or 30d."},
                        "begin_timestamp": {"type": "string", "description": "RFC3339 timestamp."},
                        "end_timestamp": {"type": "string", "description": "RFC3339 timestamp."},
                    },
                    "required": ["type"],
                },
            ),
            McpToolSpec(
                id="query_isp_metrics",
                label="Query ISP Metrics",
                description=(
                    "Queries WAN metrics for one or more specific UniFi sites using required siteId and hostId pairs. "
                    "Use this when diagnosing one problem site precisely."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["5m", "1h"]},
                        "sites": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "site_id": {"type": "string", "minLength": 1},
                                    "host_id": {"type": "string", "minLength": 1},
                                    "begin_timestamp": {"type": "string"},
                                    "end_timestamp": {"type": "string"},
                                },
                                "required": ["site_id", "host_id"],
                            },
                        },
                    },
                    "required": ["type", "sites"],
                },
            ),
            McpToolSpec(
                id="summarize_wan_health",
                label="Summarize WAN Health",
                description=(
                    "Builds a WAN troubleshooting summary for one or more sites using ISP metrics. "
                    "Returns per-site health states like healthy, degraded, down, or no_data."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["5m", "1h"]},
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "host_id": {"type": "string"},
                        "sites": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "site_id": {"type": "string"},
                                    "site_name": {"type": "string"},
                                    "host_id": {"type": "string"},
                                },
                            },
                        },
                        "begin_timestamp": {"type": "string"},
                        "end_timestamp": {"type": "string"},
                    },
                    "required": ["type"],
                },
            ),
            McpToolSpec(
                id="debug_wan_outage",
                label="Debug WAN Outage",
                description=(
                    "Builds a structured WAN outage report for one site using WAN inventory, network inventory, and recent ISP metrics. "
                    "Use this as the first incident-response tool when internet seems down."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                        "host_id": {"type": "string"},
                        "type": {"type": "string", "enum": ["5m", "1h"]},
                        "begin_timestamp": {"type": "string"},
                        "end_timestamp": {"type": "string"},
                    },
                    "required": ["type"],
                },
            ),
            McpToolSpec(
                id="get_client_details",
                label="Get Client Details",
                description="Fetches detailed UniFi client information for one connected client.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "client_id": {"type": "string", "minLength": 1},
                        "site_id": {"type": "string"},
                        "site_name": {"type": "string"},
                        "console_id": {"type": "string"},
                    },
                    "required": ["client_id"],
                },
            ),
            McpToolSpec(
                id="site_manager_get",
                label="Site Manager GET",
                description="Calls any read-only UniFi Site Manager GET endpoint under /v1 for generic discovery and diagnostics.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "description": "Path like /v1/sites or /v1/hosts."},
                        "query": {"type": "object", "description": "Optional query parameters."},
                    },
                    "required": ["path"],
                },
            ),
            McpToolSpec(
                id="proxy_get",
                label="Connector GET",
                description=(
                    "Calls any read-only UniFi connector proxy endpoint for deeper UniFi Network inspection. "
                    "Pass either a full proxy path like /proxy/network/integration/v1/sites or a path relative to /proxy/network/integration/v1."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "console_id": {"type": "string"},
                        "path": {"type": "string", "minLength": 1},
                        "query": {"type": "object", "description": "Optional query parameters."},
                    },
                    "required": ["path"],
                },
            ),
        ]

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id in {"list_sites", "list_hosts", "list_network_sites", "list_devices", "get_device_details", "list_clients", "list_networks", "list_wans", "get_isp_metrics", "query_isp_metrics", "summarize_wan_health", "debug_wan_outage", "get_client_details", "site_manager_get", "proxy_get"}:
            return (
                "UniFi Network safety reminder:\n"
                "- This MCP is read-only; do not attempt state-changing UniFi actions with it.\n"
                "- Prefer discovery tools first: list_sites, list_hosts, list_network_sites, list_devices, list_clients, list_networks, list_wans.\n"
                "- Use proxy_get only when the specialized read tools do not cover the needed endpoint.\n"
                "- For WAN outages, use debug_wan_outage or summarize_wan_health before assuming the issue is local to one client.\n"
                "- If site or console selection is ambiguous, return the ambiguity instead of guessing.\n"
                "- Return JSON only with this shape: {\"arguments\":{...}}"
            )
        return ""

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        api_key = _required_api_key(params)
        if not api_key:
            return False, "UniFi API key is required."

        base_url = _cloud_base_url(params)
        try:
            payload = await asyncio.to_thread(
                _request_json,
                "GET",
                _build_url(base_url, "/v1/sites", {"pageSize": 1}),
                api_key,
            )
        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            if exc.code in {401, 403}:
                return False, "UniFi rejected the API key."
            return False, f"UniFi verification failed ({exc.code}): {detail}"
        except error.URLError as exc:
            return False, f"Network error while contacting UniFi: {_url_error_reason(exc)}"
        except Exception:
            return False, "Unexpected error while verifying UniFi connection."

        sites = _extract_items(payload)
        return True, f"UniFi API connected at {base_url}. {len(sites)} site(s) returned by verification call."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        api_key = _required_api_key(params)
        if not api_key:
            raise RuntimeError("UniFi API key is missing.")

        base_url = _cloud_base_url(params)
        try:
            if tool_id == "list_sites":
                return await asyncio.to_thread(_list_sites, base_url, api_key, arguments)
            if tool_id == "list_hosts":
                return await asyncio.to_thread(_list_hosts, base_url, api_key)
            if tool_id == "list_network_sites":
                return await asyncio.to_thread(_list_network_sites, base_url, api_key, arguments, params)
            if tool_id == "list_devices":
                return await asyncio.to_thread(_list_devices, base_url, api_key, arguments, params)
            if tool_id == "get_device_details":
                return await asyncio.to_thread(_get_device_details, base_url, api_key, arguments, params)
            if tool_id == "list_clients":
                return await asyncio.to_thread(_list_clients, base_url, api_key, arguments, params)
            if tool_id == "list_networks":
                return await asyncio.to_thread(_list_networks, base_url, api_key, arguments, params)
            if tool_id == "list_wans":
                return await asyncio.to_thread(_list_wans, base_url, api_key, arguments, params)
            if tool_id == "get_isp_metrics":
                return await asyncio.to_thread(_get_isp_metrics, base_url, api_key, arguments)
            if tool_id == "query_isp_metrics":
                return await asyncio.to_thread(_query_isp_metrics, base_url, api_key, arguments)
            if tool_id == "summarize_wan_health":
                return await asyncio.to_thread(_summarize_wan_health, base_url, api_key, arguments, params)
            if tool_id == "debug_wan_outage":
                return await asyncio.to_thread(_debug_wan_outage, base_url, api_key, arguments, params)
            if tool_id == "get_client_details":
                return await asyncio.to_thread(_get_client_details, base_url, api_key, arguments, params)
            if tool_id == "site_manager_get":
                return await asyncio.to_thread(_site_manager_get, base_url, api_key, arguments)
            if tool_id == "proxy_get":
                return await asyncio.to_thread(_proxy_get, base_url, api_key, arguments, params)
        except error.HTTPError as exc:
            detail = _read_http_error(exc)
            raise RuntimeError(f"UniFi API request failed ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Network error while contacting UniFi: {_url_error_reason(exc)}") from exc

        raise RuntimeError(f"Unsupported UniFi Network tool: {tool_id}")


def _list_sites(base_url: str, api_key: str, arguments: dict[str, object]) -> dict[str, object]:
    query: dict[str, object] = {}
    page_size = _optional_int(arguments, "page_size", 0, 1, 1000)
    next_token = _optional_str(arguments, "next_token", "")
    if page_size:
        query["pageSize"] = page_size
    if next_token:
        query["nextToken"] = next_token

    payload = _request_json("GET", _build_url(base_url, "/v1/sites", query), api_key)
    items = _extract_items(payload)
    return {
        "count": len(items),
        "next_token": _extract_next_token(payload),
        "sites": _summarize_sites(items),
        "raw": _truncate_payload_lists(payload),
    }


def _list_hosts(base_url: str, api_key: str) -> dict[str, object]:
    payload = _request_json("GET", _build_url(base_url, "/v1/hosts", None), api_key)
    items = _extract_items(payload)
    return {
        "count": len(items),
        "hosts": _summarize_hosts(items),
        "raw": _truncate_payload_lists(payload),
    }


def _list_network_sites(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    console_id = _resolve_console_id(base_url, api_key, arguments, params)
    payload = _connector_get(base_url, api_key, console_id, "sites", None)
    items = _extract_items(payload)
    return {
        "console_id": console_id,
        "count": len(items),
        "sites": items[:_MAX_RESULT_ITEMS],
        "truncated": len(items) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _list_devices(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    query = _list_query(arguments)
    payload = _connector_get(base_url, api_key, console_id, f"sites/{site_id}/devices", query)
    items = _extract_items(payload)
    return {
        "site_id": site_id,
        "console_id": console_id,
        "count": len(items),
        "devices": items[:_MAX_RESULT_ITEMS],
        "truncated": len(items) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _get_device_details(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    device_id = _required_str(arguments, "device_id")
    payload = _connector_get(base_url, api_key, console_id, f"sites/{site_id}/devices/{parse.quote(device_id, safe='')}", None)
    return {
        "site_id": site_id,
        "console_id": console_id,
        "device_id": device_id,
        "device": _truncate_payload_lists(payload),
    }


def _list_clients(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    query = _list_query(arguments)
    payload = _connector_get(base_url, api_key, console_id, f"sites/{site_id}/clients", query)
    items = _extract_items(payload)
    return {
        "site_id": site_id,
        "console_id": console_id,
        "count": len(items),
        "clients": items[:_MAX_RESULT_ITEMS],
        "truncated": len(items) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _list_networks(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    query = _list_query(arguments)
    payload = _connector_get(base_url, api_key, console_id, f"sites/{site_id}/networks", query)
    items = _extract_items(payload)
    return {
        "site_id": site_id,
        "console_id": console_id,
        "count": len(items),
        "networks": items[:_MAX_RESULT_ITEMS],
        "truncated": len(items) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _list_wans(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    query = {
        "offset": _optional_int(arguments, "offset", 0, 0, 1000000),
        "limit": _optional_int(arguments, "limit", 25, 1, _LIST_PAGE_LIMIT_MAX),
    }
    payload = _connector_get(base_url, api_key, console_id, f"sites/{site_id}/wans", query)
    items = _extract_items(payload)
    return {
        "site_id": site_id,
        "console_id": console_id,
        "count": len(items),
        "wans": items[:_MAX_RESULT_ITEMS],
        "truncated": len(items) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _get_isp_metrics(base_url: str, api_key: str, arguments: dict[str, object]) -> dict[str, object]:
    metric_type = _validate_metric_type(_required_str(arguments, "type"))
    query = _isp_metric_query(arguments)
    payload = _request_json("GET", _build_url(base_url, f"/v1/isp-metrics/{parse.quote(metric_type, safe='')}", query), api_key)
    items = _extract_items(payload)
    return {
        "type": metric_type,
        "query": query,
        "count": len(items),
        "metrics": items[:_MAX_RESULT_ITEMS],
        "truncated": len(items) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _query_isp_metrics(base_url: str, api_key: str, arguments: dict[str, object]) -> dict[str, object]:
    metric_type = _validate_metric_type(_required_str(arguments, "type"))
    raw_sites = arguments.get("sites")
    if not isinstance(raw_sites, list) or not raw_sites:
        raise RuntimeError("query_isp_metrics requires a non-empty 'sites' array.")

    request_sites: list[dict[str, object]] = []
    for entry in raw_sites:
        if not isinstance(entry, dict):
            continue
        site_payload: dict[str, object] = {
            "siteId": _required_str_from_mapping(entry, "site_id"),
            "hostId": _required_str_from_mapping(entry, "host_id"),
        }
        begin_timestamp = _optional_str(entry, "begin_timestamp", "")
        end_timestamp = _optional_str(entry, "end_timestamp", "")
        if begin_timestamp:
            site_payload["beginTimestamp"] = begin_timestamp
        if end_timestamp:
            site_payload["endTimestamp"] = end_timestamp
        request_sites.append(site_payload)

    if not request_sites:
        raise RuntimeError("query_isp_metrics requires at least one valid site entry.")

    payload = _request_json(
        "POST",
        _build_url(base_url, f"/v1/isp-metrics/{parse.quote(metric_type, safe='')}/query", None),
        api_key,
        {"sites": request_sites},
    )
    metrics = _extract_metrics_from_query_payload(payload)
    status = _extract_named_field(payload if isinstance(payload, dict) else {}, ("status",)) if isinstance(payload, dict) else ""
    message = _extract_named_field(payload if isinstance(payload, dict) else {}, ("message",)) if isinstance(payload, dict) else ""
    return {
        "type": metric_type,
        "status": status,
        "message": message,
        "count": len(metrics),
        "metrics": metrics[:_MAX_RESULT_ITEMS],
        "truncated": len(metrics) > _MAX_RESULT_ITEMS,
        "raw": _truncate_payload_lists(payload),
    }


def _summarize_wan_health(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    metric_type = _validate_metric_type(_required_str(arguments, "type"))
    request_sites = _build_wan_summary_request_sites(base_url, api_key, arguments, params)
    payload = _request_json(
        "POST",
        _build_url(base_url, f"/v1/isp-metrics/{parse.quote(metric_type, safe='')}/query", None),
        api_key,
        {"sites": request_sites},
    )
    metrics = _extract_metrics_from_query_payload(payload)
    summaries = [_summarize_metric_entry(entry) for entry in metrics[:_MAX_RESULT_ITEMS]]
    return {
        "type": metric_type,
        "requested_sites": request_sites,
        "count": len(summaries),
        "summary": summaries,
        "raw": _truncate_payload_lists(payload),
    }


def _debug_wan_outage(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    metric_type = _validate_metric_type(_required_str(arguments, "type"))
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    host_id = _optional_str(arguments, "host_id", "") or _resolve_console_id(
        base_url,
        api_key,
        {"site_id": site_id, "console_id": console_id},
        params,
        site_id=site_id,
    )

    wans_payload = _list_wans(base_url, api_key, {"site_id": site_id, "console_id": console_id, "limit": 50}, params)
    networks_payload = _list_networks(base_url, api_key, {"site_id": site_id, "console_id": console_id, "limit": 100}, params)
    summary_payload = _summarize_wan_health(
        base_url,
        api_key,
        {
            "type": metric_type,
            "sites": [{"site_id": site_id, "host_id": host_id}],
            "begin_timestamp": _optional_str(arguments, "begin_timestamp", ""),
            "end_timestamp": _optional_str(arguments, "end_timestamp", ""),
        },
        params,
    )

    site_summary = summary_payload.get("summary")
    latest_summary = site_summary[0] if isinstance(site_summary, list) and site_summary else {}
    health = latest_summary.get("health", "no_data") if isinstance(latest_summary, dict) else "no_data"
    wan_entries = wans_payload.get("wans")
    wan_list: list[object] = wan_entries if isinstance(wan_entries, list) else []
    network_entries = networks_payload.get("networks")
    network_list: list[object] = network_entries if isinstance(network_entries, list) else []
    recommendations = _build_wan_recommendations(
        str(health),
        wan_list,
        network_list,
        latest_summary if isinstance(latest_summary, dict) else {},
    )

    return {
        "site_id": site_id,
        "console_id": console_id,
        "host_id": host_id,
        "metric_type": metric_type,
        "health": health,
        "wan_summary": latest_summary,
        "wans": wan_list,
        "networks": _summarize_network_inventory(network_list),
        "recommendations": recommendations,
        "raw": {
            "wan_inventory": wans_payload,
            "network_inventory": networks_payload,
            "metric_summary": summary_payload,
        },
    }


def _get_client_details(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    site_id, console_id = _resolve_site_and_console(base_url, api_key, arguments, params)
    client_id = _required_str(arguments, "client_id")
    payload = _connector_get(base_url, api_key, console_id, f"sites/{site_id}/clients/{parse.quote(client_id, safe='')}", None)
    return {
        "site_id": site_id,
        "console_id": console_id,
        "client_id": client_id,
        "client": _truncate_payload_lists(payload),
    }


def _site_manager_get(base_url: str, api_key: str, arguments: dict[str, object]) -> dict[str, object]:
    path = _normalize_site_manager_path(_required_str(arguments, "path"))
    query = _optional_query_dict(arguments.get("query"))
    payload = _request_json("GET", _build_url(base_url, path, query), api_key)
    return {
        "path": path,
        "query": query,
        "result": _truncate_payload_lists(payload),
    }


def _proxy_get(base_url: str, api_key: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    console_id = _resolve_console_id(base_url, api_key, arguments, params)
    path = _normalize_proxy_path(_required_str(arguments, "path"))
    query = _optional_query_dict(arguments.get("query"))
    payload = _request_json(
        "GET",
        _build_url(base_url, f"/v1/connector/consoles/{parse.quote(console_id, safe='')}/{path}", query),
        api_key,
    )
    return {
        "console_id": console_id,
        "path": "/" + path,
        "query": query,
        "result": _truncate_payload_lists(payload),
    }


def _connector_get(
    base_url: str,
    api_key: str,
    console_id: str,
    relative_path: str,
    query: Mapping[str, object] | None,
) -> dict[str, object] | list[object]:
    normalized_relative = relative_path.strip().lstrip("/")
    full_path = f"/v1/connector/consoles/{parse.quote(console_id, safe='')}/{CONNECTOR_NETWORK_PREFIX}/{normalized_relative}"
    return _request_json("GET", _build_url(base_url, full_path, query), api_key)


def _match_network_site(sites: list[dict[str, object]], query_text: str) -> dict[str, object] | None:
    query = query_text.strip().lower()
    if not query:
        return None

    def candidates(site: dict[str, object]) -> list[str]:
        values = [
            _extract_site_id(site),
            _extract_named_field(site, ("name", "displayName", "siteName", "desc", "internalReference")),
        ]
        internal_reference = site.get("internalReference")
        if isinstance(internal_reference, str):
            values.append(internal_reference.strip())
        return [value.strip().lower() for value in values if isinstance(value, str) and value.strip()]

    exact = [site for site in sites if query in candidates(site)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError(f"Multiple local UniFi Network sites matched '{query_text}'. Use the exact local site id.")

    partial = [site for site in sites if any(query in candidate for candidate in candidates(site))]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise RuntimeError(f"Multiple local UniFi Network sites partially matched '{query_text}'. Use the exact local site id.")
    return None


def _resolve_site_and_console(
    base_url: str,
    api_key: str,
    arguments: dict[str, object],
    params: dict[str, str],
) -> tuple[str, str]:
    console_id = _resolve_console_id(base_url, api_key, arguments, params)
    site_id = _resolve_site_id(base_url, api_key, arguments, params, console_id=console_id)
    return site_id, console_id


def _resolve_site_id(
    base_url: str,
    api_key: str,
    arguments: dict[str, object],
    params: dict[str, str],
    *,
    console_id: str = "",
) -> str:
    explicit_site_id = _optional_str(arguments, "site_id", "") or str(params.get(DEFAULT_SITE_ID_PARAM, "")).strip()
    site_name = _optional_str(arguments, "site_name", "")
    resolved_console_id = console_id or _resolve_console_id(base_url, api_key, arguments, params)
    local_sites_payload = _connector_get(base_url, api_key, resolved_console_id, "sites", None)
    local_sites = _extract_items(local_sites_payload)

    if explicit_site_id:
        matched_by_id = _match_network_site(local_sites, explicit_site_id)
        if matched_by_id is not None:
            matched_site_id = _extract_site_id(matched_by_id)
            if matched_site_id:
                return matched_site_id

    if site_name:
        matched_by_name = _match_network_site(local_sites, site_name)
        if matched_by_name is not None:
            matched_site_id = _extract_site_id(matched_by_name)
            if matched_site_id:
                return matched_site_id

    if len(local_sites) == 1:
        only_site_id = _extract_site_id(local_sites[0])
        if only_site_id:
            return only_site_id

    if explicit_site_id:
        raise RuntimeError(
            f"'{explicit_site_id}' did not match a local UniFi Network site on the selected console. Use list_network_sites to find the correct local site id."
        )
    if site_name:
        raise RuntimeError(f"No local UniFi Network site matched '{site_name}'. Use list_network_sites first.")
    raise RuntimeError("site_id is required unless the selected console exposes exactly one local site.")


def _resolve_console_id(
    base_url: str,
    api_key: str,
    arguments: dict[str, object],
    params: dict[str, str],
    *,
    site_id: str = "",
) -> str:
    explicit_console_id = _optional_str(arguments, "console_id", "") or str(params.get(DEFAULT_CONSOLE_ID_PARAM, "")).strip()
    if explicit_console_id:
        return explicit_console_id

    resolved_site_id = site_id or _optional_str(arguments, "site_id", "") or str(params.get(DEFAULT_SITE_ID_PARAM, "")).strip()
    if resolved_site_id or _optional_str(arguments, "site_name", ""):
        sites_payload = _request_json("GET", _build_url(base_url, "/v1/sites", {"pageSize": 200}), api_key)
        sites = _extract_items(sites_payload)
        if not resolved_site_id:
            site_name = _optional_str(arguments, "site_name", "")
            matched = _match_site_by_name(sites, site_name)
        else:
            matched = next((site for site in sites if _extract_site_id(site) == resolved_site_id), None)
        console_id = _extract_site_console_id(matched)
        if console_id:
            return console_id

    hosts_payload = _request_json("GET", _build_url(base_url, "/v1/hosts", None), api_key)
    hosts = _extract_items(hosts_payload)
    if len(hosts) == 1:
        host_id = _extract_host_id(hosts[0])
        if host_id:
            return host_id

    raise RuntimeError(
        "console_id is required unless a default console is configured, the selected site has a linked console, or your account exposes exactly one host. Use list_sites or list_hosts first."
    )


def _request_json(
    method: str,
    url: str,
    api_key: str,
    payload: Mapping[str, object] | None = None,
) -> dict[str, object] | list[object]:
    body: bytes | None = None
    headers: dict[str, str] = {
        "Accept": "application/json",
        "X-API-Key": api_key,
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url=url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return {}
        loaded = json.loads(raw)
        if isinstance(loaded, (dict, list)):
            return loaded
        return {"value": str(loaded)}


def _cloud_base_url(params: dict[str, str]) -> str:
    raw = str(params.get(CLOUD_BASE_URL_PARAM, "") or "").strip() or DEFAULT_CLOUD_BASE_URL
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "https://" + raw
    return raw.rstrip("/")


def _required_api_key(params: dict[str, str]) -> str:
    return str(params.get(API_KEY_PARAM, "") or "").strip()


def _build_url(base_url: str, path: str, query: Mapping[str, object] | None) -> str:
    normalized_path = path if path.startswith("/") else "/" + path
    url = base_url.rstrip("/") + normalized_path
    encoded_query = _encode_query(query)
    if encoded_query:
        return f"{url}?{encoded_query}"
    return url


def _encode_query(query: Mapping[str, object] | None) -> str:
    if not query:
        return ""
    items: list[tuple[str, str]] = []
    for key, value in query.items():
        if value is None:
            continue
        key_text = str(key).strip()
        if not key_text:
            continue
        if isinstance(value, bool):
            items.append((key_text, "true" if value else "false"))
            continue
        if isinstance(value, (int, float)):
            items.append((key_text, str(value)))
            continue
        if isinstance(value, str):
            if value.strip():
                items.append((key_text, value.strip()))
            continue
        if isinstance(value, list):
            for entry in value:
                if entry is None:
                    continue
                entry_text = str(entry).strip()
                if entry_text:
                    items.append((key_text, entry_text))
    return parse.urlencode(items, doseq=True)


def _normalize_site_manager_path(path: str) -> str:
    normalized = path.strip()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if not normalized.startswith("/v1/") and normalized != "/v1":
        raise RuntimeError("Site Manager path must start with /v1.")
    return normalized


def _normalize_proxy_path(path: str) -> str:
    normalized = path.strip()
    if normalized.startswith("/"):
        normalized = normalized[1:]
    if normalized.startswith("proxy/"):
        return normalized
    return f"{CONNECTOR_NETWORK_PREFIX}/{normalized}"


def _extract_items(payload: dict[str, object] | list[object]) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    if isinstance(data, dict):
        return [data]
    items = payload.get("items")
    if isinstance(items, list):
        return [entry for entry in items if isinstance(entry, dict)]
    return []


def _extract_next_token(payload: dict[str, object] | list[object]) -> str:
    if not isinstance(payload, dict):
        return ""
    token = payload.get("nextToken")
    return str(token).strip() if isinstance(token, str) else ""


def _summarize_sites(items: list[dict[str, object]]) -> list[dict[str, object]]:
    summarized: list[dict[str, object]] = []
    for item in items[:_MAX_RESULT_ITEMS]:
        summarized.append(
            {
                "id": _extract_site_id(item),
                "name": _extract_site_name(item),
                "console_id": _extract_site_console_id(item),
                "raw": item,
            }
        )
    return summarized


def _summarize_hosts(items: list[dict[str, object]]) -> list[dict[str, object]]:
    summarized: list[dict[str, object]] = []
    for item in items[:_MAX_RESULT_ITEMS]:
        summarized.append(
            {
                "id": _extract_host_id(item),
                "name": _extract_named_field(item, ("name", "displayName", "hostname")),
                "ip": _extract_named_field(item, ("ipAddress", "ip", "host")),
                "type": _extract_named_field(item, ("type", "deviceType", "product")),
                "raw": item,
            }
        )
    return summarized


def _extract_site_id(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("id", "siteId", "site_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_site_name(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    direct = _extract_named_field(payload, ("name", "displayName", "siteName", "desc"))
    if direct:
        return direct
    meta = payload.get("meta")
    if isinstance(meta, dict):
        return _extract_named_field(meta, ("name", "displayName"))
    return ""


def _extract_site_console_id(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("hostId", "host_id", "consoleId", "console_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    meta = payload.get("meta")
    if isinstance(meta, dict):
        for key in ("hostId", "consoleId"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_host_id(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("id", "hostId", "consoleId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_named_field(payload: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _match_site_by_name(sites: list[dict[str, object]], site_name: str) -> dict[str, object] | None:
    query = site_name.strip().lower()
    if not query:
        return None

    exact_matches = [site for site in sites if _extract_site_name(site).strip().lower() == query]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise RuntimeError(f"Multiple UniFi sites exactly matched '{site_name}'. Use site_id instead.")

    partial_matches = [site for site in sites if query in _extract_site_name(site).strip().lower()]
    if len(partial_matches) == 1:
        return partial_matches[0]
    if len(partial_matches) > 1:
        raise RuntimeError(f"Multiple UniFi sites matched '{site_name}'. Use site_id instead.")
    return None


def _validate_metric_type(metric_type: str) -> str:
    normalized = metric_type.strip().lower()
    if normalized not in {"5m", "1h"}:
        raise RuntimeError("type must be either '5m' or '1h'.")
    return normalized


def _isp_metric_query(arguments: dict[str, object]) -> dict[str, object]:
    duration = _optional_str(arguments, "duration", "")
    begin_timestamp = _optional_str(arguments, "begin_timestamp", "")
    end_timestamp = _optional_str(arguments, "end_timestamp", "")
    if duration and (begin_timestamp or end_timestamp):
        raise RuntimeError("duration cannot be combined with begin_timestamp or end_timestamp.")

    query: dict[str, object] = {}
    if duration:
        query["duration"] = duration
    if begin_timestamp:
        query["beginTimestamp"] = begin_timestamp
    if end_timestamp:
        query["endTimestamp"] = end_timestamp
    return query


def _extract_metrics_from_query_payload(payload: dict[str, object] | list[object]) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            metrics = data.get("metrics")
            if isinstance(metrics, list):
                return [entry for entry in metrics if isinstance(entry, dict)]
    return _extract_items(payload)


def _build_wan_summary_request_sites(
    base_url: str,
    api_key: str,
    arguments: dict[str, object],
    params: dict[str, str],
) -> list[dict[str, object]]:
    explicit_sites = arguments.get("sites")
    request_sites: list[dict[str, object]] = []
    begin_timestamp = _optional_str(arguments, "begin_timestamp", "")
    end_timestamp = _optional_str(arguments, "end_timestamp", "")

    if isinstance(explicit_sites, list) and explicit_sites:
        for entry in explicit_sites:
            if not isinstance(entry, dict):
                continue
            site_payload: dict[str, object] = {}
            site_id = _optional_str(entry, "site_id", "")
            site_name = _optional_str(entry, "site_name", "")
            if site_id:
                site_payload["siteId"] = site_id
            elif site_name:
                site_payload["siteId"] = _resolve_site_id(base_url, api_key, {"site_name": site_name}, params)
            else:
                raise RuntimeError("Each WAN summary site entry needs site_id or site_name.")

            host_id = _optional_str(entry, "host_id", "")
            if not host_id:
                resolution_args: dict[str, object] = {"site_id": str(site_payload["siteId"])}
                site_name_value = _optional_str(entry, "site_name", "")
                if site_name_value:
                    resolution_args["site_name"] = site_name_value
                host_id = _resolve_console_id(base_url, api_key, resolution_args, params, site_id=str(site_payload["siteId"]))
            site_payload["hostId"] = host_id

            if begin_timestamp:
                site_payload["beginTimestamp"] = begin_timestamp
            if end_timestamp:
                site_payload["endTimestamp"] = end_timestamp
            request_sites.append(site_payload)

    if request_sites:
        return request_sites

    site_id = _optional_str(arguments, "site_id", "")
    site_name = _optional_str(arguments, "site_name", "")
    host_id = _optional_str(arguments, "host_id", "")
    if not site_id and not site_name:
        site_id = str(params.get(DEFAULT_SITE_ID_PARAM, "")).strip()
    resolved_site_id = site_id or _resolve_site_id(base_url, api_key, {"site_name": site_name}, params)
    resolved_host_id = host_id or _resolve_console_id(base_url, api_key, {"site_id": resolved_site_id, "site_name": site_name}, params, site_id=resolved_site_id)

    site_payload = {
        "siteId": resolved_site_id,
        "hostId": resolved_host_id,
    }
    if begin_timestamp:
        site_payload["beginTimestamp"] = begin_timestamp
    if end_timestamp:
        site_payload["endTimestamp"] = end_timestamp
    return [site_payload]


def _summarize_metric_entry(entry: dict[str, object]) -> dict[str, object]:
    periods = entry.get("periods")
    period_list = [period for period in periods if isinstance(period, dict)] if isinstance(periods, list) else []
    latest_period = period_list[-1] if period_list else {}
    latest_time = str(latest_period.get("metricTime", "")).strip() if isinstance(latest_period, dict) else ""
    wan_data = latest_period.get("data") if isinstance(latest_period, dict) else None
    wan_metrics = wan_data.get("wan") if isinstance(wan_data, dict) else None
    wan_map = wan_metrics if isinstance(wan_metrics, dict) else {}

    packet_loss = _coerce_float(wan_map.get("packetLoss"))
    uptime = _coerce_float(wan_map.get("uptime"))
    downtime = _coerce_float(wan_map.get("downtime"))
    avg_latency = _coerce_float(wan_map.get("avgLatency"))
    max_latency = _coerce_float(wan_map.get("maxLatency"))
    download_kbps = _coerce_float(wan_map.get("download_kbps"))
    upload_kbps = _coerce_float(wan_map.get("upload_kbps"))

    health = "healthy"
    reason = "Recent WAN metrics look normal."
    if not period_list:
        health = "no_data"
        reason = "No ISP metric periods returned for this site."
    elif downtime > 0 and uptime <= 0:
        health = "down"
        reason = "WAN shows downtime with zero uptime in the latest metric period."
    elif packet_loss >= 50 or avg_latency >= 250 or downtime > 0:
        health = "degraded"
        reason = "WAN shows packet loss, high latency, or downtime in the latest metric period."
    elif packet_loss > 0 or max_latency >= 200:
        health = "warning"
        reason = "WAN shows intermittent packet loss or latency spikes."

    return {
        "site_id": _extract_named_field(entry, ("siteId", "site_id")),
        "host_id": _extract_named_field(entry, ("hostId", "host_id")),
        "metric_type": _extract_named_field(entry, ("metricType", "metric_type")),
        "latest_metric_time": latest_time,
        "health": health,
        "reason": reason,
        "uptime": uptime,
        "downtime": downtime,
        "packet_loss": packet_loss,
        "avg_latency": avg_latency,
        "max_latency": max_latency,
        "download_kbps": download_kbps,
        "upload_kbps": upload_kbps,
        "isp_name": _extract_named_field(wan_map, ("ispName", "isp_name")),
        "isp_asn": _extract_named_field(wan_map, ("ispAsn", "isp_asn")),
        "period_count": len(period_list),
        "latest_period": latest_period if isinstance(latest_period, dict) else {},
    }


def _summarize_network_inventory(networks: list[object]) -> list[dict[str, object]]:
    summarized: list[dict[str, object]] = []
    for entry in networks[:_MAX_RESULT_ITEMS]:
        if not isinstance(entry, dict):
            continue
        summarized.append(
            {
                "id": _extract_named_field(entry, ("id",)),
                "name": _extract_named_field(entry, ("name",)),
                "enabled": bool(entry.get("enabled")),
                "default": bool(entry.get("default")),
                "vlan_id": entry.get("vlanId"),
                "management": _extract_named_field(entry, ("management",)),
                "origin": _extract_named_field(entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}, ("origin",)),
            }
        )
    return summarized


def _build_wan_recommendations(
    health: str,
    wans: list[object],
    networks: list[object],
    latest_summary: dict[str, object],
) -> list[str]:
    recommendations: list[str] = []
    wan_count = len([entry for entry in wans if isinstance(entry, dict)])
    network_count = len([entry for entry in networks if isinstance(entry, dict)])
    packet_loss = _coerce_float(latest_summary.get("packet_loss"))
    avg_latency = _coerce_float(latest_summary.get("avg_latency"))

    if health == "down":
        recommendations.append("WAN metrics indicate a likely upstream outage; compare with ISP status and modem/ONT link state immediately.")
    elif health == "degraded":
        recommendations.append("WAN metrics show degradation; inspect packet loss and latency trends before rebooting network gear.")
    elif health == "warning":
        recommendations.append("WAN shows intermittent instability; watch for recurring spikes and correlate with ISP maintenance windows.")
    elif health == "no_data":
        recommendations.append("No ISP metrics were returned; verify the site-host mapping and confirm Site Manager has access to this console.")
    else:
        recommendations.append("WAN metrics look healthy; investigate LAN, DNS, policy, or client-specific causes next.")

    if wan_count == 0:
        recommendations.append("No WAN interfaces were returned for the site; verify the site/console selection and UniFi permissions.")
    elif wan_count > 1:
        recommendations.append("Multiple WAN interfaces are present; confirm whether failover or load balancing changed the expected uplink path.")

    if network_count > 0:
        recommendations.append(f"{network_count} site networks were discovered; if only one VLAN is affected, the outage is probably not a full WAN failure.")

    if packet_loss >= 50:
        recommendations.append("Packet loss is severe; capture the exact time window and compare it against ISP circuit events.")
    if avg_latency >= 250:
        recommendations.append("Latency is very high; check whether the circuit is degraded rather than fully down.")

    return recommendations


def _coerce_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


def _list_query(arguments: dict[str, object]) -> dict[str, object]:
    query: dict[str, object] = {
        "offset": _optional_int(arguments, "offset", 0, 0, 1000000),
        "limit": _optional_int(arguments, "limit", 25, 1, _LIST_PAGE_LIMIT_MAX),
    }
    filter_value = _optional_str(arguments, "filter", "")
    if filter_value:
        query["filter"] = filter_value
    return query


def _optional_query_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for key, entry in value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        if isinstance(entry, (str, int, float, bool, list)) or entry is None:
            result[key_text] = entry
    return result


def _truncate_payload_lists(payload: dict[str, object] | list[object]) -> dict[str, object] | list[object]:
    if isinstance(payload, list):
        if len(payload) <= _MAX_RESULT_ITEMS:
            return payload
        note: dict[str, object] = {"note": f"List truncated to first {_MAX_RESULT_ITEMS} items."}
        return payload[:_MAX_RESULT_ITEMS] + [note]
    if not isinstance(payload, dict):
        return payload

    result = dict(payload)
    data = result.get("data")
    if isinstance(data, list) and len(data) > _MAX_RESULT_ITEMS:
        result["data"] = data[:_MAX_RESULT_ITEMS]
        result["truncated"] = True
        result["truncated_count"] = len(data) - _MAX_RESULT_ITEMS
    return result


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Missing required argument '{key}'.")
    return value.strip()


def _required_str_from_mapping(arguments: Mapping[str, object], key: str) -> str:
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
        raw = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        raw = ""
    if raw:
        return raw
    return "No additional details."


def _url_error_reason(exc: error.URLError) -> str:
    reason = exc.reason
    if isinstance(reason, str):
        return reason
    return str(reason)
