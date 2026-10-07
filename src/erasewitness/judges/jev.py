"""Jev (TypeSafe AI) judge: one calibrated Noul probability per text chunk."""

from __future__ import annotations

import os
from contextlib import AbstractAsyncContextManager
from typing import Any

from erasewitness.judges.base import JudgeConfigError, JudgeUsage
from erasewitness.judges.chunking import chunk_text
from erasewitness.judges.pricing import JEV_INPUT_PER_M, cost, estimate_tokens
from erasewitness.judges.system_one import SystemOneJudge, noul_instructions


class JevJudge(SystemOneJudge):
    name = "jev"
    evidence = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "jev-latest",
        transport: Any = None,
        max_retries: int = 2,
    ) -> None:
        key = (api_key or os.environ.get("TYPESAFE_API_KEY") or "").strip()
        if not key:
            raise JudgeConfigError("TYPESAFE_API_KEY is not set")
        try:
            import typesafe_sdk
        except ImportError:
            raise JudgeConfigError(
                "the jev judge needs: pip install 'erasewitness[judges]'"
            ) from None
        self._sdk = typesafe_sdk
        self._key = key
        self._model = model
        self._transport = transport
        self._max_retries = max_retries
        self.usage = JudgeUsage(model=model)

    def _session(self) -> AbstractAsyncContextManager[Any]:
        sdk = self._sdk
        client: AbstractAsyncContextManager[Any] = sdk.AsyncTypeSafeClient(
            api_key=self._key,
            model=self._model,
            retry=sdk.RetryPolicy(max_retries=self._max_retries),
            transport=self._transport,
        )
        return client

    async def _ask_one(self, session: Any, state: str, instructions: str) -> float:
        resp = await session.system_one(state, {"q": self._sdk.Noul(instructions=instructions)})
        p = float(resp.answers["q"].noul)
        in_t = resp.usage.input_tokens or 0
        out_t = resp.usage.output_tokens or 0
        self.usage.calls += 1
        self.usage.model = resp.model or self.usage.model
        self.usage.input_tokens += in_t
        self.usage.output_tokens += out_t
        self.usage.cost_usd += cost(in_t, out_t, JEV_INPUT_PER_M, 0.0)
        return p

    def estimate_cost(self, fact: str, question: str, texts: list[str]) -> float:
        instructions = noul_instructions(fact, question)
        tokens = sum(
            estimate_tokens(chunk + instructions) + 50
            for t in texts
            for chunk in chunk_text(t, self.chunk_size)
        )
        return tokens * JEV_INPUT_PER_M / 1_000_000
