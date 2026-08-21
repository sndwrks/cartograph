"""One-command porcelain: python -m cartograph ingest PATH.

The plumbing CLIs (cartograph.ingest, cartograph.enrich) are one process per
phase, which pushes the retry/poll loops into the caller's shell. This wraps
the whole pipeline — register, ingest, metrics, enrichment with automatic
retries of written-off items — in a single process, reading everything it
needs from the repo-root .env.

    python -m cartograph ingest ../myrepo --exclude generated certs
    python -m cartograph ingest ../myrepo --provider claude-code
    python -m cartograph enrich myrepo --phase embeddings
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path

logger = logging.getLogger("cartograph")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cartograph",
        description="Register, ingest, and enrich a repository in one command.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_enrich_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--provider",
            choices=("anthropic", "claude-code"),
            default=None,
            help="LLM provider for docs/summaries/communities "
            "(default: ENRICH_PROVIDER setting)",
        )
        p.add_argument("--limit", type=int, default=None, metavar="N")
        p.add_argument(
            "--retries",
            type=int,
            default=10,
            help="re-run rounds for written-off items before giving up (default 10)",
        )
        p.add_argument(
            "--retry-wait",
            type=float,
            default=60.0,
            metavar="SECONDS",
            help="pause between retry rounds (default 60)",
        )
        p.add_argument(
            "--concurrency",
            type=int,
            default=None,
            help="override ENRICH_CONCURRENCY (claude-code defaults to 4)",
        )

    ingest = sub.add_parser(
        "ingest", help="register (if needed) + ingest + metrics + enrich"
    )
    ingest.add_argument("path", help="repository root on this machine")
    ingest.add_argument(
        "--name", default=None, help="repository name (default: directory basename)"
    )
    ingest.add_argument("--branch", default="main", help="default branch")
    ingest.add_argument(
        "--exclude",
        nargs="*",
        default=None,
        metavar="DIR",
        help="directory basenames to skip (replaces the stored list; "
        "omit to keep it)",
    )
    ingest.add_argument(
        "--full", action="store_true", help="ignore stored hashes, re-ingest everything"
    )
    ingest.add_argument(
        "--no-enrich",
        action="store_true",
        help="stop after ingest + metrics (no API/LLM spend)",
    )
    add_enrich_opts(ingest)

    enrich = sub.add_parser(
        "enrich", help="run enrichment with automatic retries of failed items"
    )
    enrich.add_argument("name", help="registered repository name")
    enrich.add_argument(
        "--phase", default="all", help="single phase, or all (default)"
    )
    enrich.add_argument(
        "--force", action="store_true", help="re-label communities that have labels"
    )
    add_enrich_opts(enrich)

    return parser


def _apply_concurrency(args: argparse.Namespace) -> None:
    # Must happen before the first get_settings() call (it's lru_cached).
    # claude-code spawns one CLI subprocess per in-flight call, so the API
    # default of 12 is far too hot for it.
    if args.concurrency is not None:
        os.environ["ENRICH_CONCURRENCY"] = str(args.concurrency)
    elif args.provider == "claude-code" and "ENRICH_CONCURRENCY" not in os.environ:
        os.environ["ENRICH_CONCURRENCY"] = "4"


async def _enrich_with_retries(
    maker,
    repo_name: str,
    phases: tuple[str, ...],
    args: argparse.Namespace,
) -> int:
    from cartograph.enrich.llm import build_llm
    from cartograph.enrich.runner import (
        EMBED_PHASES,
        EXIT_PARTIAL_FAILURE,
        LLM_PHASES,
        failed_phases,
        run_phases,
    )
    from cartograph.enrich.voyage import build_embedder
    from cartograph.query import ingest as q

    llm = build_llm(args.provider) if LLM_PHASES.intersection(phases) else None
    embedder = build_embedder() if EMBED_PHASES.intersection(phases) else None
    force = getattr(args, "force", False)

    for attempt in range(1, args.retries + 1):
        async with maker() as session:
            repo = await q.get_repository_by_name(session, repo_name)
            if repo is None:
                print(f"unknown repository {repo_name!r}", file=sys.stderr)
                return 2
            try:
                results = await run_phases(
                    session,
                    repo,
                    phases,
                    llm=llm,
                    embedder=embedder,
                    limit=args.limit,
                    force=force,
                )
            except Exception:
                traceback.print_exc()
                return 1
        print(json.dumps(results))
        incomplete = failed_phases(results)
        if not incomplete:
            return 0
        # Every phase re-selects unfinished work by predicate (content hash,
        # embedding IS NULL), so simply running again retries only failures.
        for phase, count in incomplete:
            logger.warning("%s: %d item(s) failed", phase, count)
        if attempt < args.retries:
            logger.info(
                "retry %d/%d in %.0fs — completed work is already committed",
                attempt + 1,
                args.retries,
                args.retry_wait,
            )
            await asyncio.sleep(args.retry_wait)
    logger.error("gave up after %d rounds; re-run to continue", args.retries)
    return EXIT_PARTIAL_FAILURE


async def amain(args: argparse.Namespace) -> int:
    from cartograph.db import get_sessionmaker
    from cartograph.enrich.runner import ALL_PHASES
    from cartograph.query import ingest as q

    maker = get_sessionmaker()

    if args.command == "enrich":
        phases = ALL_PHASES if args.phase == "all" else (args.phase,)
        return await _enrich_with_retries(maker, args.name, phases, args)

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"{root} is not a directory", file=sys.stderr)
        return 2
    name = args.name or root.name

    async with maker() as session:
        repo = await q.upsert_repository(
            session, name, str(root), args.branch, exclude_dirs=args.exclude
        )
        await session.commit()
        suffix = (
            f" (excluding {', '.join(repo.exclude_dirs)})" if repo.exclude_dirs else ""
        )
        logger.info("registered %s -> %s%s", repo.name, repo.root_path, suffix)

        from cartograph.ingest.loader import ingest_repo
        from cartograph.metrics.job import run_metrics

        try:
            stats = await ingest_repo(session, repo, full=args.full, trigger="manual")
            stats["metrics"] = await run_metrics(
                session,
                repo,
                changed_edges=stats["edges_added"] + stats["edges_deleted"],
            )
        except Exception:
            traceback.print_exc()
            return 1
        print(json.dumps(stats))

    if args.no_enrich:
        return 0
    return await _enrich_with_retries(maker, name, ALL_PHASES, args)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    _apply_concurrency(args)
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
