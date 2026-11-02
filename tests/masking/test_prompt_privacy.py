"""Outgoing prompt privacy and local response restoration."""

from __future__ import annotations

import json

from infrastructure.safety.masking.policy import MaskingPolicy
from infrastructure.safety.masking.prompt import PromptPrivacy


def test_identifier_restores_but_secret_never_restores() -> None:
    privacy = PromptPrivacy(MaskingPolicy(enabled=True))
    outgoing = privacy.mask("Pod backend-123 failed. API key: secret-value")

    assert outgoing == "Pod <POD_0> failed. API key: [REDACTED]"
    assert privacy.restore(outgoing) == "Pod backend-123 failed. API key: [REDACTED]"
    assert "secret-value" not in privacy.rules.placeholder_map.values()
    assert privacy.restore("<POD_0> secret-value") == "backend-123 [REDACTED]"


def test_custom_pattern_and_json_arguments_restore_without_corrupting_json() -> None:
    privacy = PromptPrivacy(
        MaskingPolicy(enabled=True, extra_patterns={"customer": r'CUST-[0-9]+ "North"'})
    )
    original = 'CUST-123 "North"'
    assert original not in privacy.mask("Customer: " + original)
    restored = privacy.restore(
        json.dumps({"tool_calls": [{"input": {"customer": "<CUSTOMER_0>"}}]})
    )

    assert json.loads(restored)["tool_calls"][0]["input"]["customer"] == original


def test_disabled_privacy_preserves_existing_behavior() -> None:
    privacy = PromptPrivacy(MaskingPolicy(enabled=False))
    original = "Pod backend-123 failed. API key: secret-value"
    assert privacy.mask(original) == original
    assert privacy.restore(original) == original


def test_request_maps_do_not_cross_contaminate() -> None:
    first = PromptPrivacy(MaskingPolicy(enabled=True))
    second = PromptPrivacy(MaskingPolicy(enabled=True))
    first.mask("Pod backend-123 failed")
    second.mask("Pod backend-456 failed")

    assert first.restore("<POD_0>") == "backend-123"
    assert second.restore("<POD_0>") == "backend-456"


def test_quoted_secret_with_spaces_is_fully_redacted() -> None:
    privacy = PromptPrivacy(MaskingPolicy(enabled=True))
    outgoing = privacy.mask(json.dumps({"api_key": "secret value with spaces"}))
    assert json.loads(outgoing)["api_key"] == "[REDACTED]"
    assert "secret" not in outgoing


def test_password_assignment_keeps_surrounding_json_valid() -> None:
    privacy = PromptPrivacy(MaskingPolicy(enabled=True))
    outgoing = privacy.mask(json.dumps({"message": "password=secret-value", "password": 123456}))
    parsed = json.loads(outgoing)
    assert parsed["message"] == "password=[REDACTED]"
    assert parsed["password"] == "[REDACTED]"


def test_embedded_agent_json_masks_decoded_values_and_restores_fenced_reply() -> None:
    privacy = PromptPrivacy(
        MaskingPolicy(enabled=True, extra_patterns={"customer": r'CUST-[0-9]+ "North"'})
    )
    original = 'CUST-123 "North"'
    state = {"conversation": f"Pod backend-123. Customer: {original}", "namespace": "prod-app"}
    outgoing = privacy.mask("EXTERNAL AGENT STATE (JSON):\n" + json.dumps(state))
    parsed = json.loads(outgoing.split("\n", 1)[1])
    assert parsed["conversation"] == "Pod <POD_0>. Customer: <CUSTOMER_0>"
    assert parsed["namespace"] == "<NAMESPACE_0>"

    reply = '```json\n{"tool_calls": [{"input": {"customer": "<CUSTOMER_0>"}}]}\n```'
    restored = privacy.restore(reply)
    assert json.loads(restored.split("\n")[1])["tool_calls"][0]["input"]["customer"] == original
