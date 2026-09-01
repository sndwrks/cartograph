#!/usr/bin/env python3
"""Per-session token usage from Claude Code transcripts — the A/B half of
"is the MCP server making my agent more efficient?".

The dashboard's "tokens saved" is a modelled counterfactual. The real test is
the same task run with and without the `cartograph` server registered, and
this script measures each arm from what Claude Code writes to disk:
`~/.claude/projects/<project-dir>/<session>.jsonl`, where every
`type == "assistant"` line carries `message.usage` (input, cache creation,
cache read, output tokens). Streaming writes several lines per request with
the same `requestId` and identical usage, so requests are deduped on it.

Usage:
    scripts/session_tokens.py ~/.claude/projects/-Users-me--proj-x [--since 2026-08-31T00:00]
    scripts/session_tokens.py a.jsonl b.jsonl --label with-mcp
    scripts/session_tokens.py DIR --label with-mcp --label-file without.jsonl:without-mcp

Per session: turns (distinct requests), context tokens processed
(input + cache_creation + cache_read — the number that tool-output verbosity
actually drives), output tokens, tool calls by name split into
`mcp__cartograph__*` vs the file tools it replaces, and wall time. With
labels, per-label means follow so the two arms can be compared directly.

Stdlib only. Tag the with-MCP arm server-side too by adding
`"headers": {"X-Cartograph-Session": "<label>"}` to that arm's `.mcp.json`
entry — `tool_calls.client_session` then joins server rows to sessions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

FILE_TOOLS = {"Read", "Grep", "Glob", "Bash"}


def _aware(raw: str) -> datetime:
    """Transcript timestamps are UTC-aware; a naive --since is taken as UTC so
    the two are comparable."""
    t = datetime.fromisoformat(raw)
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def iter_files(paths: list[str]):
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            yield from sorted(p.glob("*.jsonl"))
        elif p.is_file():
            yield p


def parse_session(path: Path, since: datetime | None) -> dict | None:
    requests: dict[str, dict] = {}
    tools: Counter = Counter()
    first = last = None
    session_id = path.stem
    with path.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            session_id = rec.get("sessionId", session_id)
            ts = rec.get("timestamp")
            if ts:
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    t = None
                if t is not None:
                    if since is not None and t < since:
                        continue
                    first = t if first is None or t < first else first
                    last = t if last is None or t > last else last
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage")
            rid = rec.get("requestId") or rec.get("uuid")
            if usage and rid:
                requests[rid] = usage  # same requestId => same usage; last wins
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name", "?")] += 1
    if not requests:
        return None
    ctx = out = 0
    for u in requests.values():
        ctx += (
            (u.get("input_tokens") or 0)
            + (u.get("cache_creation_input_tokens") or 0)
            + (u.get("cache_read_input_tokens") or 0)
        )
        out += u.get("output_tokens") or 0
    mcp = sum(n for name, n in tools.items() if name.startswith("mcp__cartograph__"))
    files = sum(n for name, n in tools.items() if name in FILE_TOOLS)
    return {
        "session": session_id[:8],
        "file": path.name,
        "start": first,
        "turns": len(requests),
        "context_tokens": ctx,
        "output_tokens": out,
        "mcp_calls": mcp,
        "file_tool_calls": files,
        "wall_s": (last - first).total_seconds() if first and last else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="transcript .jsonl files or project directories")
    ap.add_argument(
        "--since",
        type=_aware,
        help="ignore records before this ISO time (naive = UTC, like the transcripts)",
    )
    ap.add_argument("--label", default=None, help="label applied to every session given")
    ap.add_argument(
        "--label-file",
        action="append",
        default=[],
        metavar="FILE:LABEL",
        help="label one transcript (repeatable); overrides --label for that file",
    )
    args = ap.parse_args(argv)

    per_file = {}
    for spec in args.label_file:
        name, _, label = spec.rpartition(":")
        per_file[Path(name).expanduser().name] = label

    rows = []
    for path in iter_files(args.paths):
        row = parse_session(path, args.since)
        if row is None:
            continue
        row["label"] = per_file.get(path.name, args.label) or "-"
        rows.append(row)
    if not rows:
        print("no assistant usage records found", file=sys.stderr)
        return 1
    # sessions with no parseable timestamp sort last, among themselves by file
    rows.sort(key=lambda r: (r["start"] is None, r["start"] or datetime.min.replace(tzinfo=UTC), r["file"]))

    hdr = f"{'session':8} {'label':12} {'start':16} {'turns':>5} {'context':>10} {'output':>8} {'mcp':>4} {'file':>4} {'wall_s':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        start = r["start"].strftime("%Y-%m-%d %H:%M") if r["start"] else "?"
        print(
            f"{r['session']:8} {r['label'][:12]:12} {start:16} {r['turns']:5d} "
            f"{r['context_tokens']:10d} {r['output_tokens']:8d} {r['mcp_calls']:4d} "
            f"{r['file_tool_calls']:4d} {r['wall_s']:7.0f}"
        )

    by_label = defaultdict(list)
    for r in rows:
        by_label[r["label"]].append(r)
    if len(by_label) > 1 or "-" not in by_label:
        print()
        print(f"{'label':12} {'n':>3} {'turns':>7} {'context':>10} {'output':>8} {'mcp':>5} {'file':>5} {'wall_s':>7}   (means)")
        for label, group in sorted(by_label.items()):
            mean = lambda k: statistics.fmean(g[k] for g in group)  # noqa: E731
            print(
                f"{label[:12]:12} {len(group):3d} {mean('turns'):7.1f} {mean('context_tokens'):10.0f} "
                f"{mean('output_tokens'):8.0f} {mean('mcp_calls'):5.1f} {mean('file_tool_calls'):5.1f} {mean('wall_s'):7.0f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
