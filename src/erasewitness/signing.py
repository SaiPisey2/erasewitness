"""ed25519 signing of run folders. Proves files were not altered after the run."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

DEFAULT_KEY_PATH = Path.home() / ".erasewitness" / "signing.key"
_MANIFEST = "manifest.json"
_SIGNATURE = "manifest.sig"


def generate_key(path: Path, *, force: bool = False) -> Ed25519PrivateKey:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if force:
        path.unlink(missing_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # O_EXCL closes the check-then-create race: the OS rejects the open atomically
    # if anything (including a symlink) already occupies the path. O_NOFOLLOW is
    # defense in depth on platforms that provide it.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    os.chmod(path, 0o600)
    return key


def load_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an ed25519 private key")
    return key


def load_or_create_key(path: Path) -> tuple[Ed25519PrivateKey, bool]:
    if path.exists():
        return load_key(path), False
    return generate_key(path), True


def _raw(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(public_key: Ed25519PublicKey) -> str:
    digest = hashlib.sha256(_raw(public_key)).hexdigest()[:16]
    return ":".join(digest[i : i + 4] for i in range(0, 16, 4))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(run_dir: Path) -> list[str]:
    rels = (
        p.relative_to(run_dir).as_posix()
        for p in run_dir.rglob("*")
        if p.is_file() and not p.is_symlink()
    )
    return sorted(r for r in rels if r not in {_MANIFEST, _SIGNATURE})


def _symlinks(run_dir: Path) -> list[str]:
    return sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_symlink())


def _unsafe_relpath(run_dir: Path, rel: str) -> bool:
    """True if `rel` is absolute, escapes `run_dir` via "..", or resolves outside it."""
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return True
    try:
        resolved = (run_dir / rel).resolve()
        resolved.relative_to(run_dir.resolve())
    except ValueError:
        return True
    return False


def sign_run(run_dir: Path, key: Ed25519PrivateKey) -> None:
    symlinks = _symlinks(run_dir)
    if symlinks:
        raise ValueError(f"refusing to sign symlink: {symlinks[0]}")
    manifest = {
        "version": 1,
        "algorithm": "ed25519",
        "public_key": base64.b64encode(_raw(key.public_key())).decode(),
        "files": {rel: _sha256(run_dir / rel) for rel in _files(run_dir)},
    }
    body = json.dumps(manifest, indent=2, sort_keys=True).encode()
    (run_dir / _MANIFEST).write_bytes(body)
    (run_dir / _SIGNATURE).write_text(base64.b64encode(key.sign(body)).decode())


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    fingerprint: str | None
    files_checked: int
    problems: list[str]
    pinned: bool = False


def verify_run(run_dir: Path, expected_fingerprint: str | None = None) -> VerifyResult:
    try:
        body = (run_dir / _MANIFEST).read_bytes()
        signature = base64.b64decode((run_dir / _SIGNATURE).read_text())
    except (OSError, ValueError) as exc:
        return VerifyResult(False, None, 0, [f"cannot read manifest or signature: {exc}"])
    try:
        manifest = json.loads(body)
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(manifest["public_key"]))
        files: dict[str, str] = manifest["files"]
    except (ValueError, KeyError, TypeError) as exc:
        return VerifyResult(False, None, 0, [f"malformed manifest: {exc}"])

    problems: list[str] = []
    try:
        public_key.verify(signature, body)
    except InvalidSignature:
        problems.append("signature does not match manifest")

    if not files:
        problems.append("manifest lists no files")

    for rel, digest in sorted(files.items()):
        if _unsafe_relpath(run_dir, rel):
            problems.append(f"invalid path in manifest: {rel}")
            continue
        path = run_dir / rel
        if not path.is_file():
            problems.append(f"missing file: {rel}")
        elif _sha256(path) != digest:
            problems.append(f"modified file: {rel}")
    for rel in _files(run_dir):
        if rel not in files:
            problems.append(f"unlisted file: {rel}")
    for rel in _symlinks(run_dir):
        problems.append(f"symlink in run folder: {rel}")

    actual_fingerprint = fingerprint(public_key)
    pinned = False
    if expected_fingerprint is not None:
        if actual_fingerprint != expected_fingerprint:
            problems.append(
                f"signer {actual_fingerprint} does not match expected {expected_fingerprint}"
            )
        else:
            pinned = True

    return VerifyResult(not problems, actual_fingerprint, len(files), problems, pinned)
