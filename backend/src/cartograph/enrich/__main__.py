"""Enrichment CLI: python -m cartograph.enrich --repo NAME [--phase ...]."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback

from cartograph.db import get_sessionmaker
from cartograph.query import ingest as q_ingest

from . import batch
from .batch import EXIT_BATCH_PENDING, build_batch_client
from .llm import build_llm
from .runner import (
    ALL_PHASES,
    EMBED_PHASES,
    EXIT_PARTIAL_FAILURE,
    LLM_PHASES,
    failed_phases,
    run_phases,
)
from .voyage import build_embedder

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cartograph.enrich",
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
        "--force",
        action="store_true",
        help=(
            "re-label communities that have labels; with --batch, submit even "
            "when uncollected batches exist"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--batch",
        action="store_true",
        help=(
            "submit summaries to the Anthropic Batch API (50%% cost, async) "
            "and exit — requires --phase summaries"
        ),
    )
    group.add_argument(
        "--batch-status",
        action="store_true",
        help=f"poll submitted batches; exits {EXIT_BATCH_PENDING} while any is processing",
    )
    group.add_argument(
        "--batch-collect",
        action="store_true",
        help="write summaries from every ended batch, then mark it collected",
    )
    group.add_argument(
        "--batch-abandon",
        action="store_true",
        help=(
            "give up on every uncollected batch: cancel still-processing ones "
            "at the provider and clear the rows; the sync sweep re-does the work"
        ),
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="with --batch: poll until every batch ends, then collect inline",
    )
    parser.add_argument(
        "--provider",
        choices=("anthropic", "claude-code"),
        default=None,
        help="LLM provider for docs/summaries/communities (default: ENRICH_PROVIDER setting).",
    )
    return parser


async def amain_batch(args: argparse.Namespace) -> int:
    if args.batch and args.phase != "summaries":
        # --phase defaults to "all"; requiring the explicit phase keeps
        # "enrich --batch" from silently submitting a five-figure request set
        print("--batch requires --phase summaries", file=sys.stderr)
        return 2
    client = build_batch_client()
    maker = get_sessionmaker()
    async with maker() as session:
        repo = await q_ingest.get_repository_by_name(session, args.repo)
        if repo is None:
            print(f"unknown repository {args.repo!r}", file=sys.stderr)
            return 2
        try:
            if args.batch:
                result = await batch.submit_summaries(
                    session, repo, client, limit=args.limit, force=args.force
                )
            elif args.batch_status:
                result = await batch.check_status(session, repo, client)
            elif args.batch_abandon:
                result = await batch.abandon_batches(session, repo, client)
            else:
                result = await batch.collect_summaries(session, repo, client)
        except batch.BatchStateError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except SystemExit:
            raise
        except Exception:
            traceback.print_exc()
            return 1
    if args.batch and args.wait:
        # the submit session is closed: the wait opens a fresh one per poll
        # rather than parking a checked-out connection for potentially hours
        try:
            result = {
                "submitted": result,
                "collected": await batch.wait_and_collect(maker, repo, client),
            }
        except batch.BatchStateError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except Exception:
            traceback.print_exc()
            return 1
    print(json.dumps(result))
    if args.batch_status:
        return EXIT_BATCH_PENDING if result["pending"] else 0
    collected = result.get("collected") if args.batch else result
    if isinstance(collected, dict) and collected.get("failed"):
        logger.warning(
            "%d item(s) failed — run --phase summaries (sync) to retry them",
            collected["failed"],
        )
        return EXIT_PARTIAL_FAILURE
    return 0


async def amain(args: argparse.Namespace) -> int:
    if args.batch or args.batch_status or args.batch_collect or args.batch_abandon:
        return await amain_batch(args)
    phases = ALL_PHASES if args.phase == "all" else (args.phase,)
    llm = build_llm(args.provider) if LLM_PHASES.intersection(phases) else None
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
    incomplete = failed_phases(results)
    for phase, count in incomplete:
        logger.warning("%s: %d item(s) failed and were left unprocessed", phase, count)
    if incomplete:
        logger.warning("re-run to retry — completed work is already committed")
        return EXIT_PARTIAL_FAILURE
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.wait and not args.batch:
        parser.error("--wait only applies to --batch")
    if args.provider == "claude-code" and (
        args.batch or args.batch_status or args.batch_collect or args.batch_abandon
    ):
        parser.error(
            "--provider claude-code cannot be combined with batch flags: "
            "batch mode uses the Anthropic Message Batches API, which is API-only."
        )
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
