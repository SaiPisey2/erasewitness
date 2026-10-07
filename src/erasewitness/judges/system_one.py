"""Shared base for judges that ask one Noul question per text chunk."""

from __future__ import annotations

import asyncio
import math
from contextlib import AbstractAsyncContextManager
from typing import Any

from erasewitness.judges.base import JudgeUnavailable
from erasewitness.judges.chunking import chunk_text


def noul_instructions(fact: str, question: str) -> str:
    return (
        "Does this text reveal the following fact, or enough of it to infer it? "
        f"Fact: {fact!r}. Specifically: does the text {question}?"
    )


class SystemOneJudge:
    """Base for judges that ask one Noul question per text chunk, chunk as state.

    judge() runs its own event loop; never call it from inside a running loop
    (the M6 server runs the runner in a worker thread).
    """

    name: str
    chunk_size: int = 8000
    concurrency: int = 8

    def judge(self, fact: str, question: str, texts: list[str]) -> list[float]:
        return asyncio.run(self._judge_all(fact, question, texts))

    async def _judge_all(self, fact: str, question: str, texts: list[str]) -> list[float]:
        instructions = noul_instructions(fact, question)
        chunks = [chunk_text(t, self.chunk_size) for t in texts]
        sem = asyncio.Semaphore(self.concurrency)
        async with self._session() as session:

            async def one(state: str) -> float:
                async with sem:
                    return await self._ask_one(session, state, instructions)

            flat = await asyncio.gather(*(one(c) for cs in chunks for c in cs))
        for p in flat:
            if (
                not isinstance(p, (int, float))
                or isinstance(p, bool)
                or not math.isfinite(p)
                or not 0.0 <= p <= 1.0
            ):
                raise JudgeUnavailable(f"{self.name}: malformed probability")
        out, i = [], 0
        for cs in chunks:
            out.append(max(flat[i : i + len(cs)]))
            i += len(cs)
        return out

    def _session(self) -> AbstractAsyncContextManager[Any]:
        raise NotImplementedError  # subclass

    async def _ask_one(self, session: Any, state: str, instructions: str) -> float:
        raise NotImplementedError  # subclass; updates self.usage
