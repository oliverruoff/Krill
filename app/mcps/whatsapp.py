"""WhatsApp MCP for orchestrator-controlled outbound messaging."""

from __future__ import annotations

from .base import MCPPlugin, McpConfigField, McpToolSpec
from app.integrations.whatsapp.sidecar_manager import connect, normalize_phone_number, parse_allowlist, send_message, status


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
                        "to_number": {"type": "string", "minLength": 5},
                        "text": {"type": "string", "minLength": 1},
                    },
                    "required": ["to_number", "text"],
                },
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        allowlist = parse_allowlist(params.get("allowed_numbers", ""))
        if not allowlist:
            return False, "At least one allowed WhatsApp number is required."
        await connect()
        current = await status()
        state = str(current.get("status", "")).strip().lower()
        if state == "ready":
            return True, "WhatsApp connected and ready."
        return True, f"WhatsApp sidecar reachable. Current state: {state or 'unknown'}"

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id != "whatsapp_send_message":
            raise RuntimeError(f"Unsupported WhatsApp tool: {tool_id}")

        to_number = normalize_phone_number(str(arguments.get("to_number", "")))
        text = str(arguments.get("text", "")).strip()
        if not to_number:
            raise RuntimeError("to_number is required.")
        if not text:
            raise RuntimeError("text is required.")

        allowlist = parse_allowlist(params.get("allowed_numbers", ""))
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
        del tool_id, params
        return "Only send messages to explicit allowlisted numbers."
