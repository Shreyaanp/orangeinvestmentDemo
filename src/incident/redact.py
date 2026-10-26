"""Scrub secrets and personal addresses before data reaches a model or a store."""

import re

SECRETS = re.compile(
    r"(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,}"
    r"|(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+)",
    re.I,
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def redact(text: str) -> str:
    """Applied at every boundary: adapters, stored memory. The model never sees secrets."""
    return EMAIL.sub("[email]", SECRETS.sub("[secret]", text))
