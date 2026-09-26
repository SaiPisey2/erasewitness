"""Writes and signs a run folder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from erasewitness.report.data import evidence_files, outcome_to_dict
from erasewitness.report.html import render_html
from erasewitness.report.junit import render_junit
from erasewitness.report.secret_scan import scan
from erasewitness.runner import RunOutcome
from erasewitness.signing import sign_run


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_run(
    outcome: RunOutcome, out_root: Path, key: Ed25519PrivateKey, *, redact: bool = False
) -> Path:
    data = outcome_to_dict(outcome, redact=redact)
    evidence = evidence_files(outcome, redact=redact)
    files = {
        "result.json": _dump(data),
        "report.html": render_html(data, evidence),
        "junit.xml": render_junit(data),
        **{f"evidence/{name}": _dump(body) for name, body in evidence.items()},
    }
    scan(files)  # before anything touches the disk
    run_dir = out_root / outcome.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    for rel, text in files.items():
        path = run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sign_run(run_dir, key)
    return run_dir
