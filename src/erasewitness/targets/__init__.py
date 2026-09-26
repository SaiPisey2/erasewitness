"""Registry of memory-system adapters."""

from __future__ import annotations

from collections.abc import Callable

from erasewitness.targets.base import Target
from erasewitness.targets.reference import ReferenceTarget

TARGETS: dict[str, Callable[[], Target]] = {
    "reference-clean": lambda: ReferenceTarget("clean"),
    "reference-leaky": lambda: ReferenceTarget("leaky"),
    "reference-overdelete": lambda: ReferenceTarget("overdelete"),
}


def create_target(name: str) -> Target:
    return TARGETS[name]()


__all__ = ["TARGETS", "Target", "create_target"]
