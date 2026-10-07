import subprocess
import sys
from pathlib import Path
from typing import Any

from erasewitness.judges.overlap import OverlapJudge
from erasewitness.judges.panel import Panel
from erasewitness.runner import RunConfig, Runner
from erasewitness.scenario import Scenario
from erasewitness.targets.mem0 import Mem0Target
from erasewitness.types import Layer, RunResult, Verdict


class FakeMemory:
    """Mimics mem0 2.2.1: delete() removes from search but history keeps the text."""

    def __init__(self, root: Path, collection: str) -> None:
        self.mem: dict[str, str] = {}
        self.hist: dict[str, list[dict[str, Any]]] = {}
        self.n = 0
        self.queries: list[str] = []

    def add(self, messages: list[dict[str, str]], user_id: str) -> dict[str, Any]:
        text = messages[0]["content"]
        if "salary" not in text.lower():
            return {"results": []}
        self.n += 1
        mid = f"m{self.n}"
        self.mem[mid] = f"User says: {text}"
        self.hist[mid] = [{"event": "ADD", "old_memory": None, "new_memory": self.mem[mid]}]
        return {"results": [{"id": mid, "memory": self.mem[mid], "event": "ADD"}]}

    def search(self, query: str, filters: dict[str, str], **kwargs: Any) -> dict[str, Any]:
        self.queries.append(query)
        words = query.lower().split()
        hits = [
            {"id": k, "memory": v}
            for k, v in self.mem.items()
            if any(w in v.lower() for w in words)
        ]
        return {"results": hits}

    def get_all(self, filters: dict[str, str]) -> dict[str, Any]:
        return {"results": [{"id": k, "memory": v} for k, v in self.mem.items()]}

    def delete(self, memory_id: str) -> None:
        if memory_id in self.mem:
            self.hist[memory_id].append(
                {"event": "DELETE", "old_memory": self.mem.pop(memory_id), "new_memory": None}
            )

    def delete_all(self, user_id: str) -> None:
        for k in list(self.mem):
            self.delete(k)

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        return self.hist.get(memory_id, [])


def _answer(question: str, memories: list[str]) -> str:
    return " ".join(memories) if memories else "I don't know anything about you."


def _target() -> Mem0Target:
    return Mem0Target(memory_factory=FakeMemory, answer=_answer)


def test_mem0_history_leak_is_reported(salary: Scenario) -> None:
    outcome = Runner(_target, Panel([OverlapJudge()])).run(salary, run_id="run-1")
    verdicts = {p.probe_id: p.verdict for p in outcome.probes}
    assert outcome.result is RunResult.FAIL
    assert verdicts["derived"] is Verdict.LEAKED
    assert verdicts["recall:salary"] is Verdict.CLEAN
    derived = next(p for p in outcome.probes if p.probe_id == "derived")
    leaked = [j.item.source for j in derived.after if j.verdict is Verdict.LEAKED]
    assert any(s.startswith("history:") for s in leaked)


def test_mem0_cleanup_removes_temp_dir() -> None:
    target = _target()
    target.setup("run-2")
    d = target.dir
    assert d.exists() and d.name.startswith("ew-")
    assert target.cleanup() == []
    assert not d.exists()


def test_mem0_strict_still_leaks_history(salary: Scenario) -> None:
    outcome = Runner(_target, Panel([OverlapJudge()]), RunConfig(strict=True)).run(
        salary, run_id="run-3"
    )
    assert outcome.result is RunResult.FAIL


def test_mem0_reads_history_db_rows() -> None:
    import sqlite3

    target = _target()
    target.setup("run-4")
    con = sqlite3.connect(target.dir / "history.db")
    con.execute("create table messages (id text, role text, content text)")
    con.execute("insert into messages values ('1', 'user', 'My salary is 42 LPA.')")
    con.commit()
    con.close()
    items = target.probe_derived()
    assert any(i.source.startswith("db:messages:") and "42 LPA" in i.text for i in items)
    assert all(i.layer is Layer.DERIVED for i in items)
    target.cleanup()


def test_import_without_mem0_installed() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, erasewitness.targets; assert 'mem0' not in sys.modules",
        ],
        check=True,
    )


def test_erase_does_not_use_probe_queries(salary: Scenario) -> None:
    target = _target()
    target.setup("run-5")
    target.plant(salary.fact.plant_as)
    fake: FakeMemory = target.memory
    fake.queries.clear()
    target.erase(salary, None)
    assert fake.queries == [salary.fact.statement]
    assert not set(fake.queries) & set(salary.probes.recall)
    target.cleanup()


HOLD: list[FakeMemory] = []


def _seeded(root: Path, collection: str) -> FakeMemory:
    fake = FakeMemory(root, collection)
    fake.mem["hike"] = "User likes hiking"
    fake.hist["hike"] = [{"event": "ADD", "old_memory": None, "new_memory": "User likes hiking"}]
    HOLD.append(fake)
    return fake


def test_strict_deletes_only_flagged_memories(salary: Scenario) -> None:
    outcome = Runner(
        lambda: Mem0Target(memory_factory=_seeded, answer=_answer),
        Panel([OverlapJudge()]),
        RunConfig(strict=True),
    ).run(salary, run_id="run-6")
    assert "hike" in HOLD[0].mem
    assert outcome.collateral == []


def test_mem0_notes_disclose_unmetered_spend(salary: Scenario) -> None:
    outcome = _run_default(salary)
    assert any(f.startswith("note: mem0 internal LLM") for f in outcome.findings)


def _run_default(salary: Scenario) -> Any:
    return Runner(_target, Panel([OverlapJudge()])).run(salary, run_id="run-7")
