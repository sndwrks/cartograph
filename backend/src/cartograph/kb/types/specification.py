"""Specification: a contract of record. Humans write these."""

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


class Specification(KbType):
    name: ClassVar[str] = "specification"
    label: ClassVar[str] = "Specification"
    lookup_keys: ClassVar[tuple[LookupKey, ...]] = ("title", "slug")
    export_dir: ClassVar[str | None] = "docs/spec"

    class Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")

        summary: str = ""
        owner: str | None = None
        requirements: list[str] = []
        #: Qualified names, a soft link to the graph. Deliberately not an FK —
        #: node ids churn on re-ingestion and a dangling FK would block writes.
        related_nodes: list[str] = []

    @classmethod
    def embed_text(cls, view: KbEntryView) -> str:
        parts = [view.title, view.payload.get("summary", ""), view.body]
        return "\n\n".join(part for part in parts if part and part.strip())

    @classmethod
    def export(
        cls, entries: Sequence[KbEntryView], ctx: ExportContext
    ) -> dict[PurePosixPath, str]:
        out: dict[PurePosixPath, str] = {}
        for view in entries:
            payload = view.payload
            lines = [ctx.marker(cls.name, view.slug), "", f"# {view.title}", ""]
            if payload.get("owner"):
                lines += [f"- Owner: {payload['owner']}", ""]
            if (payload.get("summary") or "").strip():
                lines += [payload["summary"].strip(), ""]
            section(lines, "Specification", view.body)
            bullets(lines, "Requirements", payload.get("requirements") or [])
            related = [f"`{n}`" for n in (payload.get("related_nodes") or []) if str(n).strip()]
            bullets(lines, "Related code", related)
            out[file_path(cls, view.slug)] = render(lines)
        return out
