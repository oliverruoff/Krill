"""Brave Search MCP plugin providing a web search tool and token verification."""

import asyncio
import json
from urllib import error, parse, request

from .base import MCPPlugin, McpConfigField, McpToolSpec


class BraveSearchMCP(MCPPlugin):
    mcp_id = "brave_search"
    display_name = "Brave Search"
    description = "Web search tool using Brave Search API."
    config_fields = [
        McpConfigField(
            id="api_key",
            label="API Key",
            type="password",
            required=True,
            placeholder="BSA...",
            description="Create key at api.search.brave.com",
        )
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="web_search",
                label="Web Search",
                description="Searches the web and returns top results.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "count": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        api_key = params.get("api_key", "").strip()
        if not api_key:
            return False, "Brave Search API key is required."

        try:
            await asyncio.to_thread(_search_brave, api_key, "health check", 1)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                return False, "Brave Search rejected the API key."
            return False, f"Brave Search verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting Brave Search."
        except Exception:
            return False, "Unexpected error while verifying Brave Search API key."

        return True, "Brave Search API key verified."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id != "web_search":
            raise RuntimeError(f"Unsupported Brave Search tool: {tool_id}")

        api_key = params.get("api_key", "").strip()
        if not api_key:
            raise RuntimeError("Brave Search API key is missing.")

        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RuntimeError("Brave Search tool requires a non-empty 'query'.")

        count = arguments.get("count")
        result_count = 5
        if isinstance(count, int):
            result_count = max(1, min(10, count))

        try:
            payload = await asyncio.to_thread(_search_brave, api_key, query.strip(), result_count)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"Brave Search request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting Brave Search.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting Brave Search.") from exc

        return _normalize_search_payload(payload)


def _search_brave(api_key: str, query: str, count: int) -> dict[str, object]:
    encoded_query = parse.quote(query)
    url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count={count}"
    req = request.Request(
        url=url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )

    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_search_payload(payload: dict[str, object]) -> dict[str, object]:
    web = payload.get("web")
    raw_results = web.get("results") if isinstance(web, dict) else []
    if not isinstance(raw_results, list):
        raw_results = []

    results: list[dict[str, str]] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue

        title = entry.get("title")
        url = entry.get("url")
        description = entry.get("description")
        profile = entry.get("profile")
        if not isinstance(description, str) and isinstance(profile, dict):
            profile_description = profile.get("long_name")
            if isinstance(profile_description, str):
                description = profile_description

        results.append(
            {
                "title": title.strip() if isinstance(title, str) else "",
                "url": url.strip() if isinstance(url, str) else "",
                "snippet": description.strip() if isinstance(description, str) else "",
            }
        )

    return {
        "query": payload.get("query", {}),
        "results": results,
    }


def _safe_read_error(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return "No additional details."
