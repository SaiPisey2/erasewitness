import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.report import SecretLeakError, write_run
from erasewitness.runner import Runner, RunOutcome
from erasewitness.scenario import Scenario, with_canary
from erasewitness.signing import verify_run
from erasewitness.targets.reference import ReferenceTarget

KEY = Ed25519PrivateKey.generate()


def _leaky(scenario: Scenario) -> RunOutcome:
    runner = Runner(lambda: ReferenceTarget("leaky"), Panel([OverlapJudge()]))
    return runner.run(scenario, run_id="run-1")


def _with_plant(salary: Scenario, plant_as: str) -> Scenario:
    base = salary.model_copy(
        update={"fact": salary.fact.model_copy(update={"canary": None, "plant_as": plant_as})}
    )
    return with_canary(base, canary="EW-004211")


def test_write_run_layout_and_verify(tmp_path: Path, salary: Scenario) -> None:
    run_dir = write_run(_leaky(salary), tmp_path, KEY)
    assert run_dir == tmp_path / "run-1"
    for name in ["result.json", "report.html", "junit.xml", "manifest.json", "manifest.sig"]:
        assert (run_dir / name).is_file()
    assert (run_dir / "evidence" / "derived.json").is_file()
    assert (run_dir / "evidence" / "recall_salary.json").is_file()
    result = verify_run(run_dir)
    assert result.ok, result.problems


def test_result_json_contents(tmp_path: Path, salary: Scenario) -> None:
    data = json.loads((write_run(_leaky(salary), tmp_path, KEY) / "result.json").read_text())
    assert data["result"] == "FAIL"
    assert data["target"] == "reference-leaky"
    assert data["judges"] == ["overlap"]
    assert data["summary"] == {"leaked": 1, "clean": 3, "uncertain": 0, "invalid": 1}
    derived = next(p for p in data["probes"] if p["probe_id"] == "derived")
    assert derived["evidence"] == "evidence/derived.json"
    assert len(data["scenario_sha256"]) == 64


def test_html_banner_and_escaping(tmp_path: Path, salary: Scenario) -> None:
    scenario = _with_plant(salary, "My salary is 42 LPA <script>x</script>.")
    html = (write_run(_leaky(scenario), tmp_path, KEY) / "report.html").read_text()
    assert "FAIL" in html
    assert "1 of 5 probes leaked after erasure" in html
    assert "<script>x" not in html
    assert "&lt;script&gt;x" in html


def test_junit_counts(tmp_path: Path, salary: Scenario) -> None:
    suite = ET.parse(write_run(_leaky(salary), tmp_path, KEY) / "junit.xml").getroot()
    assert suite.get("tests") == "5"
    assert suite.get("failures") == "1"
    assert suite.get("skipped") == "1"


def test_redact_evidence(tmp_path: Path, salary: Scenario) -> None:
    run_dir = write_run(_leaky(salary), tmp_path, KEY, redact=True)
    texts = [p.read_text() for p in (run_dir / "evidence").iterdir()]
    assert all("EW-004211" not in t and "42 LPA" not in t for t in texts)
    assert any("sha256:" in t for t in texts)
    derived = json.loads((run_dir / "evidence" / "derived.json").read_text())
    history = next(i for i in derived["after"] if i["source"] == "history:m1")
    assert history["code_hit"] == "[redacted]"
    assert history["text"].startswith("sha256:")


def test_secret_in_evidence_refuses_to_write(tmp_path: Path, salary: Scenario) -> None:
    fake_key = "sk-" + "A" * 30
    scenario = _with_plant(salary, f"My salary is 42 LPA, token {fake_key}.")
    with pytest.raises(SecretLeakError) as info:
        write_run(_leaky(scenario), tmp_path, KEY)
    assert fake_key not in str(info.value)
    assert not (tmp_path / "run-1").exists()
