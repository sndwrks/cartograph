"""Shared extraction contract (slice 03).

This layer must stay DB-free: no imports of sqlalchemy, codegraph.db, or
codegraph.models. Kind/rel/confidence fields are plain strings whose values
match the NodeKind/EdgeRel/EdgeConfidence enum values by convention — the
ingest loader (slice 05) maps them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol


@dataclass(frozen=True)
class SymbolRecord:
    kind: str            # "module" | "class" | "function" | "method"
    name: str            # bare name, e.g. "save"
    qualified_name: str  # e.g. "pkg.orders.OrderService.save"
    start_line: int      # 1-based, inclusive
    end_line: int
    content_hash: str    # sha256 hex of the symbol's exact source slice


@dataclass(frozen=True)
class ImportRecord:
    local_name: str      # the name usable in this file, e.g. "OrderService" or "np"
    target: str          # qualified target as written, e.g. "pkg.orders.OrderService", "numpy"
    line: int


@dataclass(frozen=True)
class RefRecord:
    kind: str                # "call" | "inherits" | "attr_ref"
    src_qualified_name: str  # qualified name of the enclosing symbol (module qname at top level)
    target_expr: str         # dotted expression as written: "OrderService.save", "self.repo.get"
    line: int


@dataclass(frozen=True)
class FileExtraction:
    path: str            # repo-relative, posix
    language: str        # "python" | "typescript" | "javascript"
    module_qname: str    # e.g. "pkg.orders" for pkg/orders.py
    symbols: list[SymbolRecord]
    imports: list[ImportRecord]
    refs: list[RefRecord]


class Extractor(Protocol):
    language: str
    extensions: tuple[str, ...]

    def extract(self, path: str, source: bytes) -> FileExtraction: ...


def hash_content(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


_REGISTRY: dict[str, Extractor] = {}


def register(extractor: Extractor) -> None:
    for ext in extractor.extensions:
        _REGISTRY[ext] = extractor


def get_extractor_for(path: str) -> Extractor | None:
    return _REGISTRY.get(PurePosixPath(path).suffix)
