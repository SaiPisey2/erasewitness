"""In-process reference memory systems with known behaviour, used to test the harness."""

from __future__ import annotations

import re
from typing import Literal

from erasewitness.scenario import Scenario
from erasewitness.types import Edge, EraseResult, Item, Layer

Mode = Literal["clean", "leaky", "overdelete"]
_DIGIT_TOKEN = re.compile(r"\S*\d\S*")


def _strip_digit_tokens(text: str) -> str:
    return " ".join(_DIGIT_TOKEN.sub("", text).split())


class ReferenceTarget:
    tested_versions = ["builtin"]

    def __init__(self, mode: Mode, *, settle_ok: bool = True, fail_erase: bool = False) -> None:
        self.name = f"reference-{mode}"
        self.mode = mode
        self._settle_ok = settle_ok
        self._fail_erase = fail_erase
        self.memories: dict[str, str] = {}
        self.history: list[tuple[str, str]] = []
        self.summary: str | None = None
        self._next = 0

    def _add(self, text: str) -> None:
        self._next += 1
        mem_id = f"m{self._next}"
        self.memories[mem_id] = text
        self.history.append((mem_id, text))

    def setup(self, run_id: str) -> None:
        if self.mode == "overdelete":
            self._add("User prefers dark mode.")

    def version_info(self) -> dict[str, str]:
        return {"reference": "builtin", "mode": self.mode}

    def plant(self, text: str) -> None:
        self._add(text)

    def exercise(self, turns: list[str]) -> None:
        if self.memories:
            rewritten = " ".join(_strip_digit_tokens(t) for t in self.memories.values())
            self.summary = f"Summary of past chats: {rewritten}"

    def settle(self, timeout_s: float) -> bool:
        return self._settle_ok

    def snapshot(self) -> list[Item]:
        stored = [Item(Layer.STORE, f"memory:{k}", v) for k, v in self.memories.items()]
        return stored + self.probe_derived()

    def recorded_edges(self) -> list[Edge]:
        return [Edge(f"memory:{k}", f"history:{k}", "recorded") for k, _ in self.history]

    def erase(self, scenario: Scenario, strict_items: list[Item] | None) -> EraseResult:
        if self._fail_erase:
            raise RuntimeError("reference erase failure")
        if self.mode == "overdelete":
            self.memories.clear()
            self.history.clear()
            self.summary = None
            return EraseResult(True, "deleted all memories")
        needle = scenario.fact.canary or scenario.fact.plant_as
        doomed = [k for k, v in self.memories.items() if needle in v]
        for key in doomed:
            del self.memories[key]
        if self.mode == "clean":
            self.history = [(k, v) for k, v in self.history if k not in doomed]
            self.summary = None
        if strict_items:
            sources = {item.source for item in strict_items}
            self.history = [(k, v) for k, v in self.history if f"history:{k}" not in sources]
            for key in [k for k in self.memories if f"memory:{k}" in sources]:
                del self.memories[key]
            if "summary" in sources:
                self.summary = None
        return EraseResult(True, f"deleted {len(doomed)} memories")

    def probe_store(self, query: str) -> list[Item]:
        wanted = query.lower()
        return [
            Item(Layer.STORE, f"memory:{k}", v)
            for k, v in self.memories.items()
            if wanted in v.lower()
        ]

    def probe_derived(self) -> list[Item]:
        items = [Item(Layer.DERIVED, f"history:{k}", v) for k, v in self.history]
        if self.summary is not None:
            items.append(Item(Layer.DERIVED, "summary", self.summary))
        return items

    def ask(self, question: str) -> str:
        if not self.memories:
            return "I don't have that information."
        return "Based on what you told me: " + " ".join(self.memories.values())

    def coverage(self) -> dict[Layer, bool]:
        return {layer: True for layer in Layer}

    def cleanup(self) -> list[str]:
        self.memories.clear()
        self.history.clear()
        self.summary = None
        return []
