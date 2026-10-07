"""Runs the code check and every semantic judge over a batch of items."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from erasewitness.judges.base import JudgeUsage, SemanticJudge
from erasewitness.judges.budget import Budget
from erasewitness.judges.ensemble import Thresholds, decide
from erasewitness.normalise import first_match
from erasewitness.scenario import Scenario
from erasewitness.types import Item, ItemJudgement


class Panel:
    def __init__(
        self,
        judges: Sequence[SemanticJudge],
        thresholds: Thresholds | None = None,
        budget: Budget | None = None,
    ) -> None:
        self._judges = list(judges)
        self._thresholds = thresholds or Thresholds()
        self.budget = budget
        self.errors: list[str] = []
        self._refused: set[int] = set()

    @property
    def names(self) -> list[str]:
        return [j.name for j in self._judges]

    @property
    def non_evidence(self) -> list[str]:
        return [j.name for j in self._judges if not getattr(j, "evidence", True)]

    def usage_report(self) -> dict[str, dict[str, Any]]:
        return {j.name: j.usage.as_dict() for j in self._judges if hasattr(j, "usage")}

    def reset(self) -> None:
        self.errors.clear()
        self._refused.clear()
        if self.budget is not None:
            self.budget.spent_usd = 0.0
        for judge in self._judges:
            usage = getattr(judge, "usage", None)
            if usage is not None:
                judge.usage = JudgeUsage(model=usage.model)

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
        fact, question = scenario.fact.statement, scenario.judge.question
        estimate = getattr(judge, "estimate_cost", None)
        est = estimate(fact, question, texts) if estimate else 0.0
        if self.budget is not None and not self.budget.allows(est):
            if id(judge) not in self._refused:
                self._refused.add(id(judge))
                self._record(
                    f"{judge.name}: budget exceeded "
                    f"(spent ${self.budget.spent_usd:.4f} of ${self.budget.limit_usd:.2f})"
                )
            return [None] * len(texts)
        usage = getattr(judge, "usage", None)
        before = usage.cost_usd if usage else 0.0
        try:
            probs = list(judge.judge(fact, question, texts))
        except Exception as exc:  # any judge failure degrades to "unavailable"
            self._record(f"{judge.name}: {exc}")
            return [None] * len(texts)
        finally:
            if self.budget is not None and usage:
                self.budget.charge(usage.cost_usd - before)

        def _valid(p: object) -> bool:
            return isinstance(p, (int, float)) and not isinstance(p, bool) and 0.0 <= p <= 1.0

        if len(probs) != len(texts) or not all(_valid(p) for p in probs):
            self._record(f"{judge.name}: malformed response")
            return [None] * len(texts)
        return [float(p) for p in probs]

    def _record(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)
