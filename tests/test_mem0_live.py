import os

import pytest

from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.runner import Runner
from erasewitness.scenario import Scenario
from erasewitness.targets.mem0 import Mem0Target
from erasewitness.types import RunResult, Verdict

live = pytest.mark.skipif(
    os.environ.get("ERASEWITNESS_LIVE") != "1" or not os.environ.get("OPENAI_API_KEY"),
    reason="live test: set ERASEWITNESS_LIVE=1 and OPENAI_API_KEY",
)


@live
def test_real_mem0_keeps_deleted_fact_in_history(salary: Scenario) -> None:
    outcome = Runner(Mem0Target, Panel([OverlapJudge()])).run(salary, run_id="live-mem0")
    assert outcome.error is None, outcome.error
    derived = next(p for p in outcome.probes if p.probe_id == "derived")
    assert derived.verdict is Verdict.LEAKED
    assert outcome.result is RunResult.FAIL
