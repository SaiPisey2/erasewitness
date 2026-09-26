"""Executes one erasure run: plant, exercise, observe, erase, probe, judge."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from erasewitness.judges.panel import Panel
from erasewitness.scenario import Scenario, with_canary
from erasewitness.targets.base import Target
from erasewitness.types import (
    EraseResult,
    Item,
    ItemJudgement,
    Layer,
    ProbeResult,
    RunResult,
    Verdict,
)

STEPS = [
    "setup",
    "plant",
    "exercise",
    "control+",
    "snapshot",
    "delete",
    "settle",
    "probe",
    "control-",
    "judge",
]


@dataclass(frozen=True)
class RunConfig:
    strict: bool = False
    settle_timeout_s: float = 60.0


@dataclass(frozen=True)
class Event:
    kind: str
    step: str
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    layer: Layer
    query: str


@dataclass
class RunOutcome:
    run_id: str
    scenario: Scenario
    target: str
    judges: list[str]
    versions: dict[str, str] = field(default_factory=dict)
    result: RunResult = RunResult.ERROR
    probes: list[ProbeResult] = field(default_factory=list)
    snapshot: list[ItemJudgement] = field(default_factory=list)
    collateral: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    not_covered: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    error: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def probe_specs(scenario: Scenario) -> list[ProbeSpec]:
    specs = [ProbeSpec(f"recall:{q}", Layer.STORE, q) for q in scenario.probes.recall]
    specs.append(ProbeSpec("derived", Layer.DERIVED, ""))
    specs += [
        ProbeSpec(f"ask:{i}", Layer.BEHAVIOUR, p.question)
        for i, p in enumerate(scenario.probes.behaviour)
    ]
    return specs


def aggregate(judgements: Sequence[ItemJudgement]) -> Verdict:
    verdicts = {j.verdict for j in judgements}
    if Verdict.LEAKED in verdicts:
        return Verdict.LEAKED
    if Verdict.UNCERTAIN in verdicts:
        return Verdict.UNCERTAIN
    return Verdict.CLEAN


def final_verdict(
    before: Sequence[ItemJudgement],
    after: Sequence[ItemJudgement],
    control: Sequence[ItemJudgement],
    settled: bool,
) -> tuple[Verdict, str]:
    if aggregate(before) is not Verdict.LEAKED:
        return Verdict.INVALID, "fact was not observable through this probe before erasure"
    after_verdict = aggregate(after)
    if after_verdict is Verdict.LEAKED:
        leaked = [j for j in after if j.verdict is Verdict.LEAKED]
        semantic_only = all(j.code_hit is None for j in leaked)
        if semantic_only and aggregate(control) is Verdict.LEAKED:
            return (
                Verdict.UNCERTAIN,
                "a space that never saw the fact gives the same signal (agent guessing)",
            )
        return Verdict.LEAKED, "fact still observable after erasure"
    if after_verdict is Verdict.UNCERTAIN:
        return Verdict.UNCERTAIN, "judges could not agree on at least one item after erasure"
    if not settled:
        return Verdict.UNCERTAIN, "settle timed out, so a clean result cannot be trusted"
    return Verdict.CLEAN, "fact observable before erasure and not after"


def overall(probes: Sequence[ProbeResult]) -> RunResult:
    verdicts = [p.verdict for p in probes]
    if Verdict.LEAKED in verdicts:
        return RunResult.FAIL
    if Verdict.UNCERTAIN in verdicts or Verdict.CLEAN not in verdicts:
        return RunResult.INCONCLUSIVE
    return RunResult.PASS


class Runner:
    def __init__(
        self,
        target_factory: Callable[[], Target],
        panel: Panel,
        config: RunConfig | None = None,
        on_event: Callable[[Event], None] | None = None,
    ) -> None:
        self._factory = target_factory
        self._panel = panel
        self._config = config or RunConfig()
        self._on_event = on_event

    def run(self, scenario: Scenario, run_id: str | None = None) -> RunOutcome:
        scenario = with_canary(scenario)
        rid = run_id or new_run_id()
        target = self._factory()
        out = RunOutcome(
            run_id=rid,
            scenario=scenario,
            target=target.name,
            judges=self._panel.names,
            started_at=_now(),
        )
        control: Target | None = None
        try:
            self._step("setup")
            target.setup(rid)
            out.versions = dict(target.version_info())
            coverage = target.coverage()
            specs = [s for s in probe_specs(scenario) if coverage.get(s.layer, False)]
            out.not_covered = [layer.value for layer in Layer if not coverage.get(layer, False)]

            self._step("plant")
            target.plant(scenario.fact.plant_as)
            self._step("exercise")
            target.exercise(scenario.exercise)
            if not target.settle(self._config.settle_timeout_s):
                out.findings.append("settle before erasure timed out")

            self._step("control+")
            before = {s.probe_id: self._observe(target, s, scenario) for s in specs}

            self._step("snapshot")
            out.snapshot = self._panel.judge_items(scenario, target.snapshot())

            self._step("delete")
            strict = self._config.strict or scenario.erasure.method == "strict"
            strict_items = (
                [j.item for j in out.snapshot if j.verdict is Verdict.LEAKED] if strict else None
            )
            erase = self._erase(target, scenario, strict_items)
            if not erase.ok:
                out.findings.append(f"vendor erasure call failed: {erase.detail}")

            self._step("settle")
            settled = target.settle(self._config.settle_timeout_s)
            if not settled:
                out.findings.append("settle after erasure timed out; CLEAN results downgraded")

            self._step("probe")
            after = {s.probe_id: self._observe(target, s, scenario) for s in specs}
            out.collateral = self._collateral(out.snapshot, target.snapshot())
            if out.collateral:
                out.findings.append(
                    f"collateral deletion: {len(out.collateral)} unrelated item(s) removed"
                )

            self._step("control-")
            control = self._factory()
            control.setup(f"{rid}-control")
            control.exercise(scenario.exercise)
            control.settle(self._config.settle_timeout_s)
            ctrl = {s.probe_id: self._observe(control, s, scenario) for s in specs}

            self._step("judge")
            for spec in specs:
                verdict, reason = final_verdict(
                    before[spec.probe_id], after[spec.probe_id], ctrl[spec.probe_id], settled
                )
                out.probes.append(
                    ProbeResult(
                        probe_id=spec.probe_id,
                        layer=spec.layer,
                        verdict=verdict,
                        reason=reason,
                        before=before[spec.probe_id],
                        after=after[spec.probe_id],
                        control=ctrl[spec.probe_id],
                    )
                )
                self._emit(
                    Event("probe", "judge", {"probe_id": spec.probe_id, "verdict": verdict.value})
                )
            out.result = overall(out.probes)
        except Exception as exc:  # the run must always produce an outcome
            out.result = RunResult.ERROR
            out.error = f"{type(exc).__name__}: {exc}"
        finally:
            out.leftovers = self._cleanup(target)
            if control is not None:
                out.leftovers += self._cleanup(control)
            out.findings += [f"judge error: {e}" for e in self._panel.errors]
            out.finished_at = _now()
            self._emit(Event("done", "report", {"result": out.result.value}))
        return out

    def _observe(self, target: Target, spec: ProbeSpec, scenario: Scenario) -> list[ItemJudgement]:
        items: list[Item]
        if spec.layer is Layer.STORE:
            items = target.probe_store(spec.query)
        elif spec.layer is Layer.DERIVED:
            items = target.probe_derived()
        else:
            items = [
                Item(Layer.BEHAVIOUR, f"{spec.probe_id}#{k}", target.ask(spec.query))
                for k in range(scenario.judge.samples)
            ]
        return self._panel.judge_items(scenario, items)

    @staticmethod
    def _erase(target: Target, scenario: Scenario, strict_items: list[Item] | None) -> EraseResult:
        try:
            return target.erase(scenario, strict_items)
        except Exception as exc:  # a failing vendor delete is a finding, not a crash
            return EraseResult(False, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _collateral(before: Sequence[ItemJudgement], after_items: Sequence[Item]) -> list[str]:
        remaining = {item.source for item in after_items}
        return sorted(
            j.item.source
            for j in before
            if j.verdict is Verdict.CLEAN and j.item.source not in remaining
        )

    @staticmethod
    def _cleanup(target: Target) -> list[str]:
        try:
            return target.cleanup()
        except Exception as exc:
            return [f"cleanup failed: {type(exc).__name__}: {exc}"]

    def _step(self, name: str) -> None:
        self._emit(Event("step", name))

    def _emit(self, event: Event) -> None:
        if self._on_event is not None:
            self._on_event(event)
