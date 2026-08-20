"""Fake LLM/embedding clients — enrichment tests never hit real APIs."""

import hashlib
import re

from cartograph.enrich.batch import BatchItemResult
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


class FakeBatchClient:
    def __init__(
        self,
        statuses: list[str] | None = None,
        outcomes: dict[str, BatchItemResult] | None = None,
        fail_results: set[str] | None = None,
    ):
        # batch_id -> the (custom_id, prompt) list it was submitted with
        self.submitted: dict[str, list[tuple[str, str]]] = {}
        self.submit_params: list[tuple[str, int]] = []  # (model, max_tokens)
        # processing_status values returned by successive status() calls
        # (shared across batches); empty/exhausted -> "ended"
        self.statuses = list(statuses or [])
        # custom_id -> result override; anything else succeeds
        self.outcomes = outcomes or {}
        # batch_ids whose results() raises, standing in for expired/deleted
        # provider results
        self.fail_results = fail_results or set()
        self.status_calls = 0
        self.canceled: list[str] = []

    async def submit(
        self, prompts: list[tuple[str, str]], model: str, max_tokens: int
    ) -> str:
        batch_id = f"msgbatch_fake_{len(self.submitted) + 1}"
        self.submitted[batch_id] = list(prompts)
        self.submit_params.append((model, max_tokens))
        return batch_id

    async def status(self, batch_id: str) -> tuple[str, dict]:
        self.status_calls += 1
        status = self.statuses.pop(0) if self.statuses else "ended"
        total = len(self.submitted[batch_id])
        done = total if status == "ended" else 0
        return status, {"processing": total - done, "succeeded": done,
                        "errored": 0, "canceled": 0, "expired": 0}

    async def results(self, batch_id: str):
        if batch_id in self.fail_results:
            raise RuntimeError(f"simulated unreadable results for {batch_id}")
        for custom_id, _prompt in self.submitted[batch_id]:
            yield self.outcomes.get(custom_id) or BatchItemResult(
                custom_id=custom_id, kind="succeeded", text="A batch summary."
            )

    async def cancel(self, batch_id: str) -> None:
        self.canceled.append(batch_id)


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
