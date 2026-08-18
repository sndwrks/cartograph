"""Rendering and writing the export. No argv here — the CLI is a thin shell."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.kb.export.manifest import (
    MANIFEST_NAME,
    read_manifest,
    recorded_hash,
    sha256_text,
    write_manifest,
)
from cartograph.kb.types import LOOKUP_PRECEDENCE, MARKER_PREFIX, REGISTRY, ExportContext
from cartograph.kb.views import KbEntryView
from cartograph.models import Repository
from cartograph.query import kb as q_kb

logger = logging.getLogger(__name__)

#: One root CONTEXT.md is designed for a curated list. Past this the file stops
#: being something a human reads and starts being a dump.
GLOSSARY_WARN_AT = 150


@dataclass
class ExportResult:
    repository: str
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def partial(self) -> bool:
        return bool(self.conflicts or self.failed)

    def as_dict(self) -> dict:
        return {
            "repo": self.repository,
            "written": len(self.written),
            "unchanged": len(self.unchanged),
            "pruned": len(self.pruned),
            "conflicts": sorted(self.conflicts),
            "failed": self.failed,
            "warnings": self.warnings,
            "dry_run": self.dry_run,
        }


def _is_safe(path: PurePosixPath) -> bool:
    return not path.is_absolute() and ".." not in path.parts


def _is_ours(text: str) -> bool:
    """Our own generated header on line 1 — the escape hatch for a lost manifest."""
    return text.lstrip().startswith(MARKER_PREFIX)


def _read(target: Path) -> str | None:
    """Target contents, or None when it cannot be read as text.

    A binary file, a wrong encoding, or a directory sitting where a file is
    expected must not abort a run that has already written other files — it is
    reported as a conflict instead, exactly like a hand-authored file.
    """
    try:
        return target.read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("cannot read %s as UTF-8 text; treating it as foreign", target)
        return None


def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=target.parent, prefix=".cartograph-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def _render(
    session: AsyncSession,
    repo: Repository,
    ctx: ExportContext,
    types: tuple[str, ...],
    include_global: bool,
    result: ExportResult,
) -> dict[PurePosixPath, tuple[str, str]]:
    """path -> (content, type_name). Entries that cannot render are written off."""
    planned: dict[PurePosixPath, tuple[str, str]] = {}

    for type_name in types:
        kb_type = REGISTRY[type_name]
        entries = await q_kb.entries_for_export(
            session, type_name, repo.id, include_global
        )

        # Pre-validate here rather than inside export(): one bad row must not
        # take out the whole type's file, and export() gets to stay pure.
        views: list[KbEntryView] = []
        for entry in entries:
            try:
                kb_type.validate_payload(entry.payload)
            except ValidationError as exc:
                result.failed.append(
                    {
                        "slug": entry.slug,
                        "type": type_name,
                        "error": f"payload invalid: {exc.error_count()} problem(s)",
                    }
                )
                continue
            if kb_type.assigns_seq and entry.seq is None:
                result.failed.append(
                    {"slug": entry.slug, "type": type_name, "error": "no seq assigned"}
                )
                continue
            view = KbEntryView.from_model(entry)
            result.warnings.extend(kb_type.validate_entry(view))
            views.append(view)

        if type_name == "glossary" and len(views) > GLOSSARY_WARN_AT:
            result.warnings.append(
                f"glossary: {len(views)} terms in one CONTEXT.md — a glossary "
                "this long is one nobody reads"
            )
        # entries_for_export dedupes on lower(title), but a one-file-per-entry
        # type names its file after the SLUG — so a global entry and a
        # repo-scoped override sharing a slug with different titles both
        # survive and collapse to one key inside export(), silently losing one.
        # Decisions are exempt: their filename carries seq, which disambiguates.
        if kb_type.export_dir is not None and not kb_type.assigns_seq:
            seen: dict[str, list[str]] = {}
            for view in views:
                seen.setdefault(view.slug.lower(), []).append(view.title)
            clashing = {slug for slug, titles in seen.items() if len(titles) > 1}
            for slug in sorted(clashing):
                result.failed.append(
                    {
                        "slug": slug,
                        "type": type_name,
                        "error": (
                            "two entries share this slug in the exported scope "
                            f"({', '.join(sorted(seen[slug]))}) and would render "
                            "to the same file"
                        ),
                    }
                )
            views = [v for v in views if v.slug.lower() not in clashing]

        if not views:
            continue

        views.sort(key=kb_type.sort_key)
        try:
            rendered = kb_type.export(views, ctx)
        except Exception as exc:  # a type's own rendering bug
            logger.exception("export failed for type %r", type_name)
            result.failed.append({"slug": None, "type": type_name, "error": str(exc)})
            continue

        for path, content in rendered.items():
            if not _is_safe(path):
                result.failed.append(
                    {"slug": None, "type": type_name, "error": f"unsafe path {path}"}
                )
                continue
            if path in planned:
                # Two entries rendering to one file. entries_for_export dedupes
                # on lower(title), so a global and a repo-scoped entry sharing a
                # slug but not a title both survive and land here — whichever
                # sorted later would silently win. Refuse both instead.
                result.failed.append(
                    {
                        "slug": path.stem,
                        "type": type_name,
                        "error": f"two entries render to {path} — slugs must be "
                        "unique within a type across the exported scope",
                    }
                )
                del planned[path]
                continue
            planned[path] = (content, type_name)
    return planned


async def run_export(
    session: AsyncSession,
    repo: Repository,
    out: Path,
    *,
    types: tuple[str, ...] | None = None,
    include_global: bool = True,
    dry_run: bool = False,
    force: bool = False,
    prune: bool = True,
    context_name: str | None = None,
    context_description: str = "",
) -> ExportResult:
    result = ExportResult(repository=repo.name, dry_run=dry_run)
    ctx = ExportContext(
        repository_name=repo.name,
        context_name=context_name or repo.name,
        context_description=context_description,
    )
    selected = types or LOOKUP_PRECEDENCE

    planned = await _render(session, repo, ctx, selected, include_global, result)

    manifest = read_manifest(out)
    manifest_files: dict[str, dict] = dict(manifest["files"])

    for path in sorted(planned, key=str):
        content, type_name = planned[path]
        target = out / path
        digest = sha256_text(content)
        key = str(path)

        if target.exists():
            on_disk = _read(target)
            if on_disk is None:
                # unreadable target (binary, wrong encoding, a directory) — we
                # cannot tell whose it is, so we must not touch it
                result.conflicts.append(key)
                continue
            if on_disk == content:
                # already correct: record it and report it as unchanged
                result.unchanged.append(key)
                manifest_files[key] = {"sha256": digest, "type": type_name}
                continue
            known = recorded_hash(manifest, path)
            if known is not None:
                # The manifest is authoritative when it has a record: a hash
                # mismatch means the file was edited since we wrote it. The
                # marker must NOT rescue this case — our own header survives a
                # hand edit, so trusting it here would silently discard one.
                ours = known == sha256_text(on_disk)
            else:
                # No record. The generated-by header is the only evidence left,
                # and it covers exactly one situation: a lost manifest.
                ours = _is_ours(on_disk)
            if not ours and not force:
                result.conflicts.append(key)
                continue

        if not dry_run:
            _atomic_write(target, content)
        result.written.append(key)
        manifest_files[key] = {"sha256": digest, "type": type_name}

    if prune:
        for key in sorted(set(manifest["files"]) - {str(p) for p in planned}):
            # The manifest is a plain file in the target repo, so its keys are
            # no more trustworthy than any other repo content: an absolute key
            # escapes `out / key` entirely and "../.." walks out of it. This is
            # the same check _render applies to rendered paths — pruning needs
            # it just as much, because it DELETES.
            if not _is_safe(PurePosixPath(key)):
                result.failed.append(
                    {"slug": None, "type": None, "error": f"unsafe manifest path {key}"}
                )
                manifest_files.pop(key, None)
                continue
            target = out / key
            if target.exists():
                on_disk = _read(target)
                if on_disk is None or (
                    sha256_text(on_disk) != manifest["files"][key].get("sha256")
                ):
                    # edited since we wrote it (or unreadable) — leave it alone
                    if not force:
                        result.conflicts.append(key)
                        continue
                if not dry_run:
                    target.unlink()
            result.pruned.append(key)
            manifest_files.pop(key, None)

    # Always persist, even on an all-unchanged run. Gating this on
    # written-or-pruned meant a deleted manifest was never rebuilt, which
    # silently disabled the "manifest is authoritative" check above and let the
    # marker fallback overwrite hand edits forever.
    if not dry_run:
        write_manifest(out, repo.name, manifest_files)
    return result


__all__ = ["ExportResult", "run_export", "MANIFEST_NAME"]
