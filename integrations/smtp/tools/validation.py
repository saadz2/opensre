"""Validation for plain-text SMTP report delivery."""

from email.utils import parseaddr


def validate_email_request(report: str, subject: str, to_address: str) -> str:
    if not report.strip():
        return "Report must not be empty."
    if not subject.strip() or any(character in subject for character in ("\r", "\n", "\x00")):
        return "Subject must be non-empty and contain no header control characters."
    if to_address:
        if any(character in to_address for character in ("\r", "\n", "\x00")):
            return "Recipient must contain no header control characters."
        _name, address = parseaddr(to_address)
        if not address or "@" not in address:
            return "Recipient must be a valid email address."
    return ""
