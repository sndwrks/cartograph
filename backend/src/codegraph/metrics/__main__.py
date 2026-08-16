"""Metrics CLI: python -m codegraph.metrics --repo NAME."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback

from codegraph.db import get_sessionmaker
from codegraph.query import ingest as q_ingest

from .job import run_metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m codegraph.metrics",
        description="Compute degrees, PageRank, and Leiden communities for a repo.",
    )
    parser.add_argument("--repo", required=True, help="repository name")
    parser.add_argument(
        "--force-recluster",
        action="store_true",
        help="re-cluster even below the changed-edges threshold",
    )
    parser.add_argument(
        "--changed-edges",
        type=int,
        default=None,
        metavar="N",
        help=(
            "edges added+deleted by the preceding ingest; clustering is skipped "
            "when below RECLUSTER_EDGE_THRESHOLD (omit to always cluster)"
        ),
    )
    return parser


async def amain(args: argparse.Namespace) -> int:
    async with get_sessionmaker()() as session:
        repo = await q_ingest.get_repository_by_name(session, args.repo)
        if repo is None:
            print(
                f"unknown repository {args.repo!r} — register it first",
                file=sys.stderr,
            )
            return 2
        try:
            stats = await run_metrics(
                session,
                repo,
                force_recluster=args.force_recluster,
                changed_edges=args.changed_edges,
            )
        except Exception:
            traceback.print_exc()
            return 1
        print(json.dumps(stats))
        return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(amain(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
