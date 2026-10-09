"""User-authorized plain-text report delivery via configured SMTP."""

from typing import Any

from core.domain.types.tools import ToolSurface
from core.tool import BaseTool, SideEffectLevel
from core.tool_framework import tool
from integrations.smtp.tools.delivery import deliver_email
from integrations.smtp.tools.validation import validate_email_request


class SendSMTPEmailTool(BaseTool):
    """Send a user-requested report through the configured SMTP relay."""

    name = "send_smtp_email"
    source = "smtp"
    surfaces = (ToolSurface.CHAT, ToolSurface.ACTION)
    description = (
        "Send a plain-text report by email through the configured SMTP integration. "
        "Use only when the user explicitly requests email delivery. Supply the report "
        "and subject; omit to_address to use the configured SMTP default recipient. "
        "SMTP credentials are resolved privately. Success means the SMTP server "
        "accepted the message, not that it reached the recipient's inbox."
    )
    requires = ["smtp"]
    side_effect_level = SideEffectLevel.EXTERNAL
    requires_approval = True
    approval_reason = "Sending email transmits report contents to an external recipient."
    input_schema = {
        "type": "object",
        "properties": {
            "report": {"type": "string", "description": "Plain-text report body."},
            "subject": {"type": "string", "description": "Email subject without line breaks."},
            "to_address": {
                "type": "string",
                "description": "Optional recipient; defaults to the configured SMTP_DEFAULT_TO.",
            },
        },
        "required": ["report", "subject"],
    }
    outputs = {
        "status": "sent or failed",
        "sent": "Whether the SMTP server accepted the message",
        "error": "Sanitized failure reason when delivery failed",
        "error_type": "validation_error, configuration_error, or delivery_error",
    }

    def is_available(self, sources: dict[str, Any]) -> bool:
        smtp = sources.get("smtp") or {}
        return bool(smtp.get("host") and smtp.get("from_address"))

    def run(
        self, report: str, subject: str, to_address: str = "", **_kwargs: Any
    ) -> dict[str, Any]:
        error = validate_email_request(report, subject, to_address)
        if error:
            return {
                "status": "failed",
                "sent": False,
                "error_type": "validation_error",
                "error": error,
            }
        ok, error_type, error = deliver_email(report, subject, to_address)
        return {
            "status": "sent" if ok else "failed",
            "sent": ok,
            "error_type": error_type,
            "error": error,
        }


send_smtp_email = tool(SendSMTPEmailTool(), surfaces=(ToolSurface.CHAT, ToolSurface.ACTION))
