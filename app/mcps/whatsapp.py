"""WhatsApp MCP for orchestrator-controlled outbound messaging."""

from __future__ import annotations

import difflib
import time

from typing import Any

from .base import MCPPlugin, McpConfigField, McpToolSpec
from app.integrations.whatsapp.sidecar_manager import (
    connect,
    get_message_history,
    list_contacts,
    normalize_phone_number,
    parse_allowlist,
    send_message,
    status,
)


# ---------------------------------------------------------------------------
# Contacts TTL cache (shared across tool calls, avoids re-fetching each time)
# ---------------------------------------------------------------------------

_contacts_cache: list[dict[str, str]] = []
_contacts_cache_ts: float = 0.0
_CONTACTS_CACHE_TTL = 30.0  # seconds


async def _get_contacts_cached() -> list[dict[str, str]]:
    """Return the contacts list, using a TTL cache to avoid hammering the sidecar."""
    global _contacts_cache, _contacts_cache_ts
    now = time.monotonic()
    if _contacts_cache and (now - _contacts_cache_ts) < _CONTACTS_CACHE_TTL:
        return _contacts_cache
    try:
        _contacts_cache = await list_contacts()
    except Exception:
        # If the live fetch fails, return the stale cache (if any).
        if _contacts_cache:
            return _contacts_cache
        _contacts_cache = []
    _contacts_cache_ts = now
    return _contacts_cache


# ---------------------------------------------------------------------------
# MCP Plugin
# ---------------------------------------------------------------------------


class WhatsAppMCP(MCPPlugin):
    mcp_id = "whatsapp"
    display_name = "WhatsApp"
    description = "Outbound WhatsApp messaging for allowlisted numbers and automation prompt configuration."
    default_enabled = False
    config_fields: list[McpConfigField] = [
        McpConfigField(
            id="auto_answer",
            label="Auto answer",
            type="checkbox",
            required=False,
            description="When enabled, trigger-allowlisted inbound WhatsApp messages trigger automatic replies using the automation prompt. Does not affect manual send/read tools.",
        ),
        McpConfigField(
            id="quote_latest_reply_message",
            label="Quote latest inbound message",
            type="checkbox",
            required=False,
            description="When enabled, WhatsApp auto-answer replies quote the latest inbound WhatsApp message they are answering to.",
        ),
        McpConfigField(
            id="auto_reply_delay_min_seconds",
            label="Auto-reply min delay (s)",
            type="text",
            required=False,
            placeholder="10",
            description="Minimum random delay before sending an auto-answer reply (trigger flow only, not manual send/read).",
        ),
        McpConfigField(
            id="auto_reply_delay_max_seconds",
            label="Auto-reply max delay (s)",
            type="text",
            required=False,
            placeholder="60",
            description="Maximum random delay before sending an auto-answer reply (trigger flow only, not manual send/read).",
        ),
        McpConfigField(
            id="automation_prompt",
            label="Automation prompt",
            type="textarea",
            required=False,
            placeholder="Instruction used when auto answer is enabled and allowlisted inbound messages are bridged to Gateway.",
        ),
        McpConfigField(
            id="allowed_numbers_send",
            label="Allowed numbers (Send / Read)",
            type="textarea",
            required=True,
            placeholder="00491234567;00491987654",
            description="Contacts the system is allowed to proactively send messages to and read recent history from.",
        ),
        McpConfigField(
            id="allowed_numbers_receive",
            label="Allowed numbers (Trigger)",
            type="textarea",
            required=False,
            placeholder="00491234567;00491987654",
            description="Contacts that can trigger automated responses when Auto Answer is enabled.",
        ),
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="whatsapp_find_contact_number",
                label="WhatsApp Find Contact Number",
                description="Lists all allowlisted WhatsApp contacts from the send allow list, or searches them by name.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name_query": {"type": "string", "description": "Optional name to search for. Leave empty to return all allowed contacts."},
                    },
                },
            ),
            McpToolSpec(
                id="whatsapp_send_message",
                label="WhatsApp Send Message",
                description="Sends a WhatsApp message to an allowlisted number.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to_number": {"type": "string", "minLength": 1},
                        "text": {"type": "string", "minLength": 1},
                    },
                    "required": ["text"],
                },
            ),
            McpToolSpec(
                id="whatsapp_read_recent_messages",
                label="WhatsApp Read Recent Messages",
                description="Reads the most recent messages for an allowlisted contact by best name/number match.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "contact_query": {
                            "type": "string",
                            "description": "Contact name or number to match against allowlisted send/read contacts.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 30,
                            "description": "How many most recent messages to read (1-30, default 10).",
                        },
                    },
                },
            ),
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        try:
            connect_result = await connect()
        except Exception as exc:
            return False, f"WhatsApp sidecar failed to start: {exc}"

        # Use the state from the connect response directly (avoids a redundant status call).
        state = str(connect_result.get("status", "")).strip().lower()
        if not state:
            # Fallback: explicit status call if connect did not return state.
            try:
                current = await status()
                state = str(current.get("status", "")).strip().lower()
            except Exception as exc:
                return False, f"WhatsApp sidecar status check failed: {exc}"

        allowlist_send = parse_allowlist(params.get("allowed_numbers_send", ""))
        allowlist_recv = parse_allowlist(params.get("allowed_numbers_receive", ""))
        allowlist = allowlist_send | allowlist_recv

        if state in {"error", "auth_failure"}:
            return False, "WhatsApp failed to initialize. Reconnect and scan the QR code again."
        if state == "disconnected":
            return False, "WhatsApp is disconnected. Click Connect to scan the QR code."
        if state == "ready":
            if not allowlist:
                return True, "WhatsApp connected. Select at least one Allowed number from synced contacts."
            return True, "WhatsApp connected and ready."
        if state == "authenticated":
            return True, "WhatsApp authenticated. Waiting for contact sync; reopen Connect if contacts stay empty."
        if state == "qr":
            return True, "WhatsApp sidecar reachable. Scan the QR code in Connect."
        return True, f"WhatsApp sidecar reachable. Current state: {state or 'unknown'}"

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id == "whatsapp_find_contact_number":
            return await _discover_allowlisted_numbers(arguments, params)

        if tool_id == "whatsapp_read_recent_messages":
            return await _read_recent_messages(arguments, params)

        if tool_id != "whatsapp_send_message":
            raise RuntimeError(f"Unsupported WhatsApp tool: {tool_id}")

        text = str(arguments.get("text", "")).strip()
        if not text:
            raise RuntimeError("text is required.")

        # Pre-check: verify WhatsApp is ready before attempting to send.
        try:
            current_status = await status(start_if_needed=False)
            wa_state = str(current_status.get("status", "")).strip().lower()
            if wa_state != "ready":
                raise RuntimeError(
                    f"WhatsApp is not ready (current state: {wa_state}). "
                    "Use the Connect button in the WhatsApp MCP settings to re-establish the connection."
                )
        except RuntimeError:
            raise
        except Exception:
            pass  # Non-critical — the send call will surface the real error.

        allowlist = parse_allowlist(params.get("allowed_numbers_send", ""))
        raw_target = str(arguments.get("to_number", "")).strip()
        to_number = normalize_phone_number(raw_target)

        if not to_number and len(allowlist) == 1:
            to_number = next(iter(allowlist))

        if not to_number and raw_target:
            resolved, ambiguous = await _resolve_allowlisted_contact(raw_target, allowlist)
            to_number = resolved
            if not to_number and ambiguous:
                suggestions = ", ".join(f"{e['name']} ({e['number']})" for e in ambiguous)
                raise RuntimeError(
                    f"Multiple contacts match '{raw_target}'. Please specify an exact number. "
                    f"Candidates: {suggestions}"
                )

        if not to_number:
            raise RuntimeError("to_number is required (or implied by a single allowlisted contact).")

        if to_number not in allowlist:
            raise RuntimeError("Target number is not allowlisted for WhatsApp MCP.")

        payload = await send_message(to_number, text)
        return {
            "status": "sent",
            "to_number": to_number,
            "text": text,
            "result": payload,
        }

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del tool_id
        allowlist = sorted(parse_allowlist(params.get("allowed_numbers_send", "")))
        if not allowlist:
            return "Only send messages to explicit allowlisted numbers."
        if len(allowlist) == 1:
            return (
                "Only send messages to explicit allowlisted numbers. "
                f"Exactly one number is allowlisted ({allowlist[0]}), so you may omit to_number and use that target."
            )
        return (
            "Only send messages to explicit allowlisted numbers. "
            f"Allowed numbers: {', '.join(allowlist)}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_allowlisted_contact(target: str, allowlist: set[str]) -> tuple[str, list[dict[str, str]]]:
    """Resolve a contact target to a number. Returns (number, ambiguous_candidates)."""
    matches = await _find_allowlisted_contacts(target, allowlist)
    if len(matches) == 1:
        return matches[0]["number"], []
    if len(matches) > 1:
        return "", matches[:5]
    return "", []


async def _read_recent_messages(arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    allowlist = parse_allowlist(params.get("allowed_numbers_send", ""))
    if not allowlist:
        raise RuntimeError("No send/read contacts are allowlisted. Configure Allowed numbers (Send / Read) first.")

    contact_query = str(arguments.get("contact_query", "")).strip()
    limit = _coerce_history_limit(arguments.get("limit"), default=10)

    resolved_number, resolved_name, ambiguous_candidates = await _resolve_history_contact(contact_query, allowlist)
    if ambiguous_candidates:
        suggestions = ", ".join(f"{entry['name']} ({entry['number']})" for entry in ambiguous_candidates)
        raise RuntimeError(
            "Contact match is ambiguous. Please specify a clearer name or exact number. "
            f"Candidates: {suggestions}"
        )
    if not resolved_number:
        if contact_query:
            raise RuntimeError("No allowlisted send/read contact matched that query.")
        raise RuntimeError("contact_query is required when more than one send/read contact is allowlisted.")

    history = await get_message_history(resolved_number, limit=limit)
    messages = _normalize_history_entries(history, contact_name=resolved_name or resolved_number)
    return {
        "status": "ok",
        "contact": {
            "name": resolved_name or resolved_number,
            "number": resolved_number,
        },
        "limit": limit,
        "count": len(messages),
        "messages": messages,
    }


async def _discover_allowlisted_numbers(arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
    name_query = str(arguments.get("name_query", "")).strip()

    allowlist = parse_allowlist(params.get("allowed_numbers_send", ""))
    matches = await _find_allowlisted_contacts(name_query, allowlist)
    return {
        "status": "ok",
        "query": name_query,
        "matches": matches,
        "count": len(matches),
    }


async def _find_allowlisted_contacts(target: str, allowlist: set[str]) -> list[dict[str, str]]:
    scored = await _score_allowlisted_contacts(target, allowlist)
    return [{"name": item["name"], "number": item["number"]} for item in scored]


async def _resolve_history_contact(target: str, allowlist: set[str]) -> tuple[str, str, list[dict[str, str]]]:
    candidates = await _score_allowlisted_contacts(target, allowlist)
    if not candidates:
        return "", "", []

    if not target.strip():
        if len(candidates) == 1:
            only = candidates[0]
            return only["number"], only["name"], []
        return "", "", [{"name": item["name"], "number": item["number"]} for item in candidates[:5]]

    best = candidates[0]
    if len(candidates) >= 2:
        second = candidates[1]
        if (best["score"] - second["score"]) < 0.18:
            return "", "", [{"name": item["name"], "number": item["number"]} for item in candidates[:5]]

    return best["number"], best["name"], []


async def _score_allowlisted_contacts(target: str, allowlist: set[str]) -> list[dict[str, Any]]:
    if not allowlist:
        return []

    lowered_target = target.strip().lower()
    digit_target = normalize_phone_number(target)

    contacts = await _get_contacts_cached()

    known_contacts: list[dict[str, Any]] = []
    for entry in contacts:
        number = normalize_phone_number(str(entry.get("number", "")))
        if not number or number not in allowlist:
            continue
        name_display = str(entry.get("name", "")).strip() or number
        known_contacts.append({"name": name_display, "number": number, "score": 0.0})

    known_numbers = {c["number"] for c in known_contacts}
    for num in allowlist:
        if num not in known_numbers:
            known_contacts.append({"name": num, "number": num, "score": 0.0})

    if not lowered_target:
        known_contacts.sort(key=lambda item: (item["name"].lower(), item["number"]))
        return known_contacts

    tokens = _tokenize_contact_query(lowered_target)
    for entry in known_contacts:
        name_display = str(entry.get("name", ""))
        number = entry["number"]
        name = name_display.lower()
        score = 0.0

        if lowered_target == name:
            score += 1.4
        elif lowered_target in name:
            score += 1.0

        if digit_target and digit_target == number:
            score += 1.8
        elif digit_target and number.endswith(digit_target):
            score += 1.2
        elif digit_target and digit_target in number:
            score += 0.7

        if tokens:
            for token in tokens:
                if token and token in name:
                    score += 0.15

        score += 0.6 * difflib.SequenceMatcher(None, lowered_target, name).ratio()
        if digit_target:
            score += 0.3 * difflib.SequenceMatcher(None, digit_target, number).ratio()

        entry["score"] = round(score, 4)

    known_contacts.sort(key=lambda item: (_score_value(item.get("score")), item["name"].lower(), item["number"]), reverse=True)

    threshold = 0.45
    filtered = [item for item in known_contacts if _score_value(item.get("score")) >= threshold]

    deduped: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for match in filtered:
        number = match.get("number", "")
        if not number or number in seen_numbers:
            continue
        seen_numbers.add(number)
        deduped.append(match)
    return deduped


def _tokenize_contact_query(text: str) -> list[str]:
    token_chars: list[str] = []
    tokens: list[str] = []
    for char in text.lower():
        if char.isalnum():
            token_chars.append(char)
            continue
        if token_chars:
            tokens.append("".join(token_chars))
            token_chars = []
    if token_chars:
        tokens.append("".join(token_chars))
    return tokens


def _score_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _coerce_history_limit(raw_limit: object, *, default: int) -> int:
    if isinstance(raw_limit, bool):
        return default
    try:
        parsed = int(str(raw_limit).strip())
    except Exception:
        return default
    return max(1, min(parsed, 30))


def _normalize_history_entries(history: list[dict[str, object]], *, contact_name: str) -> list[dict[str, object]]:
    ordered = sorted(
        [item for item in history if isinstance(item, dict)],
        key=lambda item: _history_timestamp(item.get("timestamp")),
    )
    normalized: list[dict[str, object]] = []
    for item in ordered:
        author = _history_author_label(bool(item.get("from_me")), contact_name)
        body = str(item.get("body", "")).strip()
        has_image = bool(item.get("has_image"))
        if body:
            prefixed_text = f"{author}: {body}"
        elif has_image:
            prefixed_text = f"{author}: [image]"
        else:
            prefixed_text = f"{author}:"
        normalized.append(
            {
                "id": str(item.get("id", "")).strip(),
                "role": "assistant" if bool(item.get("from_me")) else "user",
                "author": author,
                "text": prefixed_text,
                "timestamp": _history_timestamp(item.get("timestamp")),
                "has_image": has_image,
                "type": str(item.get("type", "")).strip(),
            }
        )
    return normalized


def _history_author_label(from_me: bool, contact_name: str) -> str:
    if from_me:
        return "user"
    cleaned_contact_name = str(contact_name).strip()
    return cleaned_contact_name or "contact"


def _history_timestamp(raw_value: object) -> int:
    if isinstance(raw_value, (int, float)):
        return int(raw_value)
    if isinstance(raw_value, str):
        try:
            return int(raw_value)
        except ValueError:
            return 0
    return 0
