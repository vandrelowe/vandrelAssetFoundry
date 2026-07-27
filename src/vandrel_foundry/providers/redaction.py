from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "[REDACTED]"
REDACTED_DATA_URI = "[REDACTED_DATA_URI]"

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    }
)


def redact_provider_evidence(value: Any) -> Any:
    """Return a JSON-compatible copy with credentials and signed queries removed."""
    if isinstance(value, Mapping):
        return {
            str(key): (REDACTED if _is_sensitive_key(str(key)) else redact_provider_evidence(item))
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_provider_evidence(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return REDACTED_DATA_URI
    if isinstance(value, str) and _looks_like_url(value):
        return _redact_url(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(("_token", "_secret", "_key"))


def _looks_like_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def _redact_url(value: str) -> str:
    split = urlsplit(value)
    if not split.query:
        return value
    return urlunsplit((split.scheme, split.netloc, split.path, REDACTED, ""))
