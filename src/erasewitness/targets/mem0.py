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

from erasewitness.judges.pricing import cost, openai_price
from erasewitness.scenario import Scenario
from erasewitness.targets.refagent import openai_answer
from erasewitness.types import Edge, EraseResult, Item, Layer

_DB_TABLES = ("history", "messages")
_TEXT_COLUMNS = {"old_memory", "new_memory", "content", "memory", "text"}
_TOP_K = 10
_THRESHOLD = 0.3


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
        os.environ["MEM0_TELEMETRY"] = "False"
        os.environ.setdefault("MEM0_DIR", str(self.dir / "mem0home"))
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
        # The erase must be blind to the probes: it searches only the fact statement.
        hits = self.memory.search(
            scenario.fact.statement,
            filters={"user_id": self.user_id},
            top_k=_TOP_K,
            threshold=_THRESHOLD,
        )["results"]
        deleted: dict[str, float | None] = {}
        for hit in hits:
            self.memory.delete(hit["id"])
            deleted[hit["id"]] = hit.get("score")
        strict_ids = [
            item.source.removeprefix("memory:")
            for item in strict_items or []
            if item.source.startswith("memory:")
        ]
        for mem_id in strict_ids:
            if mem_id not in deleted:
                self.memory.delete(mem_id)
                deleted[mem_id] = None
        scores = " ".join(
            f"{k[:8]}={'n/a' if v is None else f'{v:.2f}'}" for k, v in deleted.items()
        )
        return EraseResult(
            True,
            f"app-level search-delete on the fact statement (top_k={_TOP_K}, "
            f"threshold={_THRESHOLD}): deleted {len(deleted)} memories: {scores}; "
            "history has no per-fact delete API (only reset())",
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
                    columns = [r[1] for r in con.execute(f"pragma table_info({table})")]
                    wanted = [i for i, c in enumerate(columns) if c in _TEXT_COLUMNS]
                    if not wanted:
                        continue
                    for row in con.execute(f"select rowid, * from {table}").fetchall():  # noqa: S608
                        text = " | ".join(
                            row[i + 1] for i in wanted if isinstance(row[i + 1], str) and row[i + 1]
                        )
                        if text:
                            items.append(Item(Layer.DERIVED, f"db:{table}:{row[0]}", text))
            finally:
                con.close()
        return items

    def notes(self) -> list[str]:
        usage = getattr(self._answer, "usage", None)
        calls = getattr(usage, "calls", 0)
        tokens_in = getattr(usage, "input_tokens", 0)
        tokens_out = getattr(usage, "output_tokens", 0)
        in_price, out_price = openai_price("gpt-4o-mini")
        spend = cost(tokens_in, tokens_out, in_price, out_price)
        return [
            f"reference agent (gpt-4o-mini): {calls} calls, {tokens_in} input / "
            f"{tokens_out} output tokens, about ${spend:.4f} (not counted in the judge budget)",
            "mem0 internal LLM (gpt-4o-mini) and embedder (text-embedding-3-small) "
            "calls are not metered",
            "qdrant on-disk files are not probed",
        ]

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
