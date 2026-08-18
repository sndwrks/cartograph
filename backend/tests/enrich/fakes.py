"""Fake LLM/embedding clients — enrichment tests never hit real APIs."""

import hashlib
import re

from cartograph.models import EMBED_DIM


class FakeLLM:
    def __init__(self):
        self.calls: list[str] = []

    async def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        self.calls.append(prompt)
        if '"label"' in prompt:
            return '{"label": "Test Cluster", "summary": "A test cluster."}'
        if '"references"' in prompt:
            # echo back every candidate offered in the prompt
            qnames = re.findall(r"^- (\S+)$", prompt, re.MULTILINE)
            joined = ", ".join(f'"{qname}"' for qname in qnames)
            return f'{{"references": [{joined}]}}'
        return "A test summary."

    @property
    def summary_calls(self) -> list[str]:
        return [
            call
            for call in self.calls
            if '"label"' not in call and '"references"' not in call
        ]


def vector_for(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [digest[i % len(digest)] / 255 for i in range(EMBED_DIM)]


class FakeEmbedder:
    def __init__(
        self,
        overrides: dict[str, list[float]] | None = None,
        fail_calls: set[int] | None = None,
    ):
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.overrides = overrides or {}
        # 0-based indexes of embed() calls that should raise, standing in for
        # a Voyage 429 that survived the client's retries
        self.fail_calls = fail_calls or set()

    async def embed(
        self, texts: list[str], input_type: str = "document"
    ) -> list[list[float]]:
        index = len(self.calls)
        self.calls.append((tuple(texts), input_type))
        if index in self.fail_calls:
            raise RuntimeError(f"simulated embedding failure on call {index}")
        return [self.overrides.get(text) or vector_for(text) for text in texts]
