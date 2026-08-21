"""Language-agnostic tier-1 resolver: raw records -> candidate edges (slice 03).

Intentionally naive per initial-spec.md §3 tier 1. Operates only on the
dataclasses from base.py; nothing here is Python-the-language specific.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .base import FileExtraction, SymbolRecord

_NAME_MATCH_CAP = 5
# a 1-2 char identifier (t, x, cb) says nothing about identity
_NAME_MATCH_MIN_LEN = 3
# when several symbols share the name, generic 3-char verbs (set, has, get)
# manufacture hub nodes; ambiguity demands a more distinctive name. Both
# guards depend only on the name and the repo-wide symbol table, so full and
# incremental runs produce identical edges
_NAME_MATCH_AMBIGUOUS_MIN_LEN = 4

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


def _import_map(extraction: FileExtraction) -> dict[str, str]:
    return {
        imp.local_name: imp.target
        for imp in extraction.imports
        if imp.local_name != "*"
    }


def _star_targets(extraction: FileExtraction) -> list[str]:
    return [imp.target for imp in extraction.imports if imp.local_name == "*"]


def _resolve_via_imports(
    expr: str,
    import_map: dict[str, str],
    star_targets: Sequence[str],
    module_qname: str,
    symbol_table: dict[str, SymbolRecord],
) -> tuple[str | None, bool]:
    """Resolve a dotted expression through this file's imports, star-imports,
    or same-module siblings. Returns (dst qname or None, known_import): when
    known_import is True the expression's base IS an import, so a miss means
    an external package and the caller should drop the ref rather than guess.

    The single resolution path shared by the refs loop and _field_types —
    rule 3a/3b semantics live here and only here.
    """
    left, _, rest = expr.partition(".")
    if left in import_map:
        target = import_map[left]
        candidates = [f"{target}.{rest}" if rest else target, target]
        if target.endswith(".default"):
            # `import Foo from "./foo"` records `<module>.default`, but a
            # *named* default export (`export default class Foo`) emits its
            # own name — retry as `<module>.<local name>`, then the module
            base = target[: -len(".default")]
            named = f"{base}.{left}"
            candidates += [f"{named}.{rest}" if rest else named, base]
        for candidate in candidates:
            if candidate in symbol_table:
                return candidate, True
        return None, True
    for star in star_targets:
        if f"{star}.{expr}" in symbol_table:
            return f"{star}.{expr}", False
    sibling = f"{module_qname}.{expr}"
    if sibling in symbol_table:
        return sibling, False
    return None, False


_CONFLICTED = object()


def _field_types(
    extractions: Sequence[FileExtraction],
    symbol_table: dict[str, SymbolRecord],
) -> dict[tuple[str, str], str]:
    """(class qname, field name) -> collaborator class qname, from
    `this.field = new ClassName()` assignments. A field assigned different
    constructors in different places is ambiguous and dropped — a resolved
    edge must not encode a branch-dependent guess."""
    types: dict[tuple[str, str], object] = {}
    for extraction in extractions:
        if not extraction.field_assigns:
            continue
        import_map = _import_map(extraction)
        star_targets = _star_targets(extraction)
        for fa in extraction.field_assigns:
            dst, _ = _resolve_via_imports(
                fa.ctor_expr,
                import_map,
                star_targets,
                extraction.module_qname,
                symbol_table,
            )
            if dst is None:
                continue
            key = (fa.class_qname, fa.field_name)
            if key in types and types[key] != dst:
                types[key] = _CONFLICTED
            else:
                types.setdefault(key, dst)
    return {
        key: dst for key, dst in types.items() if isinstance(dst, str)
    }


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
    field_types = _field_types(extractions, symbol_table)

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
        import_map = _import_map(extraction)
        star_targets = _star_targets(extraction)

        for ref in extraction.refs:
            rel = _REL_FOR_REF[ref.kind]
            expr = ref.target_expr

            def bare_fallback(name: str) -> bool:
                if len(name) < _NAME_MATCH_MIN_LEN:
                    return False
                candidates = bare_index.get(name, [])
                # a name shared by more symbols than the cap is ambiguous, not
                # evidence: emitting an arbitrary subset manufactures hairballs
                if not candidates or len(candidates) > _NAME_MATCH_CAP:
                    return False
                if (
                    len(candidates) > 1
                    and len(name) < _NAME_MATCH_AMBIGUOUS_MIN_LEN
                ):
                    return False
                for dst in sorted(candidates):
                    emit(ref.src_qualified_name, dst, rel, "name_match", ref.line)
                return True

            # rule 4: self./cls./this. resolve against the enclosing class first
            left, _, rest = expr.partition(".")
            if left in ("self", "cls", "this") and rest:
                cls_qname = _enclosing_class_qname(ref.src_qualified_name, symbol_table)
                if cls_qname is not None:
                    if f"{cls_qname}.{rest}" in symbol_table:
                        emit(
                            ref.src_qualified_name,
                            f"{cls_qname}.{rest}",
                            rel,
                            "resolved",
                            ref.line,
                        )
                        continue
                    # rule 4b: this.field.method() via a constructor-assigned
                    # collaborator (`this.field = new ClassName()`)
                    fld, _, chain = rest.partition(".")
                    if chain:
                        field_class = field_types.get((cls_qname, fld))
                        if (
                            field_class is not None
                            and f"{field_class}.{chain}" in symbol_table
                        ):
                            emit(
                                ref.src_qualified_name,
                                f"{field_class}.{chain}",
                                rel,
                                "resolved",
                                ref.line,
                            )
                            continue
                bare_fallback(rest.rsplit(".", 1)[-1])
                continue

            # rules 3a/3b: imports (with default-export retry), star-imports,
            # same-module siblings — shared with _field_types
            dst, known_import = _resolve_via_imports(
                expr, import_map, star_targets, extraction.module_qname, symbol_table
            )
            if dst is not None:
                emit(ref.src_qualified_name, dst, rel, "resolved", ref.line)
                continue
            if known_import:
                # the ref's provenance is a known import; a symbol-table miss
                # means an external package, and a bare fallback would only
                # name_match unrelated same-named locals
                continue

            # rule 3c: bare-name fallback; rule 3d: no candidates -> drop
            bare_fallback(expr.rsplit(".", 1)[-1])

    return edges
