"""An offline heuristic judge for tests and demos. Its output is not evidence."""

from __future__ import annotations

import re

from erasewitness.judges.base import JudgeUsage

_WORD = re.compile(r"[a-z][a-z']{3,}")
_STOP = {
    "have",
    "that",
    "this",
    "with",
    "your",
    "user",
    "user's",
    "from",
    "they",
    "there",
    "their",
    "about",
    "what",
    "when",
    "which",
    "would",
    "could",
    "should",
}


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


class OverlapJudge:
    name = "overlap"
    evidence = False

    def __init__(self) -> None:
        self.usage = JudgeUsage(model="overlap-heuristic")

    def estimate_cost(self, fact: str, question: str, texts: list[str]) -> float:
        return 0.0

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        self.usage.calls += 1
        words = _content_words(fact)
        return [0.9 if words & _content_words(t) else 0.1 for t in texts]
