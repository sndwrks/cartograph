"""Language-agnostic tier-1 resolver: raw records -> candidate edges (slice 03).

Intentionally naive per initial-spec.md §3 tier 1. Operates only on the
dataclasses from base.py; nothing here is Python-the-language specific.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .base import FileExtraction, SymbolRecord

_NAME_MATCH_CAP = 5

_REL_FOR_REF = {"call": "calls", "inherits": "inherits", "attr_ref": "references"}


@dataclass(frozen=True)
class CandidateEdge:
    src_qname: str
    dst_qname: str
    rel: str         # "imports" | "calls" | "inherits" | "references"
    confidence: str  # "resolved" | "name_match"
    line: int | None


def _build_indexes(
    extractions: Sequence[FileExtraction],
    extra_symbols: Sequence[SymbolRecord] = (),
) -> tuple[dict[str, SymbolRecord], dict[str, list[str]]]:
    symbol_table: dict[str, SymbolRecord] = {}
    for sym in extra_symbols:
        symbol_table[sym.qualified_name] = sym
    for extraction in extractions:
        for sym in extraction.symbols:
            symbol_table[sym.qualified_name] = sym
    bare_index: dict[str, list[str]] = {}
    for sym in symbol_table.values():
        # modules stay out of the bare index: a local named "util" must not
        # name_match every pkg.util module
        if sym.kind != "module":
            bare_index.setdefault(sym.name, []).append(sym.qualified_name)
    return symbol_table, bare_index


def _longest_prefix_hit(qname: str, symbol_table: dict[str, SymbolRecord]) -> str | None:
    parts = qname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in symbol_table:
            return candidate
    return None


def _enclosing_class_qname(
    src_qname: str, symbol_table: dict[str, SymbolRecord]
) -> str | None:
    parts = src_qname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        sym = symbol_table.get(candidate)
        if sym is not None and sym.kind == "class":
            return candidate
    return None


def resolve(
    extractions: Sequence[FileExtraction],
    extra_symbols: Sequence[SymbolRecord] = (),
) -> list[CandidateEdge]:
    """Resolve refs to candidate edges.

    extra_symbols extends the symbol table with records not re-extracted this
    run (slice 05 passes the whole-repo table loaded from the DB); extraction
    symbols win on qname collision.
    """
    symbol_table, bare_index = _build_indexes(extractions, extra_symbols)

    edges: list[CandidateEdge] = []
    seen: set[tuple[str, str, str, int | None]] = set()

    def emit(src: str, dst: str, rel: str, confidence: str, line: int | None) -> None:
        key = (src, dst, rel, line)
        if key not in seen:
            seen.add(key)
            edges.append(CandidateEdge(src, dst, rel, confidence, line))

    for extraction in extractions:
        for imp in extraction.imports:
            hit = _longest_prefix_hit(imp.target, symbol_table)
            if hit is not None:
                emit(extraction.module_qname, hit, "imports", "resolved", imp.line)

    for extraction in extractions:
        import_map = {
            imp.local_name: imp.target
            for imp in extraction.imports
            if imp.local_name != "*"
        }
        star_targets = [
            imp.target for imp in extraction.imports if imp.local_name == "*"
        ]

        for ref in extraction.refs:
            rel = _REL_FOR_REF[ref.kind]
            expr = ref.target_expr

            def bare_fallback(name: str) -> bool:
                candidates = sorted(bare_index.get(name, []))[:_NAME_MATCH_CAP]
                for dst in candidates:
                    emit(ref.src_qualified_name, dst, rel, "name_match", ref.line)
                return bool(candidates)

            # rule 4: self./cls./this. resolve against the enclosing class first
            left, _, rest = expr.partition(".")
            if left in ("self", "cls", "this") and rest:
                cls_qname = _enclosing_class_qname(ref.src_qualified_name, symbol_table)
                if cls_qname is not None and f"{cls_qname}.{rest}" in symbol_table:
                    emit(
                        ref.src_qualified_name,
                        f"{cls_qname}.{rest}",
                        rel,
                        "resolved",
                        ref.line,
                    )
                else:
                    bare_fallback(rest.rsplit(".", 1)[-1])
                continue

            # rule 3a: substitute the leftmost segment via this file's imports;
            # prefer the deeper (full-substitution) hit over the bare target
            if left in import_map:
                target = import_map[left]
                full = f"{target}.{rest}" if rest else target
                dst = full if full in symbol_table else (
                    target if target in symbol_table else None
                )
                if dst is not None:
                    emit(ref.src_qualified_name, dst, rel, "resolved", ref.line)
                    continue
            hit = next(
                (
                    f"{t}.{expr}"
                    for t in star_targets
                    if f"{t}.{expr}" in symbol_table
                ),
                None,
            )
            if hit is not None:
                emit(ref.src_qualified_name, hit, rel, "resolved", ref.line)
                continue

            # rule 3b: same-module sibling
            sibling = f"{extraction.module_qname}.{expr}"
            if sibling in symbol_table:
                emit(ref.src_qualified_name, sibling, rel, "resolved", ref.line)
                continue

            # rule 3c: bare-name fallback; rule 3d: no candidates -> drop
            bare_fallback(expr.rsplit(".", 1)[-1])

    return edges
