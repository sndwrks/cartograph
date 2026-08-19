"""File discovery for ingest runs."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from cartograph.extractors import get_extractor_for

DENY_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "dist",
        "build",
        "__pycache__",
        # minified bundles: 33 such files in one repo carried 11k symbols —
        # more than the entire hand-written source — and summarizing them is
        # pure enrichment spend on generated output
        "storybook-static",
        # Playwright's default output dirs — trace viewer bundles inside them
        # are minified single-line files with thousands of symbols
        "playwright-report",
        "test-results",
    }
)


def denied_dirs(exclude: Iterable[str] = ()) -> frozenset[str]:
    """The default deny-list plus a repository's registered exclude_dirs."""
    return DENY_DIRS | frozenset(exclude)


def is_excluded(rel_path: str, deny: frozenset[str]) -> bool:
    """True if any directory component of rel_path is denied or hidden.

    Mirrors walk_repo's pruning so paths named explicitly (--files, the
    post-commit hook) can't sneak past the walk-time filter.
    """
    return any(part in deny or part.startswith(".") for part in PurePosixPath(rel_path).parts[:-1])


def walk_repo(root: Path, exclude: Iterable[str] = ()) -> list[str]:
    """Repo-relative posix paths of files a registered extractor can handle.

    Skips the default deny-list, the repository's exclude dirs, and all
    hidden directories (which covers .git).
    """
    deny = denied_dirs(exclude)
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in deny and not d.startswith(".")
        )
        rel_dir = Path(dirpath).relative_to(root)
        for filename in filenames:
            rel = str(PurePosixPath(rel_dir / filename))
            if get_extractor_for(rel) is not None:
                results.append(rel)
    return sorted(results)
