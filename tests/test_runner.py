from collections.abc import Callable

from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.runner import STEPS, Event, RunConfig, Runner, RunOutcome
from erasewitness.scenario import Scenario
from erasewitness.targets.base import Target
from erasewitness.targets.reference import ReferenceTarget
from erasewitness.types import RunResult, Verdict


def _verdicts(outcome: RunOutcome) -> dict[str, Verdict]:
    return {p.probe_id: p.verdict for p in outcome.probes}


def _run(
    factory: Callable[[], Target],
    salary: Scenario,
    panel: Panel | None = None,
    **cfg: bool,
) -> RunOutcome:
    runner = Runner(factory, panel or Panel([OverlapJudge()]), RunConfig(**cfg))
    return runner.run(salary, run_id="run-1")


def test_clean_target_passes(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("clean"), salary)
    assert outcome.result is RunResult.PASS
    assert _verdicts(outcome) == {
        "recall:salary": Verdict.CLEAN,
        "recall:income": Verdict.INVALID,
        "derived": Verdict.CLEAN,
        "ask:0": Verdict.CLEAN,
        "ask:1": Verdict.CLEAN,
    }
    assert outcome.error is None


def test_leaky_target_fails_at_derived_layer_only(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("leaky"), salary)
    assert outcome.result is RunResult.FAIL
    verdicts = _verdicts(outcome)
    assert verdicts["derived"] is Verdict.LEAKED
    assert verdicts["recall:salary"] is Verdict.CLEAN
    assert verdicts["ask:0"] is Verdict.CLEAN
    derived = next(p for p in outcome.probes if p.probe_id == "derived")
    by_source = {j.item.source: j for j in derived.after}
    assert by_source["history:m1"].code_hit == "EW-004211"
    # The reworded summary is caught by the semantic judge, not by the code check.
    assert by_source["summary"].code_hit is None
    assert by_source["summary"].verdict is Verdict.LEAKED


def test_strict_mode_fixes_leaky_target(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("leaky"), salary, strict=True)
    assert outcome.result is RunResult.PASS


def test_overdelete_reports_collateral(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("overdelete"), salary)
    assert outcome.result is RunResult.PASS
    assert outcome.collateral == ["history:m1", "memory:m1"]
    assert any("collateral deletion" in f for f in outcome.findings)


def test_settle_timeout_downgrades_clean(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("clean", settle_ok=False), salary)
    assert outcome.result is RunResult.INCONCLUSIVE
    assert _verdicts(outcome)["recall:salary"] is Verdict.UNCERTAIN
    assert any("settle" in f for f in outcome.findings)


def test_vendor_erase_failure_is_a_finding(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("clean", fail_erase=True), salary)
    assert outcome.result is RunResult.FAIL
    assert any("vendor erasure call failed" in f for f in outcome.findings)
    assert outcome.error is None


class _Broken:
    name = "broken"

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        raise RuntimeError("service down")


def test_judge_failure_makes_run_inconclusive(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("clean"), salary, Panel([_Broken(), OverlapJudge()]))
    assert outcome.result is RunResult.INCONCLUSIVE
    assert "judge error: broken: service down" in outcome.findings


class _Guessing(ReferenceTarget):
    def ask(self, question: str) -> str:
        return "Your salary seems high."


def test_control_space_marks_guessing(salary: Scenario) -> None:
    outcome = _run(lambda: _Guessing("clean"), salary)
    probe = next(p for p in outcome.probes if p.probe_id == "ask:0")
    assert probe.verdict is Verdict.UNCERTAIN
    assert "guessing" in probe.reason
    assert outcome.result is RunResult.INCONCLUSIVE


class _Exploding(ReferenceTarget):
    cleaned = False

    def plant(self, text: str) -> None:
        raise RuntimeError("target crashed")

    def cleanup(self) -> list[str]:
        _Exploding.cleaned = True
        return []


def test_target_crash_is_error_and_cleans_up(salary: Scenario) -> None:
    outcome = _run(lambda: _Exploding("clean"), salary)
    assert outcome.result is RunResult.ERROR
    assert outcome.error is not None and "target crashed" in outcome.error
    assert _Exploding.cleaned


def test_events_follow_step_order(salary: Scenario) -> None:
    events: list[Event] = []
    runner = Runner(
        lambda: ReferenceTarget("clean"), Panel([OverlapJudge()]), on_event=events.append
    )
    runner.run(salary, run_id="run-1")
    assert [e.step for e in events if e.kind == "step"] == STEPS
    assert len([e for e in events if e.kind == "probe"]) == 5
    assert events[-1].kind == "done"
    assert events[-1].data == {"result": "PASS"}
