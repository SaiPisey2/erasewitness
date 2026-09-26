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
    if path.exists() and not force:
        raise FileExistsError(str(path))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
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
    rels = (p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file())
    return sorted(r for r in rels if r not in {_MANIFEST, _SIGNATURE})


def sign_run(run_dir: Path, key: Ed25519PrivateKey) -> None:
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


def verify_run(run_dir: Path) -> VerifyResult:
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
    for rel, digest in sorted(files.items()):
        path = run_dir / rel
        if not path.is_file():
            problems.append(f"missing file: {rel}")
        elif _sha256(path) != digest:
            problems.append(f"modified file: {rel}")
    for rel in _files(run_dir):
        if rel not in files:
            problems.append(f"unlisted file: {rel}")
    return VerifyResult(not problems, fingerprint(public_key), len(files), problems)
