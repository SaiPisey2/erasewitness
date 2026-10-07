import pytest

from erasewitness.judges.base import JudgeConfigError
from erasewitness.judges.budget import Budget
from erasewitness.judges.pricing import cost, estimate_tokens, openai_price


def test_budget_allows_and_charges() -> None:
    b = Budget(limit_usd=1.0)
    assert b.allows(0.6)
    b.charge(0.6)
    assert not b.allows(0.5)
    assert b.allows(0.4)
    b.charge(0.5)
    assert b.exhausted
    assert not b.allows(0.01)
    assert b.allows(0.0)


def test_budget_rejects_negative_limit() -> None:
    with pytest.raises(ValueError):
        Budget(limit_usd=-1)


def test_pricing() -> None:
    assert openai_price("gpt-5-mini") == (0.25, 2.00)
    assert cost(1_000_000, 1_000_000, 0.25, 2.00) == pytest.approx(2.25)
    assert estimate_tokens("abcd" * 10) == 11
    with pytest.raises(JudgeConfigError, match="gpt-unknown"):
        openai_price("gpt-unknown")
