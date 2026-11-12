"""Shared boundary redaction for configuration, HTTP responses and terminal logs."""
import re
from typing import Any


_CONFIG_SECRETS = re.compile(
    r"(?<![-\w])((?:password|passwd|secret|shared-key|pre-shared-key|"
    r"authentication-key|key)(?:[ \t]*[:：=][ \t]*|[ \t]+)"
    r"(?:(?:cipher|simple|irreversible-cipher)[ \t]+)?)[^\r\n]+",
    re.IGNORECASE,
)
_COMMUNITY = re.compile(
    r"((?:snmp-agent[ \t]+community[ \t]+(?:read|write)|"
    r"community(?:-name)?[ \t]+\S+)[ \t]+(?:(?:cipher|simple)[ \t]+)?)[^\r\n]+",
    re.IGNORECASE,
)
_AUTHENTICATION_SECRETS = re.compile(
    r"(?<![-\w])((?:(?:area-|domain-)?authentication-mode|privacy-mode)[ \t]+"
    r"(?:simple|md5|hmac-[\w-]+|sha(?:-?\d+)?|aes(?:-?\d+)?|des(?:56)?)[ \t]+"
    # Preserve an explicit key ID only when a cipher/plain marker follows it.
    r"(?:\d+[ \t]+(?=(?:cipher|plain)[ \t]+))?"
    r"(?:(?:cipher|plain)[ \t]+)?)[^\r\n]+",
    re.IGNORECASE,
)
# Exact field names only: a generic business `key` / `max_tokens` is not a secret.
_SECRET_FIELD_PATTERN = (
    r"password|passwd|secret|shared[-_]key|pre[-_]shared[-_]key|"
    r"authentication[-_]key|api[-_]key|access[-_]token|refresh[-_]token|authorization"
)
_SECRET_FIELD = re.compile(rf"(?:{_SECRET_FIELD_PATTERN})", re.IGNORECASE)
_QUOTED_SECRETS = re.compile(
    rf'''(["'](?:{_SECRET_FIELD_PATTERN})["'][ \t]*:[ \t]*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')''',
    re.IGNORECASE,
)


def redact_sensitive(text: str | None) -> str | None:
    """Conservatively hide the rest of a credential-bearing line, including quotes."""
    if not text:
        return text
    text = _QUOTED_SECRETS.sub(r'\1"******"', text)
    text = _AUTHENTICATION_SECRETS.sub(r"\1******", text)
    return _COMMUNITY.sub(r"\1******", _CONFIG_SECRETS.sub(r"\1******", text))


def redact_payload(value: Any) -> Any:
    """Mask text in an outgoing container without changing ORM state or scalar types."""
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, dict):
        return {
            key: ("******" if isinstance(key, str) and _SECRET_FIELD.fullmatch(key)
                  and item is not None and item != "" else redact_payload(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    return value
