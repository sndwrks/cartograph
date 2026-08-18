"""Runbook: operational steps. Humans write these."""

from __future__ import annotations

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

Severity = Literal["low", "medium", "high"]


class Runbook(KbType):
    name: ClassVar[str] = "runbook"
    label: ClassVar[str] = "Runbook"
    lookup_keys: ClassVar[tuple[LookupKey, ...]] = ("title", "slug")
    export_dir: ClassVar[str | None] = "docs/runbook"

    class Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")

        trigger: str = ""
        severity: Severity | None = None
        steps: list[str] = []
        verification: str = ""
        rollback: str = ""

    @classmethod
    def embed_text(cls, view: KbEntryView) -> str:
        parts = [view.title, view.payload.get("trigger", ""), view.body]
        return "\n\n".join(part for part in parts if part and part.strip())

    @classmethod
    def export(
        cls, entries: Sequence[KbEntryView], ctx: ExportContext
    ) -> dict[PurePosixPath, str]:
        out: dict[PurePosixPath, str] = {}
        for view in entries:
            payload = view.payload
            lines = [ctx.marker(cls.name, view.slug), "", f"# {view.title}", ""]
            if payload.get("severity"):
                lines += [f"- Severity: {payload['severity']}", ""]
            if view.body.strip():
                lines += [view.body.strip(), ""]
            section(lines, "Trigger", payload.get("trigger", ""))
            steps = [s for s in (payload.get("steps") or []) if str(s).strip()]
            if steps:
                lines += ["## Steps", ""]
                lines += [f"{i}. {step}" for i, step in enumerate(steps, start=1)]
                lines.append("")
            section(lines, "Verification", payload.get("verification", ""))
            section(lines, "Rollback", payload.get("rollback", ""))
            out[file_path(cls, view.slug)] = render(lines)
        return out
