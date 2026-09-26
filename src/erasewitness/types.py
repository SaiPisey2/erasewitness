"""Shared value types used across the runner, judges, targets and reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Layer(StrEnum):
    STORE = "store"
    DERIVED = "derived"
    BEHAVIOUR = "behaviour"


class Verdict(StrEnum):
    LEAKED = "LEAKED"
    CLEAN = "CLEAN"
    UNCERTAIN = "UNCERTAIN"
    INVALID = "INVALID"


class RunResult(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Item:
    """One piece of text observed in a target (a stored memory, a derived row, an answer)."""

    layer: Layer
    source: str
    text: str


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str  # "recorded" | "inferred"


@dataclass(frozen=True)
class EraseResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class ItemJudgement:
    item: Item
    verdict: Verdict
    code_hit: str | None
    votes: dict[str, float | None]
    reason: str


@dataclass
class ProbeResult:
    probe_id: str
    layer: Layer
    verdict: Verdict
    reason: str
    before: list[ItemJudgement]
    after: list[ItemJudgement]
    control: list[ItemJudgement]
