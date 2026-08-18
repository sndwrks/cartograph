"""Ingest CLI: python -m cartograph.ingest {register,run}."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback

from cartograph.db import get_sessionmaker
from cartograph.query import ingest as q

from .loader import ingest_repo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cartograph.ingest",
        description="Register repositories and load them into the graph.",
        epilog=(
            "Paths are as seen inside the container: volume-mount the target "
            "repo into the api service, e.g. -v /host/repo:/repos/myrepo, and "
            "register with --root /repos/myrepo."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="create or update a repository")
    register.add_argument("--name", required=True, help="unique repository name")
    register.add_argument(
        "--root", required=True, help="repo root path as seen inside the container"
    )
    register.add_argument("--branch", default="main", help="default branch")

    run = sub.add_parser("run", help="ingest a registered repository")
    run.add_argument("--repo", required=True, help="repository name")
    run.add_argument(
        "--files", nargs="+", help="restrict to these repo-relative paths"
    )
    run.add_argument(
        "--full", action="store_true", help="ignore stored hashes, re-ingest everything"
    )
    run.add_argument(
        "--enrich",
        action="store_true",
        help=(
            "chain the tier-3 enrich phases (docs, summaries, embeddings) "
            "after load+resolve — community labels stay put (on-demand only)"
        ),
    )
    run.add_argument(
        "--trigger",
        choices=["manual", "hook", "ci"],
        default="manual",
        help="recorded on the ingest_runs row",
    )
    return parser


async def amain(args: argparse.Namespace) -> int:
    async with get_sessionmaker()() as session:
        if args.command == "register":
            repo = await q.upsert_repository(session, args.name, args.root, args.branch)
            await session.commit()
            print(f"registered {repo.name} -> {repo.root_path}")
            return 0

        repo = await q.get_repository_by_name(session, args.repo)
        if repo is None:
            print(
                f"unknown repository {args.repo!r} — register it first",
                file=sys.stderr,
            )
            return 2
        try:
            stats = await ingest_repo(
                session, repo, files=args.files, full=args.full, trigger=args.trigger
            )
        except Exception:
            traceback.print_exc()
            return 1

        # chain metrics: clustering only re-runs past RECLUSTER_EDGE_THRESHOLD
        from cartograph.metrics.job import run_metrics

        try:
            stats["metrics"] = await run_metrics(
                session,
                repo,
                changed_edges=stats["edges_added"] + stats["edges_deleted"],
            )
        except Exception:
            traceback.print_exc()
            return 1

        incomplete: list[tuple[str, int]] = []
        if args.enrich:
            from cartograph.enrich.llm import build_llm
            from cartograph.enrich.runner import failed_phases, run_phases
            from cartograph.enrich.voyage import build_embedder

            try:
                enrich_stats = await run_phases(
                    session,
                    repo,
                    ("docs", "summaries", "embeddings"),
                    llm=build_llm(),
                    embedder=build_embedder(),
                )
            except Exception:
                traceback.print_exc()
                return 1
            stats["enrich"] = enrich_stats
            incomplete = failed_phases(enrich_stats)

        # fold the chained-phase results into the run row's stats
        rows = await q.list_runs(session, repo.name, limit=1)
        if rows:
            run_row, _ = rows[0]
            run_row.stats = stats
            await session.commit()

        print(json.dumps(stats))
        if incomplete:
            from cartograph.enrich.runner import EXIT_PARTIAL_FAILURE

            for phase, count in incomplete:
                logging.getLogger(__name__).warning(
                    "%s: %d item(s) failed and were left unprocessed", phase, count
                )
            return EXIT_PARTIAL_FAILURE
        return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(amain(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
