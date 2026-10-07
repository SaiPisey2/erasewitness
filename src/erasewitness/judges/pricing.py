"""Token prices (USD per 1M tokens), verified 2026-10-07. Re-check before publishing results."""

from __future__ import annotations

from erasewitness.judges.base import JudgeConfigError

JEV_INPUT_PER_M = 0.042
OPENAI_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (1.25, 10.00),
}


def openai_price(model: str) -> tuple[float, float]:
    try:
        return OPENAI_PRICES[model]
    except KeyError:
        raise JudgeConfigError(f"no price known for OpenAI model '{model}'") from None


def cost(input_tokens: int, output_tokens: int, in_per_m: float, out_per_m: float) -> float:
    return (input_tokens * in_per_m + output_tokens * out_per_m) / 1_000_000


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1
