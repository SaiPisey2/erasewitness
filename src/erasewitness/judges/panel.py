"""Runs the code check and every semantic judge over a batch of items."""

from __future__ import annotations

from collections.abc import Sequence

from erasewitness.judges.base import SemanticJudge
from erasewitness.judges.ensemble import Thresholds, decide
from erasewitness.normalise import first_match
from erasewitness.scenario import Scenario
from erasewitness.types import Item, ItemJudgement


class Panel:
    def __init__(
        self, judges: Sequence[SemanticJudge], thresholds: Thresholds | None = None
    ) -> None:
        self._judges = list(judges)
        self._thresholds = thresholds or Thresholds()
        self.errors: list[str] = []

    @property
    def names(self) -> list[str]:
        return [j.name for j in self._judges]

    def judge_items(self, scenario: Scenario, items: Sequence[Item]) -> list[ItemJudgement]:
        if not items:
            return []
        texts = [item.text for item in items]
        votes = {judge.name: self._ask(judge, scenario, texts) for judge in self._judges}
        needles = [n for n in [scenario.fact.canary, *scenario.fact.sensitive_values] if n]
        out = []
        for idx, item in enumerate(items):
            hit = first_match(item.text, needles)
            item_votes = {name: probs[idx] for name, probs in votes.items()}
            verdict, reason = decide(hit, item_votes, self._thresholds)
            out.append(ItemJudgement(item, verdict, hit, item_votes, reason))
        return out

    def _ask(
        self, judge: SemanticJudge, scenario: Scenario, texts: list[str]
    ) -> list[float | None]:
        try:
            probs = list(judge.judge(scenario.fact.statement, scenario.judge.question, texts))
        except Exception as exc:  # any judge failure degrades to "unavailable"
            self._record(f"{judge.name}: {exc}")
            return [None] * len(texts)
        if len(probs) != len(texts) or any(not 0.0 <= p <= 1.0 for p in probs):
            self._record(f"{judge.name}: malformed response")
            return [None] * len(texts)
        return list(probs)

    def _record(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)
