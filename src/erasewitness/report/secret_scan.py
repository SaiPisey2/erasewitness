"""Refuses to write report files that look like they contain API keys."""

from __future__ import annotations

import re

_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])apikey_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)bearer(?:\s|\\n)+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"),
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}"),
)


class SecretLeakError(Exception):
    """A report file contains something that looks like a credential."""


def scan(files: dict[str, str]) -> None:
    for name, text in files.items():
        if any(p.search(text) for p in _PATTERNS):
            raise SecretLeakError(
                f"refusing to write report: {name} contains something that looks like an API key"
            )
