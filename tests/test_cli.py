from pathlib import Path

from typer.testing import CliRunner, Result

from erasewitness.cli import app
from erasewitness.store import RunIndex

cli = CliRunner()


def _run(tmp_path: Path, *args: str) -> Result:
    return cli.invoke(
        app,
        ["run", *args, "--out", str(tmp_path / "runs"), "--key", str(tmp_path / "k.key")],
    )


def _only_run_dir(tmp_path: Path) -> Path:
    (run_dir,) = list((tmp_path / "runs").iterdir())
    return run_dir


def test_run_leaky_fails_with_exit_1(tmp_path: Path) -> None:
    result = _run(tmp_path, "--target", "reference-leaky", "--scenario", "salary")
    assert result.exit_code == 1, result.output
    assert "FAIL: 1 of 5 probes leaked after erasure" in result.output
    assert "not evidence" in result.output
    run_dir = _only_run_dir(tmp_path)
    assert (run_dir / "report.html").is_file()
    assert cli.invoke(app, ["verify", str(run_dir)]).exit_code == 0


def test_run_clean_passes(tmp_path: Path) -> None:
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_run_records_index(tmp_path: Path) -> None:
    _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    _run(tmp_path, "--target", "reference-leaky", "--scenario", "phone-number")
    rows = RunIndex(tmp_path / "index.sqlite").list_runs()
    assert len(rows) == 2
    assert {r["result"] for r in rows} == {"PASS", "FAIL"}


def test_unknown_names_exit_3(tmp_path: Path) -> None:
    bad_scenario = _run(tmp_path, "--target", "reference-clean", "--scenario", "nope")
    bad_target = _run(tmp_path, "--target", "nope", "--scenario", "salary")
    bad_judge = _run(
        tmp_path, "--target", "reference-clean", "--scenario", "salary", "--judges", "nope"
    )
    assert bad_scenario.exit_code == 3 and "unknown scenario" in bad_scenario.output
    assert bad_target.exit_code == 3 and "unknown target" in bad_target.output
    assert bad_judge.exit_code == 3 and "unknown judge" in bad_judge.output


def test_verify_detects_tampering(tmp_path: Path) -> None:
    _run(tmp_path, "--target", "reference-leaky", "--scenario", "salary")
    run_dir = _only_run_dir(tmp_path)
    (run_dir / "result.json").write_text("{}")
    result = cli.invoke(app, ["verify", str(run_dir)])
    assert result.exit_code == 1
    assert "modified file: result.json" in result.output


def test_keygen_refuses_overwrite(tmp_path: Path) -> None:
    key = str(tmp_path / "k.key")
    first = cli.invoke(app, ["keygen", "--key", key])
    assert first.exit_code == 0 and "fingerprint" in first.output
    assert cli.invoke(app, ["keygen", "--key", key]).exit_code == 1
    assert cli.invoke(app, ["keygen", "--key", key, "--force"]).exit_code == 0


def test_scenarios_list() -> None:
    result = cli.invoke(app, ["scenarios", "list"])
    assert result.exit_code == 0
    for name in ["salary", "health-condition", "home-address", "child-school", "phone-number"]:
        assert name in result.output


def _fingerprint_from_keygen(result: Result) -> str:
    line = next(line for line in result.output.splitlines() if line.startswith("fingerprint "))
    return line.removeprefix("fingerprint ").strip()


def test_verify_expect_matching_fingerprint(tmp_path: Path) -> None:
    keygen_result = cli.invoke(app, ["keygen", "--key", str(tmp_path / "k.key")])
    fp = _fingerprint_from_keygen(keygen_result)
    _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    run_dir = _only_run_dir(tmp_path)
    result = cli.invoke(app, ["verify", str(run_dir), "--expect", fp])
    assert result.exit_code == 0, result.output
    assert "not pinned" not in result.output


def test_verify_expect_wrong_fingerprint_fails(tmp_path: Path) -> None:
    _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    run_dir = _only_run_dir(tmp_path)
    result = cli.invoke(app, ["verify", str(run_dir), "--expect", "0000:0000:0000:0000"])
    assert result.exit_code == 1
    assert "does not match expected" in result.output


def test_verify_unpinned_warns(tmp_path: Path) -> None:
    _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    run_dir = _only_run_dir(tmp_path)
    result = cli.invoke(app, ["verify", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert "warning: signer not pinned" in result.output


def test_run_prints_signer_fingerprint(tmp_path: Path) -> None:
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    assert "signer: " in result.output
