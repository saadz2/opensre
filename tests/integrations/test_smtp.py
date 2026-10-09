"""Tests for the SMTP integration: config, catalog, verifier."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from integrations.config_models import SMTPIntegrationConfig
from integrations.smtp import classify
from integrations.smtp.verifier import verify_smtp as _verify_smtp


def test_config_accepts_starttls_defaults() -> None:
    config = SMTPIntegrationConfig(
        host="smtp.example.com",
        from_address="opensre@example.com",
    )
    assert config.port == 587
    assert config.security == "starttls"


def test_config_rejects_invalid_security_mode() -> None:
    with pytest.raises(ValueError, match="security must be one of"):
        SMTPIntegrationConfig(
            host="smtp.example.com",
            from_address="opensre@example.com",
            security="tls",
        )


def test_config_rejects_partial_auth() -> None:
    with pytest.raises(ValueError, match="username and password"):
        SMTPIntegrationConfig(
            host="smtp.example.com",
            from_address="opensre@example.com",
            username="mailer",
        )


def test_verify_smtp_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "integrations.smtp.delivery.verify_smtp_connection",
        lambda _config: (True, "Connected to SMTP server successfully."),
    )

    result = _verify_smtp(
        "local env",
        {"host": "smtp.example.com", "from_address": "opensre@example.com"},
    )

    assert result["status"] == "passed"
    assert "connected" in result["detail"].lower()


def test_verify_smtp_reports_validation_errors() -> None:
    result = _verify_smtp("local env", {"host": "smtp.example.com"})
    assert result["status"] == "missing"
    assert "from_address" in result["detail"]


def test_classify_validation_failure_reports_without_secret_value() -> None:
    secret = "smtp-secret-password"

    with patch("infrastructure.observability.errors.boundary.capture_exception") as mock_report:
        result = classify(
            {
                "host": "smtp.example.com",
                "username": "mailer",
                "password": secret,
                "from_address": "not-an-email",
            },
            "smtp-record",
        )

    assert result == (None, None)
    mock_report.assert_called_once()
    reported_exc = mock_report.call_args.args[0]
    assert secret not in str(reported_exc)
    assert "smtp config validation failed" in str(reported_exc)


def test_catalog_bootstraps_smtp_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "opensre@example.com")
    monkeypatch.setenv("SMTP_DEFAULT_TO", "team@example.com")

    from integrations.catalog import resolve_effective_integrations

    effective = resolve_effective_integrations()

    assert "smtp" in effective
    smtp = effective["smtp"]["config"]
    assert smtp["host"] == "smtp.example.com"
    assert smtp["port"] == 465
    assert smtp["security"] == "ssl"
    assert smtp["username"] == "mailer"
    assert smtp["from_address"] == "opensre@example.com"
    assert smtp["default_to"] == "team@example.com"


def test_smtp_send_tool_is_registered_private_and_approval_gated() -> None:
    from core.domain.types.tools import ToolSurface
    from surfaces.cli.ask.approval import approval_required
    from tools.registry import get_registered_tools

    tools = {tool.name: tool for tool in get_registered_tools(ToolSurface.CHAT)}
    sender = tools["send_smtp_email"]
    assert any(tool.name == sender.name for tool in get_registered_tools(ToolSurface.ACTION))
    assert approval_required(sender)
    assert "password" not in sender.public_input_schema["properties"]
    assert sender.extract_params({"smtp": {"password": "private-secret"}}) == {}
    assert sender.is_available(
        {"smtp": {"host": "relay.example.com", "from_address": "a@example.com"}}
    )
    assert not sender.is_available({})


def test_smtp_classifier_exposes_flat_tool_context() -> None:
    from core.tool.execution import availability_view
    from integrations.smtp.tools.tool import SendSMTPEmailTool

    config, key = classify(
        {
            "host": "relay.example.com",
            "from_address": "reports@example.com",
            "port": 25,
            "security": "none",
        },
        "smtp-test",
    )
    assert key == "smtp"
    assert isinstance(config, dict)
    assert SendSMTPEmailTool().is_available(availability_view({"smtp": config}))


def test_smtp_send_tool_uses_configured_default_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.smtp.tools import send_smtp_email

    config = {
        "host": "relay.example.com",
        "port": 25,
        "security": "none",
        "from_address": "reports@example.com",
        "default_to": "team@example.com",
    }
    monkeypatch.setattr(
        "integrations.smtp.tools.delivery.resolve_effective_integrations",
        lambda: {"smtp": {"config": config}},
    )
    with patch(
        "integrations.smtp.tools.delivery.send_smtp_report", return_value=(True, "")
    ) as send:
        result = send_smtp_email(report="RCA findings", subject="RCA report")

    assert result["sent"] is True
    assert send.call_args.kwargs["to_address"] == "team@example.com"
    assert send.call_args.kwargs["smtp_ctx"]["security"] == "none"


def test_smtp_send_tool_rejects_header_injection_before_transport() -> None:
    from integrations.smtp.tools import send_smtp_email

    with patch("integrations.smtp.tools.delivery.send_smtp_report") as send:
        result = send_smtp_email(report="RCA", subject="Subject\r\nBcc: other@example.com")
    assert result["sent"] is False
    assert result["error_type"] == "validation_error"
    send.assert_not_called()


def test_smtp_send_tool_failure_is_not_reported_as_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    from integrations.smtp.tools import send_smtp_email

    monkeypatch.setattr(
        "integrations.smtp.tools.delivery.resolve_effective_integrations",
        lambda: {
            "smtp": {
                "config": {
                    "host": "relay.example.com",
                    "from_address": "reports@example.com",
                    "default_to": "team@example.com",
                }
            }
        },
    )
    with patch(
        "integrations.smtp.tools.delivery.send_smtp_report",
        return_value=(False, "SMTPRecipientsRefused"),
    ):
        result = send_smtp_email(report="RCA", subject="RCA report")

    assert result["status"] == "failed"
    assert result["sent"] is False
    assert result["error_type"] == "delivery_error"


def test_smtp_send_requires_explicit_ask_authority() -> None:
    from core.domain.types.tools import ToolSurface
    from core.llm.types import ToolCall
    from core.tool import ToolExecutionRequest
    from surfaces.cli.ask.approval import ApprovalTracker, build_approval_hooks
    from tools.registry import get_registered_tools

    sender = next(
        tool for tool in get_registered_tools(ToolSurface.CHAT) if tool.name == "send_smtp_email"
    )
    request = ToolExecutionRequest(
        tool_call=ToolCall(
            id="send-1", name=sender.name, input={"report": "RCA", "subject": "RCA"}
        ),
        tool=sender,
        arguments={"report": "RCA", "subject": "RCA"},
        source="smtp",
        resolved_integrations={},
    )
    tracker = ApprovalTracker()
    denied_hooks = build_approval_hooks(allowed_tools=(), bypass_approvals=False, tracker=tracker)
    assert denied_hooks.before_tool_call is not None
    denied = denied_hooks.before_tool_call(request)
    assert denied is not None and denied.blocked
    assert tracker.denied_tools == (sender.name,)
    allowed_hooks = build_approval_hooks(
        allowed_tools=(sender.name,), bypass_approvals=False, tracker=ApprovalTracker()
    )
    assert allowed_hooks.before_tool_call is not None
    allowed = allowed_hooks.before_tool_call(request)
    assert allowed is not None and allowed.approved


def test_smtp_send_is_discoverable_through_progressive_catalog() -> None:
    from types import SimpleNamespace

    from core.agent_harness.tools.progressive_tool_catalog import ProgressiveToolCatalog
    from core.domain.types.tools import ToolSurface
    from tools.registry import get_registered_tools

    tools = tuple(get_registered_tools(ToolSurface.CHAT))
    catalog = ProgressiveToolCatalog(
        SimpleNamespace(skill_discovery_enabled=True),
        lambda: tools,
        enabled=True,
        base_names=(tool.name for tool in tools),
    )
    discovery = next(tool for tool in catalog.snapshot() if tool.name == "tool_search")
    result = discovery.run(query="SMTP email report")

    assert "send_smtp_email" in {item["name"] for item in result["activated"]}
    assert "send_smtp_email" in {tool.name for tool in catalog.snapshot()}
