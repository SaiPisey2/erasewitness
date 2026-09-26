"""Text normalisation and exact-value matching used by the code check."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_SPACE = re.compile(r"\s+")
_DIGIT_SEP = re.compile(r"(?<=\d)[ ,\-](?=\d)")


def normalise(text: str) -> str:
    """Case-fold, collapse whitespace and drop separators between digits."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    collapsed = _SPACE.sub(" ", folded).strip()
    return _DIGIT_SEP.sub("", collapsed)


def contains_value(haystack: str, needle: str) -> bool:
    """True if the normalised needle appears in the haystack as a whole token run."""
    wanted = normalise(needle)
    if not wanted:
        return False
    pattern = rf"(?<!\w){re.escape(wanted)}(?!\w)"
    return re.search(pattern, normalise(haystack)) is not None


def first_match(text: str, needles: Iterable[str]) -> str | None:
    for needle in needles:
        if contains_value(text, needle):
            return needle
    return None
