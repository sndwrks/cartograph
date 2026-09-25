"""Tier-1 Rust extractor built on tree-sitter.

Rust's own module system is path-based (`src/foo/bar.rs` is `crate::foo::bar`
by convention), which the qualified names below lean on directly rather than
tracing `mod` declarations. `module_qname_for_path` needs to know where the
owning crate's `Cargo.toml` lives to root `crate::`/anchor `lib.rs`, so unlike
the Python extractor it takes a `RustResolutionContext` (discovered once per
repo by the ingest loader, mirroring `ts_context.py`) via the shared
`context` parameter.

`crate::`, `self::` and `super::` path prefixes, and the `Self` type alias
inside `impl` blocks, are resolved to concrete qualified-name prefixes right
here at extraction time (not deferred to resolve.py) — by the time a
RefRecord/ImportRecord leaves this module its target is either a plain
sibling-style relative path (the same shape Python/TS already produce, and
the existing tier-1 resolver's import/sibling/bare-name pipeline resolves
it unchanged) or an absolute crate-rooted path, which needs exactly one
small Rust-specific branch in resolve.py (a direct symbol-table lookup)
before falling into that same shared pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node, Parser

from .base import (
    FieldAssignRecord,
    FileExtraction,
    ImportRecord,
    RefRecord,
    SymbolRecord,
    hash_content,
)

if TYPE_CHECKING:
    from .rust_context import RustResolutionContext

_RUST_LANGUAGE = Language(tsrust.language())

# node types that flatten to a plain identifier segment in a `::` path
_PATH_LEAVES = ("identifier", "type_identifier", "self", "crate", "super")


def module_qname_for_path(
    path: str, context: RustResolutionContext | None = None
) -> str:
    """Rust module qname for a repo-relative `.rs` file.

    `<crate>/src/foo/bar.rs` -> `<lib_ident>.foo.bar`; `mod.rs`/`lib.rs`
    collapse into their parent directory, matching Python's `__init__.py`
    handling. `main.rs` (and `src/bin/<name>.rs`/`.../main.rs`) is treated
    as its own, disjoint crate root rather than a submodule of the library
    crate: Tauri's `src-tauri/src/{lib,main}.rs` is the common case of a
    package shipping both a lib and a bin target from the same `src/` dir,
    and Rust itself treats them as separate crates — collapsing both to one
    qname would collide on the DB's (repository_id, qualified_name, kind)
    uniqueness constraint. `src/bin/foo.rs`/`src/bin/foo/main.rs` similarly
    become `<pkg>.bin.foo`, each a root of its own (nested modules under a
    secondary binary aren't traced further; a rare enough layout that a flat
    single-file treatment is an acceptable tier-1 gap).

    Without a context, or for a file outside any discovered crate, falls
    back to a plain dotted path so the file still gets a usable qname (just
    without crate-relative `use`/`crate::` resolution).
    """
    parts = path.split("/")
    stem = parts[-1]
    parts[-1] = stem.removesuffix(".rs")

    crate_dir = pkg_ident = lib_ident = None
    if context is not None:
        importing_dir = "/".join(parts[:-1])
        hit = context.nearest_crate(importing_dir)
        if hit is not None:
            crate_dir, pkg_ident, lib_ident = hit

    if crate_dir is None:
        if parts[-1] in ("mod", "lib", "main"):
            parts.pop()
        return ".".join(parts) if parts else "crate"

    crate_parts = [p for p in crate_dir.split("/") if p]
    src_parts = parts[len(crate_parts):]
    if src_parts and src_parts[0] == "src":
        src_parts = src_parts[1:]
    else:
        # outside src/ (build.rs, examples/, tests/): anchor to the package,
        # no lib/main disambiguation applies
        return ".".join([pkg_ident, *src_parts]) if src_parts else pkg_ident

    if src_parts == ["main"]:
        return f"{pkg_ident}.main"
    if len(src_parts) >= 2 and src_parts[0] == "bin":
        bin_rest = src_parts[1:]
        if len(bin_rest) > 1 and bin_rest[-1] == "main":
            bin_rest = bin_rest[:-1]
        return ".".join([pkg_ident, "bin", *bin_rest])
    if src_parts and src_parts[-1] in ("mod", "lib"):
        src_parts = src_parts[:-1]
    return ".".join([lib_ident, *src_parts]) if src_parts else lib_ident


def _text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line(node: Node) -> int:
    return node.start_point.row + 1


def _path_dotted(source: bytes, node: Node) -> str | None:
    """Flatten a `::`-separated path expression to dotted text (generics
    dropped). `crate`/`self`/`super` survive as literal leading segments —
    substituting them needs scope context this function doesn't have; see
    `_substitute_root`, applied by the caller."""
    if node.type in _PATH_LEAVES:
        return _text(source, node)
    if node.type == "scoped_identifier":
        path = node.child_by_field_name("path")
        name = node.child_by_field_name("name")
        if name is None:
            return None
        if path is None:
            return _text(source, name)
        left = _path_dotted(source, path)
        return f"{left}.{_text(source, name)}" if left is not None else None
    if node.type in ("generic_type", "scoped_type_identifier"):
        inner = node.child_by_field_name("type") or node.child_by_field_name("path")
        return _path_dotted(source, inner) if inner is not None else None
    if node.type == "generic_function":
        fn = node.child_by_field_name("function")
        return _path_dotted(source, fn) if fn is not None else None
    return None


def _field_chain(source: bytes, node: Node) -> str | None:
    """Flatten a `.`-separated field-access chain (`self.repo.get`,
    `widget.greet`). Any base is accepted, same as Python's `_dotted_text`
    on `attribute` nodes — only `self.*` gets special resolver treatment,
    via the generic self/cls/this rule already in resolve.py."""
    if node.type in ("identifier", "self"):
        return _text(source, node)
    if node.type == "field_expression":
        value = node.child_by_field_name("value")
        field = node.child_by_field_name("field")
        if value is None or field is None:
            return None
        left = _field_chain(source, value)
        return f"{left}.{_text(source, field)}" if left is not None else None
    return None


def _substitute_root(dotted: str, crate_root: str, cur_module_qname: str) -> str:
    """Resolve a leading `crate`/`self`/`super` segment (module-relative
    Rust path syntax) against this file's crate root / current module scope.
    A `Self` (capital) leading segment — the impl block's own type — is
    substituted by the caller, which alone knows the enclosing class scope;
    everything else passes through unchanged for the shared import/sibling/
    bare-name pipeline in resolve.py to handle."""
    if dotted == "crate" or dotted.startswith("crate."):
        rest = dotted[len("crate."):] if dotted.startswith("crate.") else ""
        return f"{crate_root}.{rest}" if rest else crate_root
    if dotted == "self" or dotted.startswith("self."):
        rest = dotted[len("self."):] if dotted.startswith("self.") else ""
        return f"{cur_module_qname}.{rest}" if rest else cur_module_qname
    if dotted == "super" or dotted.startswith("super."):
        segments = dotted.split(".")
        parts = cur_module_qname.split(".")
        i = 0
        while i < len(segments) and segments[i] == "super":
            if len(parts) > 1:
                parts = parts[:-1]
            i += 1
        remainder = segments[i:]
        return ".".join([*parts, *remainder]) if remainder else ".".join(parts)
    return dotted


def _use_targets(
    source: bytes, node: Node, prefix: str | None
) -> list[tuple[str, str]]:
    """(local_name, dotted target) pairs from a `use_declaration` argument
    subtree, syntax-only — `crate`/`self`/`super` substitution happens once
    per yielded target in the caller, which has the scope context."""
    if node.type in ("identifier", "type_identifier"):
        name = _text(source, node)
        return [(name, f"{prefix}.{name}" if prefix else name)]
    if node.type == "self":
        name = prefix.rsplit(".", 1)[-1] if prefix else "self"
        return [(name, prefix or name)]
    if node.type in ("scoped_identifier", "scoped_type_identifier"):
        path = node.child_by_field_name("path")
        name = node.child_by_field_name("name")
        if name is None:
            return []
        left = _path_dotted(source, path) if path is not None else None
        combined = f"{prefix}.{left}" if prefix and left else (left or prefix)
        name_text = _text(source, name)
        target = f"{combined}.{name_text}" if combined else name_text
        return [(name_text, target)]
    if node.type == "use_as_clause":
        path = node.child_by_field_name("path")
        alias = node.child_by_field_name("alias")
        if path is None or alias is None:
            return []
        target_path = _path_dotted(source, path)
        if target_path is None:
            return []
        full = f"{prefix}.{target_path}" if prefix else target_path
        return [(_text(source, alias), full)]
    if node.type == "use_wildcard":
        inner = node.named_children[0] if node.named_children else None
        path_text = _path_dotted(source, inner) if inner is not None else None
        full = f"{prefix}.{path_text}" if prefix and path_text else (path_text or prefix)
        return [("*", full)] if full else []
    if node.type == "scoped_use_list":
        path = node.child_by_field_name("path")
        lst = node.child_by_field_name("list")
        left = _path_dotted(source, path) if path is not None else None
        combined = f"{prefix}.{left}" if prefix and left else (left or prefix)
        if lst is None:
            return []
        out: list[tuple[str, str]] = []
        for child in lst.named_children:
            out.extend(_use_targets(source, child, combined))
        return out
    if node.type == "use_list":
        out = []
        for child in node.named_children:
            out.extend(_use_targets(source, child, prefix))
        return out
    return []


class RustExtractor:
    language = "rust"
    extensions = (".rs",)

    def extract(
        self, path: str, source: bytes, context: RustResolutionContext | None = None
    ) -> FileExtraction:
        module_qname = module_qname_for_path(path, context)
        crate_root = module_qname.split(".", 1)[0]
        parser = Parser(_RUST_LANGUAGE)
        root = parser.parse(source).root_node

        end_line = max(1, source.count(b"\n") + (0 if source.endswith(b"\n") else 1))
        symbols: list[SymbolRecord] = [
            SymbolRecord(
                kind="module",
                name=module_qname.rsplit(".", 1)[-1],
                qualified_name=module_qname,
                start_line=1,
                end_line=end_line,
                content_hash=hash_content(source),
            )
        ]
        imports: list[ImportRecord] = []
        refs: list[RefRecord] = []
        field_assigns: list[FieldAssignRecord] = []
        # ("module" | "class" | "function" | "method", qualified_name)
        scopes: list[tuple[str, str]] = [("module", module_qname)]

        def nearest(kind: str) -> str | None:
            return next((q for k, q in reversed(scopes) if k == kind), None)

        def resolve_path_ref(node: Node) -> str | None:
            dotted = _path_dotted(source, node)
            if dotted is None:
                return None
            head = dotted.split(".", 1)[0]
            if head == "Self":
                cls = nearest("class")
                if cls is None:
                    return None
                rest = dotted[len("Self."):] if dotted.startswith("Self.") else ""
                return f"{cls}.{rest}" if rest else cls
            return _substitute_root(dotted, crate_root, nearest("module") or module_qname)

        def emit_use(node: Node) -> None:
            arg = node.child_by_field_name("argument")
            if arg is None:
                return
            line = _line(node)
            cur_module = nearest("module") or module_qname
            for local, target in _use_targets(source, arg, None):
                imports.append(
                    ImportRecord(
                        local, _substitute_root(target, crate_root, cur_module), line
                    )
                )

        def emit_item(node: Node) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:  # fragmentary node inside an ERROR region
                return
            name = _text(source, name_node)
            qname = f"{scopes[-1][1]}.{name}"
            symbols.append(
                SymbolRecord(
                    kind="class",
                    name=name,
                    qualified_name=qname,
                    start_line=_line(node),
                    end_line=node.end_point.row + 1,
                    content_hash=hash_content(source[node.start_byte : node.end_byte]),
                )
            )
            # struct/enum/trait bodies hold fields/variants/signatures, not
            # code worth recursing into — same choice the TS extractor makes
            # for `interface`/`type` declarations

        def _impl_target_qname(type_node: Node) -> str | None:
            """The `impl` header's `type` field determines where this
            block's methods actually attach, so — unlike an ordinary ref —
            it must be resolved now, not deferred to resolve.py. An
            absolute crate/self/super/Self-qualified path resolves to
            itself; a plain type name (the common `impl Widget { .. }`
            case) is a sibling of the impl block, qualified under the
            impl's own scope — mirroring where `emit_item` would have
            qualified that struct."""
            raw = _path_dotted(source, type_node)
            if raw is None:
                return None
            if raw.split(".", 1)[0] in ("crate", "self", "super", "Self"):
                return resolve_path_ref(type_node)
            return f"{scopes[-1][1]}.{raw}"

        def emit_impl(node: Node) -> None:
            type_node = node.child_by_field_name("type")
            if type_node is None:
                return
            target_qname = _impl_target_qname(type_node)
            if target_qname is None:
                return
            trait_node = node.child_by_field_name("trait")
            if trait_node is not None:
                # left bare (like Python/TS base-class refs): the shared
                # import/sibling/bare-name pipeline resolves it from here
                trait_text = resolve_path_ref(trait_node)
                if trait_text is not None:
                    refs.append(
                        RefRecord("inherits", target_qname, trait_text, _line(trait_node))
                    )
            scopes.append(("class", target_qname))
            body = node.child_by_field_name("body")
            for child in (body.named_children if body is not None else []):
                visit(child)
            scopes.pop()

        def emit_fn(node: Node) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = _text(source, name_node)
            kind = "method" if scopes[-1][0] == "class" else "function"
            qname = f"{scopes[-1][1]}.{name}"
            symbols.append(
                SymbolRecord(
                    kind=kind,
                    name=name,
                    qualified_name=qname,
                    start_line=_line(node),
                    end_line=node.end_point.row + 1,
                    content_hash=hash_content(source[node.start_byte : node.end_byte]),
                )
            )
            scopes.append((kind, qname))
            body = node.child_by_field_name("body")
            for child in (body.named_children if body is not None else []):
                visit(child)
            scopes.pop()

        def emit_mod(node: Node) -> None:
            body = node.child_by_field_name("body")
            if body is None:  # `mod foo;` — foo.rs supplies its own module
                return
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = _text(source, name_node)
            qname = f"{scopes[-1][1]}.{name}"
            symbols.append(
                SymbolRecord(
                    kind="module",
                    name=name,
                    qualified_name=qname,
                    start_line=_line(node),
                    end_line=node.end_point.row + 1,
                    content_hash=hash_content(source[node.start_byte : node.end_byte]),
                )
            )
            scopes.append(("module", qname))
            for child in body.named_children:
                visit(child)
            scopes.pop()

        def _ctor_type_node(fn_node: Node) -> Node | None:
            """The `Type` half of a `Type::ctor(...)` call target — dropping
            the trailing `::ctor` segment `resolve_path_ref` would otherwise
            include. A FieldAssignRecord needs the constructed *type*
            (Python/TS's own `self.field = Ctor()` has no such split — the
            callee already IS the class), so `Node::new()` must become
            `Node`, not `Node.new`."""
            if fn_node.type == "generic_function":
                fn_node = fn_node.child_by_field_name("function") or fn_node
            if fn_node.type == "scoped_identifier":
                return fn_node.child_by_field_name("path")
            return None

        def emit_struct_literal(node: Node) -> None:
            # `Self { field: Ctor::new() }` inside an impl block, for the
            # `self.field.method()` chain rule already in resolve.py.
            # Scoped to the `Self` literal deliberately — the analogue of
            # Python/TS's own `self.field = Ctor()`/`this.field = new Ctor()`
            # restriction, not any struct literal anywhere.
            cls = nearest("class")
            name_node = node.child_by_field_name("name")
            if cls is None or name_node is None or _text(source, name_node) != "Self":
                return
            body = node.child_by_field_name("body")
            if body is None:
                return
            for fi in body.named_children:
                if fi.type != "field_initializer" or not fi.named_children:
                    continue
                field_name_node = fi.named_children[0]
                value = fi.child_by_field_name("value")
                if value is None or value.type != "call_expression":
                    continue
                fn = value.child_by_field_name("function")
                type_node = _ctor_type_node(fn) if fn is not None else None
                ctor = resolve_path_ref(type_node) if type_node is not None else None
                if ctor is not None:
                    field_assigns.append(
                        FieldAssignRecord(
                            cls, _text(source, field_name_node), ctor, _line(fi)
                        )
                    )

        def visit(node: Node) -> None:
            if node.type == "use_declaration":
                return  # collected in the imports pass below
            if node.type in ("struct_item", "enum_item", "trait_item"):
                emit_item(node)
                return
            if node.type == "impl_item":
                emit_impl(node)
                return
            if node.type == "function_item":
                emit_fn(node)
                return
            if node.type == "mod_item":
                emit_mod(node)
                return
            if node.type == "struct_expression":
                emit_struct_literal(node)
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                if fn is not None:
                    callee = (
                        _field_chain(source, fn)
                        if fn.type == "field_expression"
                        else resolve_path_ref(fn)
                    )
                    if callee is not None:
                        refs.append(
                            RefRecord("call", scopes[-1][1], callee, _line(node))
                        )
            for child in node.named_children:
                visit(child)

        # imports need the same scope-aware self/super substitution as refs
        # (a nested `mod tests { use super::helper; }` is common — inline
        # cfg(test) modules), so they're collected in a scope-tracking walk
        # of their own, run before the main pass
        def collect_uses(node: Node) -> None:
            if node.type == "use_declaration":
                emit_use(node)
                return
            if node.type == "mod_item":
                body = node.child_by_field_name("body")
                name_node = node.child_by_field_name("name")
                if body is not None and name_node is not None:
                    nested = f"{scopes[-1][1]}.{_text(source, name_node)}"
                    scopes.append(("module", nested))
                    for child in body.named_children:
                        collect_uses(child)
                    scopes.pop()
                return
            for child in node.named_children:
                collect_uses(child)

        for child in root.named_children:
            collect_uses(child)
        scopes[:] = [("module", module_qname)]  # reset before the main pass

        for child in root.named_children:
            visit(child)

        return FileExtraction(
            path=path,
            language=self.language,
            module_qname=module_qname,
            symbols=symbols,
            imports=imports,
            refs=refs,
            field_assigns=field_assigns,
        )
