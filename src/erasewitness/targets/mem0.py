"""Mem0 (open-source, local) adapter."""

from __future__ import annotations

import importlib.metadata
import os
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from erasewitness.scenario import Scenario
from erasewitness.targets.refagent import openai_answer
from erasewitness.types import Edge, EraseResult, Item, Layer

_DB_TABLES = ("history", "messages")


class Mem0Target:
    name = "mem0"
    tested_versions = ["2.2.1"]

    def __init__(
        self,
        *,
        memory_factory: Callable[[Path, str], Any] | None = None,
        answer: Callable[[str, list[str]], str] | None = None,
        llm_model: str = "gpt-4o-mini",
    ) -> None:
        self._memory_factory = memory_factory
        self._answer = answer
        self.llm_model = llm_model
        self.dir = Path()
        self.user_id = ""
        self.ids: list[str] = []
        self.memory: Any = None

    def _default_factory(self, directory: Path, collection: str) -> Any:
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        from mem0 import Memory  # type: ignore[import-untyped]

        return Memory.from_config(
            {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "path": str(directory / "qd"),
                        "collection_name": collection,
                        "on_disk": True,
                    },
                },
                "llm": {"provider": "openai", "config": {"model": self.llm_model}},
                "history_db_path": str(directory / "history.db"),
            }
        )

    def setup(self, run_id: str) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix=f"ew-{run_id[:40]}-"))
        self.user_id = f"ew-{run_id}"
        self.ids = []
        collection = "ew_" + re.sub(r"[^A-Za-z0-9_]", "_", run_id)
        factory = self._memory_factory or self._default_factory
        self.memory = factory(self.dir, collection)
        if self._answer is None:
            self._answer = openai_answer()

    def version_info(self) -> dict[str, str]:
        try:
            version = importlib.metadata.version("mem0ai")
        except importlib.metadata.PackageNotFoundError:
            version = "not installed"
        return {"mem0ai": version, "llm": self.llm_model, "agent": "gpt-4o-mini"}

    def _add(self, messages: list[dict[str, str]]) -> None:
        result = self.memory.add(messages, user_id=self.user_id)
        for entry in result.get("results", []):
            if entry["id"] not in self.ids:
                self.ids.append(entry["id"])

    def plant(self, text: str) -> None:
        self._add([{"role": "user", "content": text}])

    def exercise(self, turns: list[str]) -> None:
        for turn in turns:
            reply = self.ask(turn)
            self._add([{"role": "user", "content": turn}, {"role": "assistant", "content": reply}])

    def settle(self, timeout_s: float) -> bool:
        return True

    def _store_items(self, hits: list[dict[str, Any]]) -> list[Item]:
        return [Item(Layer.STORE, f"memory:{h['id']}", h["memory"]) for h in hits]

    def snapshot(self) -> list[Item]:
        everything = self.memory.get_all(filters={"user_id": self.user_id})["results"]
        return self._store_items(everything) + self.probe_derived()

    def recorded_edges(self) -> list[Edge]:
        return [Edge(f"memory:{i}", f"history:{i}", "recorded") for i in self.ids]

    def erase(self, scenario: Scenario, strict_items: list[Item] | None) -> EraseResult:
        strict = strict_items is not None
        queries = [scenario.fact.statement, scenario.fact.canary, *scenario.probes.recall]
        deleted: set[str] = set()
        for query in queries:
            if not query:
                continue
            hits = self.memory.search(query, filters={"user_id": self.user_id})["results"]
            for hit in hits:
                self.memory.delete(hit["id"])
                deleted.add(hit["id"])
        if strict:
            self.memory.delete_all(user_id=self.user_id)
        suffix = "; delete_all" if strict else ""
        return EraseResult(
            True,
            f"deleted {len(deleted)} memories via delete(id){suffix}; history.db has no delete API",
        )

    def probe_store(self, query: str) -> list[Item]:
        hits = self.memory.search(query, filters={"user_id": self.user_id})["results"]
        return self._store_items(hits)

    def probe_derived(self) -> list[Item]:
        items: list[Item] = []
        for mem_id in self.ids:
            for n, entry in enumerate(self.memory.history(mem_id)):
                text = " ".join(x for x in (entry.get("old_memory"), entry.get("new_memory")) if x)
                if text:
                    items.append(Item(Layer.DERIVED, f"history:{mem_id}#{n}", text))
        db_path = self.dir / "history.db"
        if db_path.exists():
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                for table in _DB_TABLES:
                    try:
                        rows = con.execute(f"select rowid, * from {table}").fetchall()  # noqa: S608
                    except sqlite3.OperationalError:
                        continue
                    for row in rows:
                        text = " ".join(v for v in row if isinstance(v, str))
                        if text:
                            items.append(Item(Layer.DERIVED, f"db:{table}:{row[0]}", text))
            finally:
                con.close()
        return items

    def ask(self, question: str) -> str:
        assert self._answer is not None
        hits = self.memory.search(question, filters={"user_id": self.user_id})["results"][:5]
        return self._answer(question, [h["memory"] for h in hits])

    def coverage(self) -> dict[Layer, bool]:
        return {layer: True for layer in Layer}

    def cleanup(self) -> list[str]:
        if self.dir.exists() and self.dir.name.startswith("ew-"):
            shutil.rmtree(self.dir, ignore_errors=True)
        return [str(self.dir)] if self.dir.exists() else []
