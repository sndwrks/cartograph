"""LLM client interface — tests inject fakes; production uses Anthropic."""

from __future__ import annotations

from typing import Protocol

from cartograph.config import get_settings

SUMMARY_MODEL = "claude-sonnet-5"


def require_api_key(purpose: str) -> str:
    api_key = get_settings().ANTHROPIC_API_KEY
    if not api_key:
        raise SystemExit(
            f"ANTHROPIC_API_KEY is not set — required for {purpose}. Set it in .env."
        )
    return api_key


def flatten_text(content) -> str:
    """Join a response's text blocks — the one true reading of message content,
    shared with the batch client so batch and sync summaries are identical."""
    return "".join(block.text for block in content if block.type == "text").strip()


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
        return flatten_text(response.content)


def build_llm() -> AnthropicLLM:
    return AnthropicLLM(
        require_api_key("the summaries, communities, and docs phases")
    )
