import json
from typing import Any

import pytest
from system_one_adapter.providers import ProviderResult
from typesafe_sdk import TypeSafeError

from erasewitness.judges.base import JudgeConfigError
from erasewitness.judges.openai_judge import OpenAIJudge


@pytest.fixture(autouse=True)
def _no_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ERASEWITNESS_OPENAI_MODEL", raising=False)


class FakeProvider:
    model_name = "gpt-5-mini"

    def __init__(self, prob: float = 0.8, fail: bool = False) -> None:
        self.prob = prob
        self.fail = fail
        self.calls = 0

    async def request(self, messages: Any, *, schema: Any, structured: Any) -> ProviderResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("upstream 500")
        return ProviderResult(
            text=json.dumps({"answers": {"q": self.prob}}), input_tokens=1000, output_tokens=300
        )

    def translate_error(self, error: Exception) -> TypeSafeError:
        return TypeSafeError(str(error))


def test_openai_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeConfigError, match="OPENAI_API_KEY"):
        OpenAIJudge()


def test_openai_unknown_model_rejected() -> None:
    with pytest.raises(JudgeConfigError, match="gpt-unknown"):
        OpenAIJudge(model="gpt-unknown", provider=FakeProvider())


def test_openai_judges_and_costs() -> None:
    fake = FakeProvider(prob=0.8)
    judge = OpenAIJudge(provider=fake)
    assert judge.judge("fact", "q", ["a", "b"]) == [0.8, 0.8]
    assert fake.calls == 2
    assert judge.usage.calls == 2
    assert judge.usage.input_tokens == 2000
    assert judge.usage.output_tokens == 600
    assert judge.usage.cost_usd == pytest.approx((2000 * 0.25 + 600 * 2.00) / 1e6)


def test_openai_error_degrades() -> None:
    judge = OpenAIJudge(provider=FakeProvider(fail=True))
    with pytest.raises(RuntimeError, match="upstream 500"):
        judge.judge("fact", "q", ["a"])


def test_openai_model_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERASEWITNESS_OPENAI_MODEL", "gpt-5-nano")
    assert OpenAIJudge(provider=FakeProvider()).usage.model == "gpt-5-nano"


class _AuthFailProvider(FakeProvider):
    async def request(self, messages: Any, *, schema: Any, structured: Any) -> ProviderResult:
        from typesafe_sdk import TypeSafeAuthenticationError

        raise TypeSafeAuthenticationError(
            401, None, {}, "Incorrect API key provided: sk-proj-****abcd"
        )


def test_openai_auth_error_hides_key_fragment() -> None:
    from erasewitness.judges.base import JudgeUnavailable

    judge = OpenAIJudge(provider=_AuthFailProvider())
    with pytest.raises(JudgeUnavailable) as info:
        judge.judge("fact", "q", ["a"])
    assert "abcd" not in str(info.value)
    assert str(info.value) == "openai: authentication failed"
