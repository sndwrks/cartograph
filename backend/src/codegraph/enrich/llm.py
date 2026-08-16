"""LLM client interface — tests inject fakes; production uses Anthropic."""

from __future__ import annotations

from typing import Protocol

from codegraph.config import get_settings

SUMMARY_MODEL = "claude-sonnet-5"


class LLMClient(Protocol):
    async def complete(self, prompt: str, max_tokens: int = 1024) -> str: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str = SUMMARY_MODEL):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


def build_llm() -> AnthropicLLM:
    api_key = get_settings().ANTHROPIC_API_KEY
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set — required for the summaries, "
            "communities, and docs phases. Set it in .env."
        )
    return AnthropicLLM(api_key)
