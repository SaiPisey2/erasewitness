"""Refuses to write report files that look like they contain API keys."""

from __future__ import annotations

import re

_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"apikey_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
)


class SecretLeakError(Exception):
    """A report file contains something that looks like a credential."""


def scan(files: dict[str, str]) -> None:
    for name, text in files.items():
        if any(p.search(text) for p in _PATTERNS):
            raise SecretLeakError(
                f"refusing to write report: {name} contains something that looks like an API key"
            )
