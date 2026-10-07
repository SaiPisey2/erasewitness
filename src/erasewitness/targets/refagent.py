"""A minimal reference agent: answers a question using only the memories it is given."""

from __future__ import annotations

from collections.abc import Callable


def openai_answer(model: str = "gpt-4o-mini") -> Callable[[str, list[str]], str]:
    """Return answer(question, memories) that asks OpenAI using only the given memories."""

    def answer(question: str, memories: list[str]) -> str:
        import openai

        if memories:
            system = (
                "You are a helpful assistant. Use these remembered facts about the user "
                "if relevant:\n- " + "\n- ".join(memories)
            )
        else:
            system = "You remember nothing about the user."
        response = openai.OpenAI().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        return response.choices[0].message.content or ""

    return answer
