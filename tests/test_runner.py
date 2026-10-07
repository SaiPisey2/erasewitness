from collections.abc import Callable
from pathlib import Path

from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.report import write_run
from erasewitness.runner import STEPS, Event, RunConfig, Runner, RunOutcome, probe_specs
from erasewitness.scenario import Scenario
from erasewitness.signing import generate_key
from erasewitness.targets.base import Target
from erasewitness.targets.reference import ReferenceTarget
from erasewitness.types import EraseResult, Item, RunResult, Verdict


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
    assert any("over-deletion" in f for f in outcome.findings)


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
    _Exploding.cleaned = False
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


class _LateIngest(ReferenceTarget):
    """Plants text but only ingests it into the store during erase() (late ingestion)."""

    def __init__(self) -> None:
        super().__init__("clean")
        self._pending: str | None = None

    def plant(self, text: str) -> None:
        self._pending = text

    def erase(self, scenario: Scenario, strict_items: list[Item] | None) -> EraseResult:
        result = super().erase(scenario, strict_items)
        if self._pending is not None:
            self._add(self._pending)
            self._pending = None
        return result


def test_leak_after_unconfirmed_before_is_leaked(salary: Scenario) -> None:
    outcome = _run(lambda: _LateIngest(), salary)
    assert outcome.result is RunResult.FAIL
    assert _verdicts(outcome)["recall:salary"] is Verdict.LEAKED


class _FlakyOnce:
    """Raises on its very first call ever, then behaves like OverlapJudge."""

    name = "flaky"

    def __init__(self) -> None:
        self._calls = 0
        self._overlap = OverlapJudge()

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("hiccup")
        return self._overlap.judge(fact, question, texts)


def test_judge_error_in_one_step_is_not_pass(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("clean"), salary, Panel([_FlakyOnce()]))
    assert outcome.result is RunResult.INCONCLUSIVE
    assert any("judge error:" in f for f in outcome.findings)


def test_panel_errors_do_not_carry_over(salary: Scenario) -> None:
    panel = Panel([_FlakyOnce()])
    first = _run(lambda: ReferenceTarget("clean"), salary, panel)
    assert any("judge error:" in f for f in first.findings)
    second = _run(lambda: ReferenceTarget("clean"), salary, panel)
    assert second.result is RunResult.PASS
    assert not any("judge error" in f for f in second.findings)


def test_factory_error_is_error_not_raise(salary: Scenario) -> None:
    def _boom() -> ReferenceTarget:
        raise RuntimeError("no creds")

    outcome = _run(_boom, salary)
    assert outcome.result is RunResult.ERROR
    assert outcome.error is not None and "no creds" in outcome.error


def test_event_callback_error_is_ignored(salary: Scenario) -> None:
    def _boom_on_event(event: Event) -> None:
        raise RuntimeError("callback broke")

    runner = Runner(
        lambda: ReferenceTarget("clean"), Panel([OverlapJudge()]), on_event=_boom_on_event
    )
    outcome = runner.run(salary, run_id="run-1")
    assert outcome.result is RunResult.PASS


class _ErasesThenFails(ReferenceTarget):
    def erase(self, scenario: Scenario, strict_items: list[Item] | None) -> EraseResult:
        super().erase(scenario, strict_items)
        raise RuntimeError("504")


def test_erase_error_after_deleting_is_not_pass(salary: Scenario) -> None:
    outcome = _run(lambda: _ErasesThenFails("clean"), salary)
    assert outcome.result is RunResult.INCONCLUSIVE
    assert any("vendor erasure call failed" in f for f in outcome.findings)


class _CleanupFails(ReferenceTarget):
    def cleanup(self) -> list[str]:
        raise RuntimeError("cleanup boom")


def test_cleanup_failure_is_not_pass(salary: Scenario) -> None:
    outcome = _run(lambda: _CleanupFails("clean"), salary)
    assert outcome.result is RunResult.INCONCLUSIVE
    assert sum(1 for f in outcome.findings if f.startswith("cleanup failed")) == 1


def test_strict_run_records_method(salary: Scenario) -> None:
    outcome = _run(lambda: ReferenceTarget("leaky"), salary, strict=True)
    assert outcome.strict is True


def test_all_invalid_layer_blocks_pass(salary: Scenario) -> None:
    no_match = salary.model_copy(
        update={"probes": salary.probes.model_copy(update={"recall": ["zzz-no-match"]})}
    )
    outcome = _run(lambda: ReferenceTarget("clean"), no_match)
    assert outcome.result is RunResult.INCONCLUSIVE
    assert "store" in outcome.not_covered


def test_duplicate_recall_queries_deduplicated(salary: Scenario) -> None:
    dup = salary.model_copy(
        update={"probes": salary.probes.model_copy(update={"recall": ["salary", "salary"]})}
    )
    ids = [s.probe_id for s in probe_specs(dup)]
    assert ids.count("recall:salary") == 1


def test_runner_records_budget_and_usage(salary: Scenario) -> None:
    from erasewitness.judges.budget import Budget

    runner = Runner(
        lambda: ReferenceTarget("clean"), Panel([OverlapJudge()], budget=Budget(limit_usd=2.0))
    )
    outcome = runner.run(salary, run_id="run-1")
    assert outcome.budget_usd == 2.0
    assert outcome.scenario_ref == "salary"
    calls = outcome.judge_usage["overlap"]["calls"]
    assert isinstance(calls, int) and calls > 0


class _KeyLeaker:
    name = "leaker"

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        raise RuntimeError("bad key sk-" + "A" * 30)


def test_judge_error_with_key_is_masked_and_run_still_writes(
    salary: Scenario, tmp_path: Path
) -> None:
    outcome = _run(lambda: ReferenceTarget("clean"), salary, Panel([_KeyLeaker()]))
    run_dir = write_run(outcome, tmp_path, generate_key(tmp_path / "k.key"))
    text = (run_dir / "result.json").read_text()
    assert "[redacted]" in text
    assert "sk-" + "A" * 30 not in text


def test_runner_notes_do_not_change_result(salary: Scenario) -> None:
    class Noted(ReferenceTarget):
        def notes(self) -> list[str]:
            return ["x"]

    outcome = _run(lambda: Noted("clean"), salary)
    assert outcome.result is RunResult.PASS
    assert "note: x" in outcome.findings
