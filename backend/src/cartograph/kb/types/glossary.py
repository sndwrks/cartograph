"""Glossary: one project term, one sanctioned meaning."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from cartograph.kb.types.base import ExportContext, KbType, LookupKey, render
from cartograph.kb.views import KbEntryView

#: The reference model's discipline: a definition is one or two sentences.
#: Lint only — see `KbType.validate_entry`.
MAX_SENTENCES = 2

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


class Glossary(KbType):
    name: ClassVar[str] = "glossary"
    label: ClassVar[str] = "Glossary term"
    # `aliases` here is the top-level ARRAY(Text) column that the tier-2 lookup
    # SQL reads — NOT a payload field. One home only; a second would drift.
    lookup_keys: ClassVar[tuple[LookupKey, ...]] = ("title", "aliases")
    export_dir: ClassVar[str | None] = None  # repo-root CONTEXT.md

    class Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")

        #: Synonyms this project has decided *against*. Rendered as `_Avoid_:`.
        avoid: list[str] = []

    @classmethod
    def embed_text(cls, view: KbEntryView) -> str:
        # Byte-identical to the pre-typed-KB f-string in enrich/kb.py, so every
        # migrated row keeps the embedding it already paid for.
        return f"{view.title}: {view.body}"

    @classmethod
    def validate_entry(cls, view: KbEntryView) -> list[str]:
        warnings: list[str] = []
        sentences = len(_SENTENCE_END.findall(view.body.strip()))
        if sentences > MAX_SENTENCES:
            warnings.append(
                f"{view.slug}: definition runs to {sentences} sentences "
                f"(the glossary rule is {MAX_SENTENCES})"
            )
        return warnings

    @classmethod
    def export(
        cls, entries: Sequence[KbEntryView], ctx: ExportContext
    ) -> dict[PurePosixPath, str]:
        """Every glossary term into one root CONTEXT.md."""
        lines = [ctx.marker(cls.name), "", f"# {ctx.context_name}", ""]
        if ctx.context_description:
            lines += [ctx.context_description, ""]
        lines += ["## Language", ""]
        for view in entries:
            lines.append(f"**{view.title}**:")
            lines.append(view.body.strip())
            avoid = [a for a in (view.payload.get("avoid") or []) if str(a).strip()]
            if avoid:
                lines.append(f"_Avoid_: {', '.join(avoid)}")
            lines.append("")
        return {PurePosixPath("CONTEXT.md"): render(lines)}
