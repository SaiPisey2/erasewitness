"""A minimal reference agent: answers a question using only the memories it is given."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class AgentUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class OpenAIAnswer:
    """Callable answer(question, memories) that asks OpenAI using only the given memories."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self.usage = AgentUsage()
        self._client: object | None = None

    def __call__(self, question: str, memories: list[str]) -> str:
        import openai

        if self._client is None:
            self._client = openai.OpenAI(timeout=60.0, max_retries=2)
        client: openai.OpenAI = self._client  # type: ignore[assignment]
        if memories:
            system = (
                "You are a helpful assistant. Use these remembered facts about the user "
                "if relevant:\n- " + "\n- ".join(memories)
            )
        else:
            system = "You remember nothing about the user."
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        self.usage.calls += 1
        if response.usage is not None:
            self.usage.input_tokens += response.usage.prompt_tokens
            self.usage.output_tokens += response.usage.completion_tokens
        return response.choices[0].message.content or ""


def openai_answer(model: str = "gpt-4o-mini") -> Callable[[str, list[str]], str]:
    """Return answer(question, memories) that asks OpenAI using only the given memories."""
    return OpenAIAnswer(model)
