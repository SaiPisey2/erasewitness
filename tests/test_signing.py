import base64
import json
import re
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

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


def test_verify_pinned_ok(tmp_path: Path) -> None:
    run = _signed_dir(tmp_path)
    manifest = json.loads((run / "manifest.json").read_text())
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(manifest["public_key"]))
    expected = fingerprint(public_key)
    result = verify_run(run, expected_fingerprint=expected)
    assert result.ok
    assert result.pinned is True


def test_verify_detects_resigned_with_other_key(tmp_path: Path) -> None:
    key_a, _ = load_or_create_key(tmp_path / "a" / "signing.key")
    run = tmp_path / "run"
    run.mkdir()
    (run / "result.json").write_text('{"result": "PASS"}')
    sign_run(run, key_a)

    # tamper, then re-sign with a fresh, unrelated key
    (run / "result.json").write_text('{"result": "FAIL"}')
    key_b, _ = load_or_create_key(tmp_path / "b" / "signing.key")
    sign_run(run, key_b)

    pinned = verify_run(run, expected_fingerprint=fingerprint(key_a.public_key()))
    assert not pinned.ok
    assert any("does not match expected" in p for p in pinned.problems)

    unpinned = verify_run(run)
    assert unpinned.ok
    assert unpinned.pinned is False


def test_generate_key_refuses_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.key"
    target.write_bytes(b"untouched")
    link = tmp_path / "link.key"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        generate_key(link)
    assert target.read_bytes() == b"untouched"


def test_sign_refuses_symlink(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "result.json").write_text("{}")
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    (run / "link.txt").symlink_to(outside)
    key, _ = load_or_create_key(tmp_path / "k" / "signing.key")
    with pytest.raises(ValueError, match="refusing to sign symlink"):
        sign_run(run, key)


def test_verify_flags_symlink(tmp_path: Path) -> None:
    run = _signed_dir(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    (run / "link.txt").symlink_to(outside)
    problems = verify_run(run).problems
    assert "symlink in run folder: link.txt" in problems


def test_verify_rejects_absolute_manifest_path(tmp_path: Path) -> None:
    run = _signed_dir(tmp_path)
    key, _ = load_or_create_key(tmp_path / "k" / "signing.key")
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["files"]["/etc/hosts"] = "0" * 64
    body = json.dumps(manifest, indent=2, sort_keys=True).encode()
    (run / "manifest.json").write_bytes(body)
    (run / "manifest.sig").write_text(base64.b64encode(key.sign(body)).decode())
    assert "invalid path in manifest: /etc/hosts" in verify_run(run).problems


def test_verify_empty_manifest(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    key, _ = load_or_create_key(tmp_path / "k" / "signing.key")
    sign_run(run, key)
    result = verify_run(run)
    assert not result.ok
    assert "manifest lists no files" in result.problems
