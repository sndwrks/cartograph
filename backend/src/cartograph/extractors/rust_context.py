"""Per-repo resolution context for the Rust extractor.

Rust's module system is path-based (`src/foo/bar.rs` is `crate::foo::bar`),
but "crate" is only meaningful once you know where the crate root is — the
nearest ancestor directory containing a `Cargo.toml`, whose `src/` holds the
module tree. A repo can hold several crates (a Cargo workspace), so this is
discovered once per ingest run, like `ts_context.discover_ts_context`, and
handed to `RustExtractor.extract()` as `context`.

This module stays DB-free like the rest of the extractor layer.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _normalize_ident(name: str) -> str:
    """Cargo's own normalization: a crate name's Rust identifier form has
    every '-' replaced with '_' (`fake-winch` the package vs `fake_winch`
    the crate root's `identifier`)."""
    return name.replace("-", "_")


def _ancestor_dirs(rel_dir: str) -> Iterator[str]:
    """Yield rel_dir, its parents, then "" (the repo root)."""
    while True:
        yield rel_dir
        if rel_dir in ("", "."):
            return
        parent = os.path.dirname(rel_dir)
        if parent == rel_dir:
            return
        rel_dir = parent


@dataclass(frozen=True)
class RustResolutionContext:
    # every dir (repo-relative posix, "" = repo root) containing a Cargo.toml
    crate_dirs: frozenset[str]
    # crate dir -> (package identifier, lib target identifier)
    # lib identifier defaults to the package identifier when Cargo.toml has
    # no [lib] name override (the common case)
    crate_idents: dict[str, tuple[str, str]]

    def nearest_crate(self, importing_dir: str) -> tuple[str, str, str] | None:
        """(crate_dir, package_ident, lib_ident) for the nearest governing
        Cargo.toml, or None if this file isn't under any known crate."""
        for d in _ancestor_dirs(importing_dir):
            if d in self.crate_dirs:
                pkg, lib = self.crate_idents.get(d, (None, None))
                if pkg is None:
                    continue
                return d, pkg, lib
        return None


def discover_rust_context(
    root: Path, denied: Iterable[str] = ()
) -> RustResolutionContext:
    """One walk over the repo collecting Cargo.toml crate roots and names.

    denied is the same directory-name set the ingest walker prunes (this
    also keeps the walk out of target/, which is never a source of crates).
    """
    denied_names = set(denied)
    crate_dirs: set[str] = set()
    crate_idents: dict[str, tuple[str, str]] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in denied_names and not d.startswith(".")
        ]
        rel = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel == "." else rel

        if "Cargo.toml" not in filenames:
            continue
        crate_dirs.add(rel_dir)
        pkg_ident = _normalize_ident(Path(rel_dir).name or root.name)
        lib_ident = pkg_ident
        try:
            manifest = tomllib.loads(
                (Path(dirpath) / "Cargo.toml").read_text(encoding="utf-8")
            )
            pkg = manifest.get("package")
            if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
                pkg_ident = _normalize_ident(pkg["name"])
                lib_ident = pkg_ident
            lib = manifest.get("lib")
            if isinstance(lib, dict) and isinstance(lib.get("name"), str):
                lib_ident = _normalize_ident(lib["name"])
        except Exception:  # repo-controlled input must never abort ingest
            logger.warning("unparseable Cargo.toml in %s", rel_dir or ".")
        crate_idents[rel_dir] = (pkg_ident, lib_ident)

    return RustResolutionContext(
        crate_dirs=frozenset(crate_dirs), crate_idents=crate_idents
    )
