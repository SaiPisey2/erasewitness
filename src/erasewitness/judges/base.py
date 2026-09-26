"""The interface every semantic judge implements."""

from __future__ import annotations

from typing import Protocol


class JudgeUnavailable(Exception):
    """The judge could not produce an answer (outage, rate limit, bad response)."""


class SemanticJudge(Protocol):
    name: str

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        """Probability, per text, that the text reveals the fact. Same length as texts."""
        ...
