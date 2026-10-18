"""Request-local identifier masking and irreversible prompt-secret redaction."""

from __future__ import annotations

import json
import re

from config.secret_redaction import DEFAULT_REDACTION_RULES
from infrastructure.safety.masking.policy import MaskingPolicy
from infrastructure.safety.masking.rules import MaskingRules

_SECRET_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b(?:api[ _-]?key|password|passwd|auth[ _-]?token|access[ _-]?token|"
    r"client[ _-]?secret|[a-z][a-z0-9_]*_(?:token|password|secret|api_key|pat|key))"
    r"(?:\\?[\"'])?\s*[:=]\s*)"
    r"(?P<value>\\\"(?:[^\\]|\\(?!\"))*\\\"|"
    r'"(?:[^"\\]|\\.)*"|'
    r"'(?:[^'\\]|\\.)*'|[^\s,;{}\"'\\]+)",
    re.IGNORECASE,
)


class PromptPrivacy:
    """Keep an identifier map private to one request; never restore secret values."""

    def __init__(self, policy: MaskingPolicy) -> None:
        self.rules = MaskingRules(policy)
        self._secrets: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self.rules.policy.enabled

    def redact(self, text: str) -> str:
        if not self.enabled:
            return text

        def replace_assignment(match: re.Match[str]) -> str:
            raw = match.group("value")
            if raw in {"null", "None", "true", "false"}:
                return match.group()
            if raw.startswith('\\"'):
                value = raw[2:-2]
                replacement = '\\"[REDACTED]\\"'
            elif raw[:1] in {'"', "'"}:
                value = raw[1:-1]
                replacement = raw[0] + "[REDACTED]" + raw[0]
            else:
                value = raw
                prefix = match.group("prefix")
                replacement = (
                    '\\"[REDACTED]\\"'
                    if '\\"' in prefix
                    else '"[REDACTED]"'
                    if '"' in prefix
                    else "[REDACTED]"
                )
            if value and value != "[REDACTED]":
                self._secrets.add(value)
            return match.group("prefix") + replacement

        result = _SECRET_ASSIGNMENT.sub(replace_assignment, text)
        for rule in DEFAULT_REDACTION_RULES:
            if rule.name == "password_arg":
                continue
            result = rule.pattern.sub("[REDACTED]", result)
        for secret in sorted(self._secrets, key=len, reverse=True):
            pattern = re.compile(r"(?<!\w)" + re.escape(secret) + r"(?!\w)")
            result = pattern.sub("[REDACTED]", result)
        return result

    def mask(self, text: str) -> str:
        return self._transform(text, restore=False)

    def restore(self, text: str) -> str:
        """Restore JSON string values structurally, or restore a plain-text answer."""
        return self._transform(text, restore=True)

    def _transform(self, text: str, *, restore: bool) -> str:
        if not self.enabled:
            return text
        text = self.redact(text)
        transform = self.rules.unmask if restore else self.rules.mask
        decoder = json.JSONDecoder()
        parts: list[str] = []
        cursor = 0
        for match in re.finditer(r"[\[{]", text):
            if match.start() < cursor:
                continue
            try:
                payload, end = decoder.raw_decode(text, match.start())
            except json.JSONDecodeError:
                continue
            parts.append(transform(text[cursor : match.start()]))
            parts.append(
                json.dumps(self._transform_value(payload, restore=restore), ensure_ascii=False)
            )
            cursor = end
        parts.append(transform(text[cursor:]))
        return self.redact("".join(parts))

    def _transform_value(self, value: object, *, restore: bool) -> object:
        if isinstance(value, dict):
            result: dict[str, object] = {}
            for key, child in value.items():
                if not restore and isinstance(child, str):
                    prefix = f"{key}: "
                    contextual = self.rules.mask(self.redact(prefix + child))
                    if contextual.startswith(prefix):
                        child = contextual[len(prefix) :]
                result[key] = self._transform_value(child, restore=restore)
            return result
        if isinstance(value, list):
            return [self._transform_value(child, restore=restore) for child in value]
        if isinstance(value, str):
            return self._transform(value, restore=restore)
        return value
