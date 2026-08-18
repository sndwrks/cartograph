"""Decision: an ADR — what was chosen, and what it beat."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from cartograph.kb.types.base import (
    ExportContext,
    KbType,
    LookupKey,
    file_path,
    render,
    section,
)
from cartograph.kb.views import KbEntryView

DecisionStatus = Literal["proposed", "accepted", "rejected", "superseded", "deprecated"]


class Decision(KbType):
    name: ClassVar[str] = "decision"
    label: ClassVar[str] = "Decision (ADR)"
    lookup_keys: ClassVar[tuple[LookupKey, ...]] = ("title", "slug")
    assigns_seq: ClassVar[bool] = True
    export_dir: ClassVar[str | None] = "docs/adr"

    class Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")

        # Named apart from the row's publication `status` on purpose: an ADR's
        # own "## Status" (accepted/superseded) is a different axis from
        # whether the entry is proposed/published, and one name for both is a
        # bug waiting to happen.
        decision_status: DecisionStatus = "accepted"
        date: datetime.date | None = None
        deciders: list[str] = []
        context: str = ""
        consequences: str = ""
        supersedes: list[str] = []  # slugs

    @classmethod
    def embed_text(cls, view: KbEntryView) -> str:
        payload = view.payload
        parts = [
            view.title,
            payload.get("context", ""),
            view.body,
            payload.get("consequences", ""),
        ]
        return "\n\n".join(part for part in parts if part and part.strip())

    @classmethod
    def sort_key(cls, view: KbEntryView) -> tuple:
        # ADRs read in decision order, not alphabetically.
        return (view.seq,)

    @classmethod
    def export(
        cls, entries: Sequence[KbEntryView], ctx: ExportContext
    ) -> dict[PurePosixPath, str]:
        out: dict[PurePosixPath, str] = {}
        for view in entries:
            if view.seq is None:
                # assigns_seq is True, so a published decision always has one;
                # the exporter pre-validates and never hands us a broken row.
                raise ValueError(f"decision {view.slug!r} has no seq")
            payload = view.payload
            lines = [
                ctx.marker(cls.name, view.slug),
                "",
                f"# {view.seq:04d}. {view.title}",
                "",
                f"- Status: {payload.get('decision_status', 'accepted')}",
            ]
            if payload.get("date"):
                lines.append(f"- Date: {payload['date']}")
            deciders = [d for d in (payload.get("deciders") or []) if str(d).strip()]
            if deciders:
                lines.append(f"- Deciders: {', '.join(deciders)}")
            supersedes = [s for s in (payload.get("supersedes") or []) if str(s).strip()]
            if supersedes:
                lines.append(f"- Supersedes: {', '.join(supersedes)}")
            lines.append("")
            section(lines, "Context", payload.get("context", ""))
            section(lines, "Decision", view.body)
            section(lines, "Consequences", payload.get("consequences", ""))
            out[file_path(cls, f"{view.seq:04d}-{view.slug}")] = render(lines)
        return out
