"""Turns a RunOutcome into the JSON structures written to the run folder."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

from erasewitness import __version__
from erasewitness.runner import RunOutcome
from erasewitness.types import ItemJudgement, Verdict


def _redact(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def evidence_name(probe_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", probe_id) + ".json"


def _evidence_filenames(probe_ids: Sequence[str]) -> dict[str, str]:
    """Map each probe_id to a unique evidence filename.

    Two probe ids can sanitise to the same name (e.g. "recall:a b" and
    "recall:a_b" both become "recall_a_b.json"); on a collision, later ids
    get "-2", "-3", ... appended before the ".json" suffix so no file is
    silently overwritten.
    """
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for probe_id in probe_ids:
        base = evidence_name(probe_id)
        counts[base] = counts.get(base, 0) + 1
        n = counts[base]
        if n == 1:
            names[probe_id] = base
        else:
            stem = base[: -len(".json")]
            names[probe_id] = f"{stem}-{n}.json"
    return names


def judgement_dict(j: ItemJudgement, *, redact: bool) -> dict[str, Any]:
    code_hit, reason = j.code_hit, j.reason
    if redact and code_hit is not None:
        # The matched value is itself sensitive; keep only the fact that a match happened.
        reason = reason.replace(code_hit, "[redacted]")
        code_hit = "[redacted]"
    return {
        "source": j.item.source,
        "layer": j.item.layer.value,
        "text": _redact(j.item.text) if redact else j.item.text,
        "verdict": j.verdict.value,
        "code_hit": code_hit,
        "votes": j.votes,
        "reason": reason,
    }


def outcome_to_dict(outcome: RunOutcome, *, redact: bool = False) -> dict[str, Any]:
    scenario = outcome.scenario.model_dump(mode="json")
    canonical = json.dumps(scenario, sort_keys=True).encode()
    scenario_sha256 = hashlib.sha256(canonical).hexdigest()
    if redact:
        fact = scenario["fact"]
        fact["statement"] = _redact(fact["statement"])
        fact["plant_as"] = _redact(fact["plant_as"])
        if fact["canary"] is not None:
            fact["canary"] = _redact(fact["canary"])
        fact["sensitive_values"] = [_redact(v) for v in fact["sensitive_values"]]
    names = _evidence_filenames([p.probe_id for p in outcome.probes])
    return {
        "schema": 1,
        "tool": {"name": "erasewitness", "version": __version__},
        "run_id": outcome.run_id,
        "result": outcome.result.value,
        "error": outcome.error,
        "target": outcome.target,
        "versions": outcome.versions,
        "judges": outcome.judges,
        "started_at": outcome.started_at,
        "finished_at": outcome.finished_at,
        "scenario": scenario,
        "scenario_sha256": scenario_sha256,
        "redacted": redact,
        "probes": [
            {
                "probe_id": p.probe_id,
                "layer": p.layer.value,
                "verdict": p.verdict.value,
                "reason": p.reason,
                "evidence": f"evidence/{names[p.probe_id]}",
            }
            for p in outcome.probes
        ],
        "snapshot": [judgement_dict(j, redact=redact) for j in outcome.snapshot],
        "collateral": outcome.collateral,
        "findings": outcome.findings,
        "not_covered": outcome.not_covered,
        "leftovers": outcome.leftovers,
        "summary": {v.value.lower(): sum(p.verdict is v for p in outcome.probes) for v in Verdict},
    }


def evidence_files(outcome: RunOutcome, *, redact: bool = False) -> dict[str, dict[str, Any]]:
    names = _evidence_filenames([p.probe_id for p in outcome.probes])
    return {
        names[p.probe_id]: {
            "probe_id": p.probe_id,
            "before": [judgement_dict(j, redact=redact) for j in p.before],
            "after": [judgement_dict(j, redact=redact) for j in p.after],
            "control": [judgement_dict(j, redact=redact) for j in p.control],
        }
        for p in outcome.probes
    }
