import json
from collections.abc import Callable

import httpx2
import pytest

from erasewitness.judges.base import JudgeConfigError
from erasewitness.judges.jev import JevJudge


def _transport(
    prob_for: Callable[[str], float], seen: list[dict[str, object]], status: int = 200
) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append(body)
        if status != 200:
            return httpx2.Response(status, json={"detail": {"error_type": "x", "message": "no"}})
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {"q": {"type": "noul", "noul": prob_for(body["state"])}},
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        )

    return httpx2.MockTransport(handler)


def test_jev_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JudgeConfigError, match="TYPESAFE_API_KEY"):
        JevJudge()


def test_jev_judges_each_text_and_tracks_usage() -> None:
    seen: list[dict[str, object]] = []
    judge = JevJudge(
        api_key="test-key-value",
        transport=_transport(lambda s: 0.9 if "salary" in s else 0.1, seen),
    )
    probs = judge.judge("My salary is 42 LPA.", "reveals the salary", ["salary summary", "weather"])
    assert probs == [0.9, 0.1]
    assert len(seen) == 2
    assert judge.usage.calls == 2
    assert judge.usage.model == "jev-1.13.0"
    assert judge.usage.input_tokens == 200
    assert judge.usage.cost_usd == pytest.approx(200 * 0.042 / 1e6)
    questions = seen[0]["questions"]
    assert isinstance(questions, dict)
    assert "My salary is 42 LPA." in questions["q"]["instructions"]


def test_jev_chunks_long_text_and_takes_max() -> None:
    seen: list[dict[str, object]] = []
    long_text = "a" * 8000 + "salary" + "b" * 100
    judge = JevJudge(
        api_key="test-key-value",
        transport=_transport(lambda s: 0.95 if "salary" in s else 0.05, seen),
    )
    assert judge.judge("fact", "q", [long_text]) == [0.95]
    assert len(seen) == 2
    assert judge.usage.calls == 2


def test_jev_auth_error_degrades() -> None:
    judge = JevJudge(api_key="test-key-value", transport=_transport(lambda s: 0.5, [], status=401))
    with pytest.raises(Exception) as info:
        judge.judge("fact", "q", ["text"])
    assert "test-key-value" not in str(info.value)


def test_jev_estimate_is_positive_and_small() -> None:
    judge = JevJudge(api_key="test-key-value", transport=_transport(lambda s: 0.5, []))
    est = judge.estimate_cost("fact", "q", ["x" * 4000])
    assert 0 < est < 0.001
