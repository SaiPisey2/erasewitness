"""SQLite index of runs, so the CLI and dashboard can list them quickly."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from erasewitness.runner import RunOutcome
from erasewitness.types import Verdict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    target TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    result TEXT NOT NULL,
    leaked INTEGER NOT NULL,
    path TEXT NOT NULL
)
"""
_COLUMNS = ["run_id", "started_at", "target", "scenario_id", "result", "leaked", "path"]


class RunIndex:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(_SCHEMA)

    def add(self, outcome: RunOutcome, run_dir: Path) -> None:
        leaked = sum(p.verdict is Verdict.LEAKED for p in outcome.probes)
        row = (
            outcome.run_id,
            outcome.started_at,
            outcome.target,
            outcome.scenario.id,
            outcome.result.value,
            leaked,
            str(run_dir),
        )
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)", row)

    def list_runs(self) -> list[dict[str, object]]:
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM runs ORDER BY started_at DESC, run_id DESC"
            ).fetchall()
        return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]
