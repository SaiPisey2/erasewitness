import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from erasewitness.cli import JUDGES, app
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


def test_bad_key_file_exits_3(tmp_path: Path) -> None:
    bad_key = tmp_path / "bad.key"
    bad_key.write_text("not a key")
    result = cli.invoke(
        app,
        [
            "run",
            "--target",
            "reference-clean",
            "--scenario",
            "salary",
            "--out",
            str(tmp_path / "runs"),
            "--key",
            str(bad_key),
        ],
    )
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 3, combined
    assert "cannot load signing key" in combined
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_bad_key_fails_before_run(tmp_path: Path) -> None:
    bad_key = tmp_path / "bad.key"
    bad_key.write_text("not a key")
    result = cli.invoke(
        app,
        [
            "run",
            "--target",
            "reference-clean",
            "--scenario",
            "salary",
            "--out",
            str(tmp_path / "runs"),
            "--key",
            str(bad_key),
        ],
    )
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 3, combined
    assert "[plant]" not in combined


def test_unwritable_out_exits_3(tmp_path: Path) -> None:
    out_path = tmp_path / "file"
    out_path.write_text("not a directory")
    result = cli.invoke(
        app,
        [
            "run",
            "--target",
            "reference-clean",
            "--scenario",
            "salary",
            "--out",
            str(out_path),
            "--key",
            str(tmp_path / "k.key"),
        ],
    )
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 3, combined
    assert "cannot write report" in combined


def test_index_failure_exits_3_after_report(tmp_path: Path) -> None:
    (tmp_path / "index.sqlite").mkdir()
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 3, combined
    assert "run index update failed" in combined
    run_dir = _only_run_dir(tmp_path)
    assert cli.invoke(app, ["verify", str(run_dir)]).exit_code == 0


def test_jev_without_key_exits_3_before_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = _run(
        tmp_path, "--target", "reference-leaky", "--scenario", "salary", "--judges", "jev"
    )
    assert result.exit_code == 3
    assert "TYPESAFE_API_KEY" in result.output
    assert "[plant]" not in result.output
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "k.key").exists()


def test_openai_without_key_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _run(
        tmp_path, "--target", "reference-leaky", "--scenario", "salary", "--judges", "openai"
    )
    assert result.exit_code == 3
    assert "OPENAI_API_KEY" in result.output


def test_negative_budget_exits_3(tmp_path: Path) -> None:
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary", "--budget", "-1")
    assert result.exit_code == 3
    assert "--budget" in result.output


def test_nan_budget_exits_3(tmp_path: Path) -> None:
    result = _run(
        tmp_path, "--target", "reference-clean", "--scenario", "salary", "--budget", "nan"
    )
    assert result.exit_code == 3


def test_inf_budget_exits_3(tmp_path: Path) -> None:
    result = _run(
        tmp_path, "--target", "reference-clean", "--scenario", "salary", "--budget", "inf"
    )
    assert result.exit_code == 3


def test_duplicate_judge_names_deduplicated(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--target",
        "reference-clean",
        "--scenario",
        "salary",
        "--judges",
        "overlap,overlap",
    )
    assert result.exit_code == 0, result.output
    data = json.loads((_only_run_dir(tmp_path) / "result.json").read_text())
    assert data["judges"] == ["overlap"]


class _Raising:
    name = "overlap"
    evidence = False

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        raise RuntimeError("bad key sk-" + "A" * 30)


def test_run_prints_judge_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(JUDGES, "overlap", _Raising)  # type: ignore[arg-type]
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    assert result.exit_code == 2, result.output
    assert "judge error:" in result.output
    assert "sk-" + "A" * 30 not in result.output


def test_run_prints_judge_cost(tmp_path: Path) -> None:
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary")
    assert "judge cost: $0.0000 of $1.00 budget" in result.output


def test_zero_budget_with_overlap_still_passes(tmp_path: Path) -> None:
    result = _run(tmp_path, "--target", "reference-clean", "--scenario", "salary", "--budget", "0")
    assert result.exit_code == 0, result.output


def test_mem0_without_openai_key_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _run(tmp_path, "--target", "mem0", "--scenario", "salary")
    assert result.exit_code == 3
    assert "OPENAI_API_KEY" in result.output
    assert not (tmp_path / "runs").exists()


def test_mem0_missing_package_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "mem0" else real(name, *a)
    )
    result = _run(tmp_path, "--target", "mem0", "--scenario", "salary")
    assert result.exit_code == 3
    assert "erasewitness[mem0]" in result.output
