# Slice 03 — Tier-1 Python extractor

## Goal

A pure, DB-free extraction module: given Python source files, it emits symbol records and reference records via tree-sitter, plus a shared language-agnostic resolver that turns raw references into candidate edges tagged `resolved` or `name_match`. This is the contract every other language extractor (slice 04) implements and the ingest loader (slice 05) consumes.

## Depends on

Slice 01 (package skeleton). No database — everything here is pure functions over source text, testable without containers.

## Spec references

`initial-spec.md` §3 Tier 1.

## Requirements

### 1. Shared contract — `extractors/base.py`

Frozen dataclasses, not ORM objects. This layer must not import `models.py`, sqlalchemy, or `cartograph.db` — kind/rel/confidence fields are plain strings whose values match the `NodeKind`/`EdgeRel`/`EdgeConfidence` enum values by convention (slice 05's loader maps them):

```python
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
    kind: str            # "call" | "inherits" | "attr_ref"
    src_qualified_name: str  # qualified name of the enclosing symbol (module qname at top level)
    target_expr: str     # dotted expression as written: "OrderService.save", "self.repo.get"
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
```

Also in `base.py`: `hash_content(source: bytes) -> str` (sha256 hex) and an extractor registry `get_extractor_for(path) -> Extractor | None` keyed by extension.

### 2. Python extractor — `extractors/python.py`

Built on `tree-sitter` + `tree-sitter-python` (add both to `pyproject.toml`; pin exact grammar version — grammar upgrades can shift node types and require re-extraction).

1. **Module qname:** derived from the repo-relative path: `pkg/orders.py → pkg.orders`, `pkg/__init__.py → pkg`.
2. **Symbols emitted:**
   - One `module` symbol per file spanning the whole file.
   - `class` for each `class_definition`, qname `module.Class` (nested classes `module.Outer.Inner`).
   - `function` for module-level `function_definition`s; `method` for functions directly inside a class body. Decorated definitions still count; the span includes decorators.
3. **Imports emitted** (`ImportRecord`):
   - `import a.b` → local `a`, target `a.b` (also record `a.b` reachable via the dotted prefix).
   - `import a.b as x` → local `x`, target `a.b`.
   - `from a.b import C` → local `C`, target `a.b.C`; with `as y` → local `y`.
   - Relative imports: resolve dots against the current module qname (`from ..models import Node` inside `pkg.sub.mod` → target `pkg.models.Node`). `from x import *` → single record with local `*` (the resolver treats it as "anything in `x` is importable here").
4. **Refs emitted:**
   - `call` for every `call` node: `target_expr` is the callee text (`foo`, `mod.foo`, `self.helper`). `src_qualified_name` is the nearest enclosing function/method/class qname, else the module qname.
   - `inherits` for each base in a class definition's superclass list.
   - `attr_ref` for attribute accesses on imported names that are not part of a call (keep this conservative: only when the leftmost identifier is an imported local name).
5. Syntax errors must not crash extraction: tree-sitter parses errors into `ERROR` nodes — extract what's recognizable and continue.

### 3. Resolver — `extractors/resolve.py`

Language-agnostic. Input: all `FileExtraction`s for a repo (for incremental runs, slice 05 reconstructs this view from the DB — not this slice's concern). Output: candidate edges.

```python
@dataclass(frozen=True)
class CandidateEdge:
    src_qname: str
    dst_qname: str
    rel: str         # "imports" | "calls" | "inherits" | "references"
    confidence: str  # "resolved" | "name_match"
    line: int | None
```

Rules (spec §3 tier 1, intentionally naive):

1. **Symbol table:** map `qualified_name → SymbolRecord` over all files; also a bare-name index `name → [qualified_names]`.
2. **Import edges:** for each `ImportRecord`, if `target` (or its longest prefix) exists in the symbol table, emit `imports` edge from the importing module qname to that symbol/module, `resolved`. Imports of names outside the repo (stdlib, third-party) emit nothing — the graph is intra-repo only.
3. **Ref resolution:** resolve `target_expr` against, in order:
   a. the file's imports: leftmost segment matches an import's `local_name` → substitute the import target, look up the resulting qname (and `qname + rest`) in the symbol table. Exactly one hit → edge with `confidence="resolved"`.
   b. same-module siblings: `module_qname + "." + target_expr` in the symbol table → `resolved`.
   c. bare-name fallback: last segment of `target_expr` in the bare-name index → one edge per candidate qname (cap at 5 candidates), `confidence="name_match"`.
   d. no candidates anywhere → drop the ref (external).
4. `self.x` / `cls.x` calls: try `enclosing_class_qname + "." + x` first (`resolved` if hit), else fall through to the bare-name fallback on `x`.
5. Ref kinds map to rels: `call → calls`, `inherits → inherits`, `attr_ref → references`.
6. Dedupe identical `(src, dst, rel, line)` tuples.

## Files

- `backend/src/cartograph/extractors/{__init__.py,base.py,resolve.py,python.py}`
- `backend/tests/extractors/fixtures/py_sample/` — a small fake package (see below)
- `backend/tests/extractors/test_python_extractor.py`, `test_resolver.py`

## Acceptance criteria

`uv run pytest tests/extractors/` passes, with fixtures covering at least:

1. A package `py_sample/` with `pkg/__init__.py`, `pkg/models.py` (two classes, one inheriting the other), `pkg/services.py` (class with methods calling across files via `from pkg.models import ...`), `pkg/util.py` (module-level functions), `pkg/cli.py` (relative import `from .services import ...`, aliased import, `import pkg.util as u` + `u.helper()` call).
2. Assertions that: qualified names and line spans are exact; the cross-file call via a single import resolves `resolved`; a name defined in two modules and called without an import yields `name_match` edges to both; inheritance produces an `inherits` edge; relative and aliased imports resolve; an unresolvable external call (`requests.get`) produces no edge; a file with a deliberate syntax error still yields its parseable symbols.
3. `content_hash` is stable across runs and changes when the symbol's source changes.
4. No file in `extractors/` imports sqlalchemy or `cartograph.db`.

## Out of scope

- Writing anything to the database (slice 05).
- TypeScript/JS (slice 04).
- LSP/analyzer-backed resolution (tier 2 — not sliced) and LLM resolution (slice 13 handles `name_match` triage).
