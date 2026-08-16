"""Fake LLM/embedding clients — enrichment tests never hit real APIs."""

import hashlib
import re

from codegraph.models import EMBED_DIM


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
    def __init__(self, overrides: dict[str, list[float]] | None = None):
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.overrides = overrides or {}

    async def embed(
        self, texts: list[str], input_type: str = "document"
    ) -> list[list[float]]:
        self.calls.append((tuple(texts), input_type))
        return [self.overrides.get(text) or vector_for(text) for text in texts]
