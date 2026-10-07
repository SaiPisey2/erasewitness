"""OpenAI judge: a Noul probability per text chunk, via the System One adapter."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from erasewitness.judges.base import JudgeConfigError, JudgeUnavailable, JudgeUsage
from erasewitness.judges.chunking import chunk_text
from erasewitness.judges.pricing import cost, estimate_tokens, openai_price
from erasewitness.judges.system_one import SystemOneJudge, noul_instructions


class OpenAIJudge(SystemOneJudge):
    name = "openai"
    evidence = True

    def __init__(self, *, model: str | None = None, provider: Any = None) -> None:
        self.model = model or os.environ.get("ERASEWITNESS_OPENAI_MODEL") or "gpt-5-mini"
        self._price = openai_price(self.model)
        try:
            import openai
            import system_one_adapter
            import typesafe_sdk
        except ImportError:
            raise JudgeConfigError(
                "the openai judge needs: pip install 'erasewitness[judges]'"
            ) from None
        if provider is None and not os.environ.get("OPENAI_API_KEY", "").strip():
            raise JudgeConfigError("OPENAI_API_KEY is not set")
        self._adapter = system_one_adapter
        self._auth_errors: tuple[type[BaseException], ...] = (
            openai.AuthenticationError,
            typesafe_sdk.TypeSafeAuthenticationError,
        )
        self._provider = provider
        self.usage = JudgeUsage(model=self.model)

    def _session(self) -> AbstractAsyncContextManager[Any]:
        return self._open_client()

    @asynccontextmanager
    async def _open_client(self) -> AsyncIterator[Any]:
        client = self._adapter.AsyncSystemOneAdapterClient(
            structured_outputs=True,
            llm_answer_mode="probabilities",
            normalize_probabilities=True,
            provider=None if self._provider else "openai",
            model=self._provider if self._provider else self.model,
        )
        try:
            yield client
        finally:
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if close is not None:
                await close()

    async def _ask_one(self, session: Any, state: str, instructions: str) -> float:
        try:
            resp = await session.system_one(
                state, {"q": self._adapter.Noul(instructions=instructions)}
            )
        except self._auth_errors:
            raise JudgeUnavailable("openai: authentication failed") from None
        p = float(resp.answers["q"].noul)
        in_t = resp.usage.input_tokens_total or 0
        out_t = resp.usage.output_tokens_total or 0
        self.usage.calls += 1
        self.usage.input_tokens += in_t
        self.usage.output_tokens += out_t
        self.usage.cost_usd += cost(in_t, out_t, *self._price)
        return p

    def estimate_cost(self, fact: str, question: str, texts: list[str]) -> float:
        instructions = noul_instructions(fact, question)
        in_t = out_t = 0
        for t in texts:
            for chunk in chunk_text(t, self.chunk_size):
                in_t += estimate_tokens(chunk + instructions) + 200
                out_t += 600
        return cost(in_t, out_t, *self._price)
