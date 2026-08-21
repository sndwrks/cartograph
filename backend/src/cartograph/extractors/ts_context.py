"""Per-repo resolution context for the TypeScript/JavaScript extractor.

Discovered once per ingest run: tsconfig/jsconfig path aliases (scoped to the
directory subtree their config governs, targets rewritten repo-relative) and
workspace package names (pnpm/npm monorepos), so specifiers like "@api/Foo",
"@scope/pkg", and Meteor-style "/imports/..." map to repo paths instead of
degrading to name_match noise.

This module stays DB-free like the rest of the extractor layer; the ingest
loader passes in the denied-directory set rather than importing the walker
here.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_INDEX_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


def _strip_jsonc_comments(text: str) -> str:
    """Remove // and /* */ comments, string-aware: alias patterns like
    "@api/*" legitimately contain comment openers inside JSON strings."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Remove commas directly before } or ], string-aware — a comma-brace
    sequence inside a JSON string value must survive untouched."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # drop the comma; the whitespace run is re-scanned
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_jsonc(text: str) -> dict:
    """Parse JSON tolerating // and /* */ comments and trailing commas."""
    return json.loads(_strip_trailing_commas(_strip_jsonc_comments(text)))


def _ancestor_dirs(rel_dir: str) -> Iterator[str]:
    """Yield rel_dir, its parents, then "" (the repo root)."""
    while True:
        yield rel_dir
        if rel_dir in ("", "."):
            return
        parent = posixpath.dirname(rel_dir)
        if parent == rel_dir:
            return
        rel_dir = parent


def aliases_from_tsconfig(text: str) -> dict[str, str]:
    """Extract {pattern: baseUrl-joined target} from tsconfig paths/baseUrl.

    Targets are relative to the tsconfig's own directory; discovery rewrites
    them repo-relative. Supports the common '@/*': ['src/*'] form, not full
    tsconfig semantics. Shape-defensive throughout: tsconfig content is
    repo-controlled and a malformed file must degrade to "no aliases", never
    abort an ingest.
    """
    parsed = _parse_jsonc(text)
    options = parsed.get("compilerOptions") if isinstance(parsed, dict) else None
    if not isinstance(options, dict):
        return {}
    base_url = options.get("baseUrl")
    if not isinstance(base_url, str):
        base_url = "."
    paths = options.get("paths")
    if not isinstance(paths, dict):
        return {}
    aliases: dict[str, str] = {}
    for pattern, targets in paths.items():
        if not isinstance(pattern, str) or not isinstance(targets, list):
            continue
        target = targets[0] if targets else None
        if isinstance(target, str):
            aliases[pattern] = posixpath.normpath(
                posixpath.join(base_url, target)
            )
    return aliases


def _sorted_patterns(aliases: dict[str, str]) -> list[tuple[str, str]]:
    """Exact patterns first, then globs longest-first, so '@db/UserData/*'
    wins over '@db/*'."""
    exact = [(p, t) for p, t in aliases.items() if "*" not in p]
    globs = [(p, t) for p, t in aliases.items() if "*" in p]
    globs.sort(key=lambda item: len(item[0]), reverse=True)
    return exact + globs


@dataclass(frozen=True)
class TsResolutionContext:
    # tsconfig/jsconfig dir ("" = repo root) -> patterns with repo-relative targets
    alias_maps: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # package name -> (repo-relative package dir, repo-relative entry base)
    workspace_packages: dict[str, tuple[str, str]] = field(default_factory=dict)
    # every dir containing a package.json, for nearest-ancestor lookups
    package_dirs: frozenset[str] = frozenset()

    def resolve_alias(self, spec: str, importing_dir: str) -> str | None:
        """Repo-relative path for spec via the nearest governing tsconfig."""
        for d in _ancestor_dirs(importing_dir):
            for pattern, target in self.alias_maps.get(d, ()):
                if "*" in pattern:
                    prefix, _, suffix = pattern.partition("*")
                    if (
                        len(spec) >= len(prefix) + len(suffix)
                        and spec.startswith(prefix)
                        and spec.endswith(suffix)
                    ):
                        remainder = spec[len(prefix) : len(spec) - len(suffix)]
                        # a starless target is a literal per tsconfig semantics
                        return (
                            target.replace("*", remainder, 1)
                            if "*" in target
                            else target
                        )
                elif spec == pattern:
                    return target
        return None

    def resolve_workspace(self, spec: str) -> str | None:
        """Repo-relative path for a workspace package name or deep import."""
        hit = self.workspace_packages.get(spec)
        if hit is not None:
            return hit[1]
        # only '/'-boundary prefixes of the specifier can be package names
        # ("@scope/pkg/sub" -> try "@scope/pkg", then "@scope")
        idx = len(spec)
        while (idx := spec.rfind("/", 0, idx)) > 0:
            hit = self.workspace_packages.get(spec[:idx])
            if hit is not None:
                return posixpath.join(hit[0], spec[idx + 1 :])
        return None

    def nearest_package_dir(self, importing_dir: str) -> str:
        for d in _ancestor_dirs(importing_dir):
            if d in self.package_dirs:
                return d
        return ""


def _entry_for(root: Path, pkg_dir: str) -> str:
    """Entry base for a workspace package, preferring source over the built
    dist/ that package.json main/exports usually point at (dist is deny-listed
    and never ingested)."""
    base = root / pkg_dir if pkg_dir else root
    for candidate in ("src/index", "index"):
        if any((base / (candidate + ext)).is_file() for ext in _INDEX_EXTENSIONS):
            return posixpath.join(pkg_dir, candidate) if pkg_dir else candidate
    return pkg_dir


def discover_ts_context(
    root: Path, denied: Iterable[str] = ()
) -> TsResolutionContext:
    """One walk over the repo collecting tsconfig aliases and package names.

    denied is the same directory-name set the ingest walker prunes.
    """
    denied_names = set(denied)
    alias_maps: dict[str, list[tuple[str, str]]] = {}
    workspace: dict[str, tuple[str, str]] = {}
    package_dirs: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in denied_names and not d.startswith(".")
        ]
        rel = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel == "." else rel

        if "package.json" in filenames:
            package_dirs.add(rel_dir)
            name = None
            try:
                # utf-8-sig eats a BOM, which strict json.loads rejects
                manifest = _parse_jsonc(
                    (Path(dirpath) / "package.json").read_text(encoding="utf-8-sig")
                )
                if isinstance(manifest, dict):
                    name = manifest.get("name")
            except Exception:  # repo-controlled input must never abort ingest
                logger.warning("unreadable package.json in %s", rel_dir or ".")
            if isinstance(name, str) and name:
                workspace[name] = (rel_dir, _entry_for(root, rel_dir))

        for fname in ("tsconfig.json", "jsconfig.json"):
            if fname not in filenames:
                continue
            try:
                aliases = aliases_from_tsconfig(
                    (Path(dirpath) / fname).read_text(encoding="utf-8-sig")
                )
            except Exception:  # repo-controlled input must never abort ingest
                logger.warning("unparseable %s in %s", fname, rel_dir or ".")
                continue
            if aliases:
                alias_maps[rel_dir] = _sorted_patterns(
                    {
                        pattern: posixpath.normpath(
                            posixpath.join(rel_dir, target)
                        )
                        for pattern, target in aliases.items()
                    }
                )
            break  # tsconfig.json wins over jsconfig.json

    return TsResolutionContext(
        alias_maps=alias_maps,
        workspace_packages=workspace,
        package_dirs=frozenset(package_dirs),
    )
