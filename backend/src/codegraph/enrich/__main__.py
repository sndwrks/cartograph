"""Enrichment CLI: python -m codegraph.enrich --repo NAME [--phase ...]."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback

from codegraph.db import get_sessionmaker
from codegraph.query import ingest as q_ingest

from .llm import build_llm
from .runner import ALL_PHASES, EMBED_PHASES, LLM_PHASES, run_phases
from .voyage import build_embedder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m codegraph.enrich",
        description=(
            "Tier-3 enrichment: summaries, embeddings, community labels, "
            "docs, KB. The only job that spends API money — results are "
            "cached on content hashes, so re-runs only pay for changes."
        ),
    )
    parser.add_argument("--repo", required=True, help="repository name")
    parser.add_argument(
        "--phase",
        choices=[*ALL_PHASES, "all"],
        default="all",
        help="single phase, or all (default)",
    )
    parser.add_argument("--limit", type=int, default=None, metavar="N")
    parser.add_argument(
        "--force", action="store_true", help="re-label communities that have labels"
    )
    return parser


async def amain(args: argparse.Namespace) -> int:
    phases = ALL_PHASES if args.phase == "all" else (args.phase,)
    llm = build_llm() if LLM_PHASES.intersection(phases) else None
    embedder = build_embedder() if EMBED_PHASES.intersection(phases) else None

    async with get_sessionmaker()() as session:
        repo = await q_ingest.get_repository_by_name(session, args.repo)
        if repo is None:
            print(f"unknown repository {args.repo!r}", file=sys.stderr)
            return 2
        try:
            results = await run_phases(
                session,
                repo,
                phases,
                llm=llm,
                embedder=embedder,
                limit=args.limit,
                force=args.force,
            )
        except Exception:
            traceback.print_exc()
            return 1
    print(json.dumps(results))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(amain(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
