"""Private SMTP configuration resolution and dispatch."""

from typing import Any

from integrations.catalog import resolve_effective_integrations
from integrations.config_models import SMTPIntegrationConfig
from integrations.smtp.delivery import send_smtp_report
from integrations.smtp.tools.validation import validate_email_request


def deliver_email(report: str, subject: str, to_address: str) -> tuple[bool, str, str]:
    entry = resolve_effective_integrations().get("smtp")
    raw_config = entry.get("config") if isinstance(entry, dict) else None
    if not isinstance(raw_config, dict):
        return False, "configuration_error", "SMTP integration is not configured."
    try:
        config = SMTPIntegrationConfig.model_validate(raw_config)
    except ValueError:
        return False, "configuration_error", "SMTP integration configuration is invalid."
    recipient = to_address.strip() or config.default_to or ""
    if not recipient:
        return False, "configuration_error", "Provide a recipient or configure SMTP_DEFAULT_TO."
    validation_error = validate_email_request(report, subject, recipient)
    if validation_error or any(
        character in config.from_address for character in ("\r", "\n", "\x00")
    ):
        return (
            False,
            "validation_error",
            validation_error or "SMTP sender contains header control characters.",
        )
    smtp_ctx: dict[str, Any] = config.model_dump()
    ok, error = send_smtp_report(
        report=report, subject=subject.strip(), smtp_ctx=smtp_ctx, to_address=recipient
    )
    return (True, "", "") if ok else (False, "delivery_error", error)
