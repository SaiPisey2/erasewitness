"""A per-run spending cap for paid judges."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.limit_usd) or self.limit_usd < 0:
            raise ValueError("budget must be a finite number >= 0")

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.limit_usd

    def allows(self, estimate_usd: float) -> bool:
        if estimate_usd <= 0.0:
            return True
        return not self.exhausted and self.spent_usd + estimate_usd <= self.limit_usd

    def charge(self, amount_usd: float) -> None:
        self.spent_usd += max(0.0, amount_usd)


def format_usd(amount: float) -> str:
    """Show sub-cent amounts with four decimals so a $0.002 budget is not shown as $0.00."""
    return f"{amount:.4f}" if amount < 0.01 else f"{amount:.2f}"
