import json
import re
import stat
from pathlib import Path

import pytest

from erasewitness.signing import (
    fingerprint,
    generate_key,
    load_or_create_key,
    sign_run,
    verify_run,
)


def _signed_dir(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "evidence").mkdir(parents=True)
    (run / "result.json").write_text('{"result": "PASS"}')
    (run / "evidence" / "derived.json").write_text("{}")
    key, _ = load_or_create_key(tmp_path / "k" / "signing.key")
    sign_run(run, key)
    return run


def test_generate_key_mode_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "keys" / "signing.key"
    generate_key(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        generate_key(path)
    generate_key(path, force=True)


def test_load_or_create(tmp_path: Path) -> None:
    path = tmp_path / "signing.key"
    k1, created1 = load_or_create_key(path)
    k2, created2 = load_or_create_key(path)
    assert (created1, created2) == (True, False)
    assert fingerprint(k1.public_key()) == fingerprint(k2.public_key())
    assert re.fullmatch(r"[0-9a-f]{4}(:[0-9a-f]{4}){3}", fingerprint(k1.public_key()))


def test_verify_ok(tmp_path: Path) -> None:
    result = verify_run(_signed_dir(tmp_path))
    assert result.ok
    assert result.files_checked == 2
    assert result.problems == []


def test_verify_detects_modified_file(tmp_path: Path) -> None:
    run = _signed_dir(tmp_path)
    (run / "result.json").write_text('{"result": "FAIL"}')
    result = verify_run(run)
    assert not result.ok
    assert result.problems == ["modified file: result.json"]


def test_verify_detects_extra_and_missing(tmp_path: Path) -> None:
    run = _signed_dir(tmp_path)
    (run / "evidence" / "derived.json").unlink()
    (run / "extra.txt").write_text("x")
    problems = verify_run(run).problems
    assert "missing file: evidence/derived.json" in problems
    assert "unlisted file: extra.txt" in problems


def test_verify_detects_edited_manifest(tmp_path: Path) -> None:
    run = _signed_dir(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["files"]["result.json"] = "0" * 64
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    assert "signature does not match manifest" in verify_run(run).problems


def test_verify_without_manifest(tmp_path: Path) -> None:
    result = verify_run(tmp_path)
    assert not result.ok
    assert result.problems[0].startswith("cannot read manifest")
