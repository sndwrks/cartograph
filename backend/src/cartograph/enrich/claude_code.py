"""Claude Code provider: runs enrichment prompts through the local Claude
Code CLI via the Claude Agent SDK, using subscription auth instead of an
Anthropic API key.

Host-only: requires the ``claude`` CLI installed and logged in. Not usable
inside the backend Docker image, and not usable with ``enrich --batch``
(Message Batches is an API-only product).
"""

from __future__ import annotations

import shutil

from cartograph.enrich.llm import SUMMARY_MODEL


class ClaudeCodeLLM:
    """LLMClient implementation backed by the Claude Agent SDK."""

    def __init__(self, model: str = SUMMARY_MODEL) -> None:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            raise SystemExit(
                "The claude-code provider requires the claude-agent-sdk "
                "package. Install it with: pip install -e '.[claude-code]'"
            )
        if shutil.which("claude") is None:
            raise SystemExit(
                "The claude-code provider requires the Claude Code CLI on "
                "PATH (and a logged-in session). Install it from "
                "https://claude.com/claude-code and run `claude` once to "
                "log in."
            )
        self._query = query
        self._options_cls = ClaudeAgentOptions
        self._model = model

    async def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        # max_tokens is part of the LLMClient contract but the Agent SDK has
        # no per-call output cap; the prompts already bound output length.
        del max_tokens
        options = self._options_cls(
            model=self._model,
            # No tools are allowed, but the model occasionally spends a turn
            # attempting one anyway; a small budget absorbs that instead of
            # failing the call with error_max_turns.
            max_turns=3,
            allowed_tools=[],
            # An inherited ANTHROPIC_API_KEY would make the CLI bill the API,
            # defeating the point of this provider; blank it out.
            env={"ANTHROPIC_API_KEY": ""},
        )
        parts: list[str] = []
        result_text: str | None = None
        error_subtype: str | None = None
        async for message in self._query(prompt=prompt, options=options):
            kind = type(message).__name__
            if kind == "AssistantMessage":
                for block in getattr(message, "content", []):
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
            elif kind == "ResultMessage":
                if getattr(message, "is_error", False):
                    error_subtype = getattr(message, "subtype", "unknown")
                else:
                    result_text = getattr(message, "result", None)
        # A turn-limit "error" still carries the assistant's text; only fail
        # when there is genuinely nothing to return.
        text = (result_text or "".join(parts)).strip()
        if not text:
            raise RuntimeError(
                f"claude-code call failed: {error_subtype}"
                if error_subtype
                else "claude-code returned an empty response"
            )
        return text
