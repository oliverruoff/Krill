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
            id="automation_prompt",
            label="Automation prompt",
            type="textarea",
            required=False,
            placeholder="Instruction used when allowlisted inbound messages are bridged to Gateway.",
        ),
        McpConfigField(
            id="allowed_numbers",
            label="Allowed numbers",
            type="textarea",
            required=True,
            placeholder="00491234567;00491987654",
            description="Semicolon-separated allowlist used for inbound filtering and outbound restriction.",
        ),
    ]

    def tool_specs(self) -> list[McpToolSpec]:
        return [
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
        allowlist = parse_allowlist(params.get("allowed_numbers", ""))

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
        if tool_id != "whatsapp_send_message":
            raise RuntimeError(f"Unsupported WhatsApp tool: {tool_id}")

        text = str(arguments.get("text", "")).strip()
        if not text:
            raise RuntimeError("text is required.")

        allowlist = parse_allowlist(params.get("allowed_numbers", ""))
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
        allowlist = sorted(parse_allowlist(params.get("allowed_numbers", "")))
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
    lowered_target = target.strip().lower()
    if not lowered_target or not allowlist:
        return ""

    try:
        contacts = await list_contacts()
    except Exception:
        return ""

    candidates: list[str] = []
    for entry in contacts:
        number = normalize_phone_number(str(entry.get("number", "")))
        if not number or number not in allowlist:
            continue
        name = str(entry.get("name", "")).strip().lower()
        if not name:
            continue
        if name == lowered_target or lowered_target in name:
            candidates.append(number)

    if len(candidates) == 1:
        return candidates[0]
    return ""
