"""The interface every semantic judge implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class JudgeUnavailable(Exception):
    """The judge could not produce an answer (outage, rate limit, bad response)."""


class JudgeConfigError(Exception):
    """A judge cannot be used as configured (missing key, package or price)."""


@dataclass
class JudgeUsage:
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


class SemanticJudge(Protocol):
    name: str
    evidence: bool
    usage: JudgeUsage

    def estimate_cost(self, fact: str, question: str, texts: list[str]) -> float: ...

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        """Probability, per text, that the text reveals the fact. Same length as texts."""
        ...
