"""A per-run spending cap for paid judges."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.limit_usd < 0:
            raise ValueError("budget must be >= 0")

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.limit_usd

    def allows(self, estimate_usd: float) -> bool:
        if estimate_usd <= 0.0:
            return True
        return not self.exhausted and self.spent_usd + estimate_usd <= self.limit_usd

    def charge(self, amount_usd: float) -> None:
        self.spent_usd += max(0.0, amount_usd)
