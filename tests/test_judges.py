import pytest

from erasewitness.judges.ensemble import Thresholds, decide
from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.scenario import Scenario
from erasewitness.types import Item, Layer, Verdict

TH = Thresholds()


@pytest.mark.parametrize(
    ("code", "votes", "expected"),
    [
        ("42 LPA", {"a": 0.0, "b": 0.0}, Verdict.LEAKED),
        (None, {"a": 0.9, "b": 0.8}, Verdict.LEAKED),
        (None, {"a": 0.1, "b": 0.2}, Verdict.CLEAN),
        (None, {"a": 0.9, "b": 0.1}, Verdict.UNCERTAIN),
        (None, {"a": 0.5, "b": 0.5}, Verdict.UNCERTAIN),
        (None, {"a": 0.9, "b": None}, Verdict.UNCERTAIN),
        (None, {}, Verdict.UNCERTAIN),
    ],
)
def test_decide_table(code: str | None, votes: dict[str, float | None], expected: Verdict) -> None:
    verdict, _ = decide(code, votes, TH)
    assert verdict is expected


def test_decide_names_unavailable_judge() -> None:
    _, reason = decide(None, {"jev": None, "openai": 0.9}, TH)
    assert "jev" in reason


def test_overlap_judge() -> None:
    judge = OverlapJudge()
    probs = judge.judge(
        "My salary is 42 LPA.",
        "reveals the salary",
        ["Summary: my salary is LPA", "I don't have that information."],
    )
    assert probs == [0.9, 0.1]


class _Broken:
    name = "broken"

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        raise RuntimeError("service down")


class _Short:
    name = "short"

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        return [0.9]


class _Counting:
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        self.calls += 1
        return [0.9 for _ in texts]


ITEMS = [
    Item(Layer.DERIVED, "history:m1", "My salary is 42 LPA. (reference EW-004211)"),
    Item(Layer.DERIVED, "summary", "Summary: my salary is LPA"),
]


def test_panel_code_hit_prefers_canary(salary: Scenario) -> None:
    out = Panel([OverlapJudge()]).judge_items(salary, ITEMS)
    assert out[0].code_hit == "EW-004211"
    assert out[0].verdict is Verdict.LEAKED
    assert out[1].code_hit is None
    assert out[1].verdict is Verdict.LEAKED
    assert out[1].votes == {"overlap": 0.9}


def test_panel_broken_judge_degrades_to_uncertain(salary: Scenario) -> None:
    panel = Panel([_Broken(), OverlapJudge()])
    out = panel.judge_items(salary, ITEMS)
    assert out[0].verdict is Verdict.LEAKED  # code check still decides
    assert out[1].verdict is Verdict.UNCERTAIN
    assert out[1].votes["broken"] is None
    assert panel.errors == ["broken: service down"]


def test_panel_broken_judge_malformed_answer(salary: Scenario) -> None:
    panel = Panel([_Short()])
    out = panel.judge_items(salary, ITEMS)
    assert out[1].verdict is Verdict.UNCERTAIN
    assert panel.errors == ["short: malformed response"]


def test_panel_skips_judges_for_no_items(salary: Scenario) -> None:
    judge = _Counting()
    assert Panel([judge]).judge_items(salary, []) == []
    assert judge.calls == 0


class _NonNumeric:
    name = "nonnumeric"

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        return [None, 0.9]  # type: ignore[list-item]


def test_panel_non_numeric_answer_degrades(salary: Scenario) -> None:
    panel = Panel([_NonNumeric()])
    out = panel.judge_items(salary, ITEMS)
    assert out[1].verdict is Verdict.UNCERTAIN
    assert panel.errors == ["nonnumeric: malformed response"]
