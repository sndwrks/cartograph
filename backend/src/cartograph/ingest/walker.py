"""File discovery for ingest runs."""

from __future__ import annotations

import os
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
    }
)


def walk_repo(root: Path) -> list[str]:
    """Repo-relative posix paths of files a registered extractor can handle.

    Skips the default deny-list and all hidden directories (which covers .git).
    """
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in DENY_DIRS and not d.startswith(".")
        )
        rel_dir = Path(dirpath).relative_to(root)
        for filename in filenames:
            rel = str(PurePosixPath(rel_dir / filename))
            if get_extractor_for(rel) is not None:
                results.append(rel)
    return sorted(results)
