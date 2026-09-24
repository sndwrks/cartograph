"""build_llm provider dispatch and the claude-code provider — no network, no
real claude-agent-sdk install required (a fake module stands in via
sys.modules, mirroring how the batch tests fake the Anthropic client)."""

import sys
import types

import pytest

from cartograph.config import get_settings
from cartograph.enrich import __main__ as enrich_main
from cartograph.enrich.claude_code import ClaudeCodeLLM
from cartograph.enrich.llm import AnthropicLLM, build_llm


class _FakeOptions:
    """Stand-in for ClaudeAgentOptions — just remembers what it was built with."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _TextBlock:
    def __init__(self, text):
        self.text = text


class AssistantMessage:
    def __init__(self, content):
        self.content = content


class ResultMessage:
    def __init__(self, result=None, is_error=False, subtype="success"):
        self.result = result
        self.is_error = is_error
        self.subtype = subtype


class _FakeProcessError(Exception):
    """Stand-in for claude_agent_sdk.ProcessError."""

    def __init__(self, message, exit_code=None, stderr=None):
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(message)


class _FakeResultError(_FakeProcessError):
    """Stand-in for claude_agent_sdk.ResultError — mirrors the real shape
    (subtype pulled from ``data``) closely enough for the provider's lazy
    ``from claude_agent_sdk import ResultError, ProcessError`` to work
    against this fake module."""

    def __init__(self, message, data=None, exit_code=None):
        data = data or {}
        self.data = data
        self.subtype = data.get("subtype")
        super().__init__(message, exit_code=exit_code)


def _inject_fake_sdk(monkeypatch):
    fake_module = types.ModuleType("claude_agent_sdk")
    fake_module.ClaudeAgentOptions = _FakeOptions
    fake_module.query = lambda **_kwargs: None  # replaced per-instance in tests
    fake_module.ProcessError = _FakeProcessError
    fake_module.ResultError = _FakeResultError
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)


# --- build_llm dispatch ------------------------------------------------------


def test_build_llm_default_returns_anthropic(monkeypatch):
    monkeypatch.setattr(get_settings(), "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(get_settings(), "ENRICH_PROVIDER", "anthropic")
    llm = build_llm()
    assert isinstance(llm, AnthropicLLM)


def test_build_llm_claude_code_via_arg_needs_no_api_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    _inject_fake_sdk(monkeypatch)
    llm = build_llm("claude-code")
    assert isinstance(llm, ClaudeCodeLLM)


def test_build_llm_claude_code_via_setting(monkeypatch):
    monkeypatch.setattr(get_settings(), "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(get_settings(), "ENRICH_PROVIDER", "claude-code")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    _inject_fake_sdk(monkeypatch)
    llm = build_llm()
    assert isinstance(llm, ClaudeCodeLLM)


def test_build_llm_unknown_provider_raises(monkeypatch):
    with pytest.raises(SystemExit, match="nope"):
        build_llm("nope")


def test_build_llm_claude_code_missing_cli_raises(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    _inject_fake_sdk(monkeypatch)
    with pytest.raises(SystemExit, match="Claude Code CLI"):
        build_llm("claude-code")


def test_build_llm_claude_code_missing_sdk_package_raises(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    # forcing an ImportError regardless of whether the real package happens
    # to be installed in this environment
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    with pytest.raises(SystemExit, match="claude-agent-sdk"):
        build_llm("claude-code")


# --- ClaudeCodeLLM.complete ---------------------------------------------------


@pytest.fixture
def claude_code_llm(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    _inject_fake_sdk(monkeypatch)
    return ClaudeCodeLLM()


async def test_complete_prefers_result_message_text(claude_code_llm):
    async def fake_query(*, prompt, options):
        yield AssistantMessage(content=[_TextBlock("ignored, superseded by result")])
        yield ResultMessage(result="  A summary. ")

    claude_code_llm._query = fake_query
    assert await claude_code_llm.complete("summarize this") == "A summary."


async def test_complete_falls_back_to_assistant_text_when_no_result(claude_code_llm):
    async def fake_query(*, prompt, options):
        yield AssistantMessage(content=[_TextBlock("assembled from blocks")])
        yield ResultMessage(result=None)

    claude_code_llm._query = fake_query
    assert await claude_code_llm.complete("summarize this") == "assembled from blocks"


async def test_complete_raises_on_error_result(claude_code_llm):
    async def fake_query(*, prompt, options):
        yield ResultMessage(is_error=True, subtype="error_during_execution")

    claude_code_llm._query = fake_query
    with pytest.raises(RuntimeError, match="error_during_execution"):
        await claude_code_llm.complete("summarize this")


async def test_complete_raises_on_empty_response(claude_code_llm):
    async def fake_query(*, prompt, options):
        return
        yield  # pragma: no cover - keeps this an async generator function

    claude_code_llm._query = fake_query
    with pytest.raises(RuntimeError, match="empty response"):
        await claude_code_llm.complete("summarize this")


def test_options_disable_built_in_tools_and_are_hermetic(claude_code_llm):
    captured = {}

    async def fake_query(*, prompt, options):
        captured["options"] = options
        return
        yield  # pragma: no cover - keeps this an async generator function

    claude_code_llm._query = fake_query

    async def _drive():
        try:
            await claude_code_llm.complete("hi")
        except RuntimeError:
            pass

    import asyncio

    asyncio.run(_drive())

    options = captured["options"]
    # allowed_tools=[] alone only means "nothing is auto-approved" — the
    # built-in tools (Read, Bash, ...) are still offered unless `tools=[]`
    # is also set.
    assert options.kwargs["tools"] == []
    assert options.kwargs["allowed_tools"] == []
    # Hermetic: no user/project/local settings, CLAUDE.md, hooks, or MCP
    # servers should be loaded for an enrichment call.
    assert options.kwargs["setting_sources"] == []
    assert options.kwargs.get("strict_mcp_config") is True


async def test_complete_returns_text_on_error_max_turns_with_collected_text(
    claude_code_llm,
):
    from claude_agent_sdk import ResultError

    async def fake_query(*, prompt, options):
        yield AssistantMessage(content=[_TextBlock("partial answer before cutoff")])
        raise ResultError(
            "Claude Code returned an error result: Reached maximum number of "
            "turns (3) (exit code: 1)",
            data={"subtype": "error_max_turns"},
            exit_code=1,
        )
        yield  # pragma: no cover - keeps this an async generator function

    claude_code_llm._query = fake_query
    result = await claude_code_llm.complete("summarize this")
    assert result == "partial answer before cutoff"


async def test_complete_raises_on_error_max_turns_with_no_text(claude_code_llm):
    from claude_agent_sdk import ResultError

    async def fake_query(*, prompt, options):
        if False:
            yield  # pragma: no cover - keeps this an async generator function
        raise ResultError(
            "Claude Code returned an error result: Reached maximum number of "
            "turns (3) (exit code: 1)",
            data={"subtype": "error_max_turns"},
            exit_code=1,
        )

    claude_code_llm._query = fake_query
    with pytest.raises(RuntimeError, match="error_max_turns"):
        await claude_code_llm.complete("summarize this")


async def test_complete_reraises_non_max_turns_result_error(claude_code_llm):
    from claude_agent_sdk import ResultError

    async def fake_query(*, prompt, options):
        yield AssistantMessage(content=[_TextBlock("some text")])
        raise ResultError(
            "Claude Code returned an error result: API Error",
            data={"subtype": "error_during_execution"},
            exit_code=1,
        )

    claude_code_llm._query = fake_query
    with pytest.raises(RuntimeError) as excinfo:
        await claude_code_llm.complete("summarize this")
    assert isinstance(excinfo.value.__cause__, ResultError)


# --- CLI guard ----------------------------------------------------------------


def test_cli_provider_claude_code_rejects_batch_flags(monkeypatch, capsys):
    def fail_sessionmaker():
        raise AssertionError("get_sessionmaker should not be called")

    monkeypatch.setattr(enrich_main, "get_sessionmaker", fail_sessionmaker)
    with pytest.raises(SystemExit) as excinfo:
        enrich_main.main(
            ["--repo", "x", "--provider", "claude-code", "--batch-status"]
        )
    assert excinfo.value.code == 2
    assert "API-only" in capsys.readouterr().err
