"""Markdown export of the knowledge base (slice 17).

One-way: Postgres is the source of truth and the files are a copy. There is no
import path, and there should not be a half-one — an edit to an exported file
is not read back, so the exporter's job is to make that visible rather than to
pretend at a round trip.
"""

from cartograph.kb.export.runner import ExportResult, run_export

__all__ = ["ExportResult", "run_export"]
