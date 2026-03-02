"""WhatsApp MCP for orchestrator-controlled outbound messaging."""

from __future__ import annotations

from .base import MCPPlugin, McpConfigField, McpToolSpec
from app.integrations.whatsapp.sidecar_manager import (
    connect,
    list_contacts,
    normalize_phone_number,
    parse_allowlist,
    send_message,
    status,
)


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
            description="When enabled, allowlisted inbound WhatsApp messages trigger automatic replies using the automation prompt.",
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
            label="Allowed numbers (Send)",
            type="textarea",
            required=True,
            placeholder="00491234567;00491987654",
            description="Contacts the system is allowed to proactively send messages to.",
        ),
        McpConfigField(
            id="allowed_numbers_receive",
            label="Allowed numbers (Receive)",
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
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        await connect()
        current = await status()
        state = str(current.get("status", "")).strip().lower()
        allowlist_send = parse_allowlist(params.get("allowed_numbers_send", ""))
        allowlist_recv = parse_allowlist(params.get("allowed_numbers_receive", ""))
        allowlist = allowlist_send | allowlist_recv

        if state in {"error", "auth_failure"}:
            return False, "WhatsApp failed to initialize. Reconnect and scan the QR code again."
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

        if tool_id != "whatsapp_send_message":
            raise RuntimeError(f"Unsupported WhatsApp tool: {tool_id}")

        text = str(arguments.get("text", "")).strip()
        if not text:
            raise RuntimeError("text is required.")

        allowlist = parse_allowlist(params.get("allowed_numbers_send", ""))
        raw_target = str(arguments.get("to_number", "")).strip()
        to_number = normalize_phone_number(raw_target)

        if not to_number and len(allowlist) == 1:
            to_number = next(iter(allowlist))

        if not to_number and raw_target:
            to_number = await _resolve_allowlisted_contact(raw_target, allowlist)

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


async def _resolve_allowlisted_contact(target: str, allowlist: set[str]) -> str:
    matches = await _find_allowlisted_contacts(target, allowlist)
    if len(matches) == 1:
        return matches[0]["number"]
    return ""


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
    if not allowlist:
        return []

    lowered_target = target.strip().lower()

    try:
        contacts = await list_contacts()
    except Exception:
        contacts = []

    known_contacts: list[dict[str, str]] = []
    for entry in contacts:
        number = normalize_phone_number(str(entry.get("number", "")))
        if not number or number not in allowlist:
            continue
        name_display = str(entry.get("name", "")).strip() or number
        known_contacts.append({"name": name_display, "number": number})

    known_numbers = {c["number"] for c in known_contacts}
    for num in allowlist:
        if num not in known_numbers:
            known_contacts.append({"name": num, "number": num})

    if not lowered_target:
        known_contacts.sort(key=lambda item: item["name"].lower())
        return known_contacts

    exact_matches: list[dict[str, str]] = []
    partial_matches: list[dict[str, str]] = []
    for entry in known_contacts:
        name_display = entry["name"]
        number = entry["number"]
        name = name_display.lower()
        if name == lowered_target:
            exact_matches.append(entry)
        elif lowered_target in name:
            partial_matches.append(entry)

    ordered = exact_matches if exact_matches else partial_matches
    ordered.sort(key=lambda item: item["name"].lower())

    deduped: list[dict[str, str]] = []
    seen_numbers: set[str] = set()
    for match in ordered:
        number = match.get("number", "")
        if not number or number in seen_numbers:
            continue
        seen_numbers.add(number)
        deduped.append(match)
    return deduped
