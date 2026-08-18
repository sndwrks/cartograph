"""Convention: a house rule — "how we do X here"."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from cartograph.kb.types.base import (
    ExportContext,
    KbType,
    LookupKey,
    bullets,
    file_path,
    render,
    section,
)
from cartograph.kb.views import KbEntryView


class ConventionExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    good: str | None = None
    bad: str | None = None
    note: str = ""


class Convention(KbType):
    name: ClassVar[str] = "convention"
    label: ClassVar[str] = "Convention"
    lookup_keys: ClassVar[tuple[LookupKey, ...]] = ("title", "slug", "aliases")
    export_dir: ClassVar[str | None] = "docs/convention"

    class Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")

        applies_to: list[str] = []  # path globs
        rationale: str = ""
        examples: list[ConventionExample] = []

    @classmethod
    def embed_text(cls, view: KbEntryView) -> str:
        parts = [view.title, view.body, view.payload.get("rationale", "")]
        return "\n\n".join(part for part in parts if part and part.strip())

    @classmethod
    def export(
        cls, entries: Sequence[KbEntryView], ctx: ExportContext
    ) -> dict[PurePosixPath, str]:
        out: dict[PurePosixPath, str] = {}
        for view in entries:
            payload = view.payload
            lines = [ctx.marker(cls.name, view.slug), "", f"# {view.title}", ""]
            if view.body.strip():
                lines += [view.body.strip(), ""]
            section(lines, "Rationale", payload.get("rationale", ""))
            globs = [f"`{g}`" for g in (payload.get("applies_to") or []) if str(g).strip()]
            bullets(lines, "Applies to", globs)
            examples = payload.get("examples") or []
            if examples:
                lines += ["## Examples", ""]
                for example in examples:
                    if example.get("good"):
                        lines += ["Do:", "", "```", example["good"].strip(), "```", ""]
                    if example.get("bad"):
                        lines += ["Avoid:", "", "```", example["bad"].strip(), "```", ""]
                    if (example.get("note") or "").strip():
                        lines += [example["note"].strip(), ""]
            out[file_path(cls, view.slug)] = render(lines)
        return out
