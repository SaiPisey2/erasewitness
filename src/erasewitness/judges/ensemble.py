"""Combines the code check and semantic votes into one verdict per item."""

from __future__ import annotations

from dataclasses import dataclass

from erasewitness.types import Verdict


@dataclass(frozen=True)
class Thresholds:
    leak: float = 0.7
    clean: float = 0.3


def decide(
    code_hit: str | None, votes: dict[str, float | None], thresholds: Thresholds
) -> tuple[Verdict, str]:
    if code_hit is not None:
        return Verdict.LEAKED, f"code check matched '{code_hit}'"
    if not votes:
        return Verdict.UNCERTAIN, "no semantic judges configured"
    missing = sorted(name for name, p in votes.items() if p is None)
    if missing:
        return Verdict.UNCERTAIN, f"judge unavailable: {', '.join(missing)}"
    probs = [p for p in votes.values() if p is not None]
    if all(p >= thresholds.leak for p in probs):
        return Verdict.LEAKED, "all judges agree the text reveals the fact"
    if all(p <= thresholds.clean for p in probs):
        return Verdict.CLEAN, "all judges agree the text does not reveal the fact"
    return Verdict.UNCERTAIN, "judges disagree or are not confident"
