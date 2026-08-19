"""Export CLI: python -m cartograph.kb.export --repo NAME [--out PATH]."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback
from pathlib import Path

from cartograph.db import get_sessionmaker
from cartograph.kb.export.runner import run_export
from cartograph.kb.types import LOOKUP_PRECEDENCE
from cartograph.query import ingest as q_ingest

logger = logging.getLogger(__name__)

EXIT_PARTIAL = 3  # same meaning as the enrich CLI: finished, but wrote off work


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cartograph.kb.export",
        description=(
            "Render published knowledge-base entries to Markdown: glossary "
            "into a root CONTEXT.md, decisions into docs/adr/, and one file "
            "each for specifications, conventions and runbooks. One-way — "
            "Postgres stays the source of truth and edits to the output are "
            "never read back."
        ),
    )
    parser.add_argument("--repo", required=True, help="repository name")
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="target directory (default: the repository's root_path)",
    )
    parser.add_argument(
        "--type",
        action="append",
        dest="types",
        choices=list(LOOKUP_PRECEDENCE),
        help="only this type; repeatable (default: all)",
    )
    parser.add_argument(
        "--no-include-global",
        action="store_true",
        help="exclude entries that are not scoped to this repository",
    )
    parser.add_argument("--context-name", default=None, help="the CONTEXT.md H1")
    parser.add_argument(
        "--context-description", default="", help="one line under the CONTEXT.md H1"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report the plan; write nothing"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files we did not write, or that changed since we did",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="keep files whose entries no longer export",
    )
    # No --json flag: the summary is ALWAYS JSON on stdout, matching
    # `python -m cartograph.enrich`. A flag that selects the only behaviour
    # there is would be a lie.
    return parser


async def amain(args: argparse.Namespace) -> int:
    async with get_sessionmaker()() as session:
        repo = await q_ingest.get_repository_by_name(session, args.repo)
        if repo is None:
            print(f"unknown repository {args.repo!r}", file=sys.stderr)
            return 2

        out = Path(args.out) if args.out else Path(repo.root_path)
        if not out.is_dir():
            print(f"--out is not a directory: {out}", file=sys.stderr)
            return 2

        try:
            result = await run_export(
                session,
                repo,
                out,
                types=tuple(args.types) if args.types else None,
                include_global=not args.no_include_global,
                dry_run=args.dry_run,
                force=args.force,
                prune=not args.no_prune,
                context_name=args.context_name,
                context_description=args.context_description,
            )
        except Exception:
            traceback.print_exc()
            return 1

    print(json.dumps(result.as_dict()))
    for warning in result.warnings:
        logger.warning("%s", warning)
    for conflict in sorted(result.conflicts):
        logger.warning(
            "%s: not written — it was hand-authored or edited since the last "
            "export. Move it aside or re-run with --force",
            conflict,
        )
    for failure in result.failed:
        logger.warning("%s: %s", failure.get("slug") or failure["type"], failure["error"])
    if result.partial:
        logger.warning("re-run to retry — everything else is already written")
        return EXIT_PARTIAL
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(amain(build_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
