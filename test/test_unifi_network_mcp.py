"""Standalone smoke test for the UniFi Network MCP.

Runs in two modes:
1) default mocked mode with no credentials required
2) optional live mode when UNIFI_API_KEY is provided
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any


MOCK_UNIFI_CREDENTIAL = "mock-unifi-credential"


async def _run_mocked_test() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import app.mcps.unifi_network as unifi_module  # pylint: disable=import-outside-toplevel

    plugin = unifi_module.UniFiNetworkMCP()
    tool_ids = {tool.id for tool in plugin.tool_specs()}
    expected = {
        "list_sites",
        "list_hosts",
        "list_network_sites",
        "list_devices",
        "list_clients",
        "list_networks",
        "list_wans",
        "get_isp_metrics",
        "query_isp_metrics",
        "summarize_wan_health",
        "debug_wan_outage",
        "site_manager_get",
        "proxy_get",
    }
    missing = sorted(expected - tool_ids)
    if missing:
        raise RuntimeError(f"UniFi MCP missing expected tools: {missing}")

    original_request_json = unifi_module._request_json

    def fake_request_json(method: str, url: str, api_key: str, payload: Any = None) -> dict[str, object] | list[object]:
        if api_key != MOCK_UNIFI_CREDENTIAL:
            raise RuntimeError(f"Unexpected API key in mock: {api_key}")
        if method == "GET" and url.endswith("/v1/sites?pageSize=1"):
            return {"data": [{"id": "site-1", "name": "Home", "hostId": "host-1"}]}
        if method == "GET" and url.endswith("/v1/sites"):
            return {"data": [{"id": "site-1", "name": "Home", "hostId": "host-1"}]}
        if method == "GET" and "/v1/sites?pageSize=200" in url:
            return {"data": [{"id": "site-1", "name": "Home", "hostId": "host-1"}]}
        if method == "GET" and url.endswith("/v1/hosts"):
            return {"data": [{"id": "host-1", "name": "UDM Pro", "ipAddress": "192.168.1.1", "type": "udmpro"}]}
        if method == "GET" and "/proxy/network/integration/v1/sites/site-1/wans?" in url:
            return {"data": [{"id": "wan-1", "name": "WAN 1"}]}
        if method == "GET" and "/proxy/network/integration/v1/sites/site-1/networks?" in url:
            return {
                "data": [
                    {"id": "net-1", "name": "Default", "enabled": True, "default": True, "vlanId": 1, "management": "GATEWAY", "metadata": {"origin": "user"}}
                ]
            }
        if method == "POST" and "/v1/isp-metrics/5m/query" in url:
            return {
                "data": {
                    "metrics": [
                        {
                            "siteId": "site-1",
                            "hostId": "host-1",
                            "metricType": "5m",
                            "periods": [
                                {
                                    "metricTime": "2026-04-21T12:00:00Z",
                                    "data": {
                                        "wan": {
                                            "avgLatency": 320,
                                            "maxLatency": 480,
                                            "packetLoss": 67,
                                            "uptime": 0,
                                            "downtime": 300,
                                            "download_kbps": 0,
                                            "upload_kbps": 0,
                                            "ispName": "ExampleISP",
                                            "ispAsn": "AS64500",
                                        }
                                    },
                                }
                            ],
                        }
                    ],
                    "status": "success",
                    "message": "ok",
                }
            }
        raise RuntimeError(f"Unhandled mock UniFi request: {method} {url} payload={payload}")

    unifi_module._request_json = fake_request_json
    try:
        ok, detail = await plugin.verify({"api_key": MOCK_UNIFI_CREDENTIAL})
        if not ok:
            raise RuntimeError(f"Expected mocked verify to succeed. Detail: {detail}")

        sites = await plugin.call_tool("list_sites", {}, {"api_key": MOCK_UNIFI_CREDENTIAL})
        if sites.get("count") != 1:
            raise RuntimeError(f"Expected one mocked site. Got: {sites}")

        outage = await plugin.call_tool(
            "debug_wan_outage",
            {"type": "5m", "site_name": "Home"},
            {"api_key": MOCK_UNIFI_CREDENTIAL},
        )
        if outage.get("health") != "down":
            raise RuntimeError(f"Expected WAN outage health=down. Got: {outage}")
        recommendations = outage.get("recommendations")
        if not isinstance(recommendations, list) or not recommendations:
            raise RuntimeError(f"Expected WAN recommendations. Got: {outage}")
    finally:
        unifi_module._request_json = original_request_json

    print("PASS: Mocked UniFi MCP smoke test succeeded.")


async def _run_live_test() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.mcps.unifi_network import UniFiNetworkMCP  # pylint: disable=import-outside-toplevel

    api_key = os.environ.get("UNIFI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("UNIFI_API_KEY is required for live mode.")

    params: dict[str, str] = {"api_key": api_key}
    for env_name, param_name in (
        ("UNIFI_CLOUD_BASE_URL", "cloud_base_url"),
        ("UNIFI_SITE_ID", "default_site_id"),
        ("UNIFI_CONSOLE_ID", "default_console_id"),
    ):
        value = os.environ.get(env_name, "").strip()
        if value:
            params[param_name] = value

    plugin = UniFiNetworkMCP()
    ok, detail = await plugin.verify(params)
    if not ok:
        raise RuntimeError(f"Live verify failed: {detail}")
    print(f"VERIFY OK: {detail}")

    sites = await plugin.call_tool("list_sites", {"page_size": 20}, params)
    print(f"LIST SITES OK: {sites.get('count')} site(s)")

    site_name = os.environ.get("UNIFI_SITE_NAME", "").strip()
    metric_type = os.environ.get("UNIFI_METRIC_TYPE", "5m").strip() or "5m"
    if params.get("default_site_id") or site_name:
        outage_args: dict[str, object] = {"type": metric_type}
        if site_name:
            outage_args["site_name"] = site_name
        outage = await plugin.call_tool("debug_wan_outage", outage_args, params)
        print(f"WAN DEBUG OK: health={outage.get('health')} site={outage.get('site_id')}")
    else:
        print("WAN DEBUG SKIPPED: set UNIFI_SITE_ID or UNIFI_SITE_NAME for targeted live WAN testing.")


async def main() -> None:
    live_mode = os.environ.get("UNIFI_LIVE_TEST", "").strip().lower() in {"1", "true", "yes"}
    if live_mode:
        await _run_live_test()
        return
    await _run_mocked_test()


if __name__ == "__main__":
    asyncio.run(main())
