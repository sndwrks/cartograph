"""Tier-1 TypeScript/JavaScript extractor built on tree-sitter (slice 04).

One extractor covers .ts/.tsx/.mts/.cts/.js/.jsx/.mjs/.cjs; the grammar is
picked per extension. Repo-specific resolution (tsconfig path aliases,
workspace packages, Meteor-style root-absolute imports) comes from the
TsResolutionContext the ingest loader discovers per run and passes to
extract(); without one, only relative specifiers resolve.
"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
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
    from .ts_context import TsResolutionContext

_LANGUAGES = {
    ".ts": Language(tstypescript.language_typescript()),
    ".tsx": Language(tstypescript.language_tsx()),
    ".mts": Language(tstypescript.language_typescript()),
    ".cts": Language(tstypescript.language_typescript()),
    ".js": Language(tsjavascript.language()),
    ".jsx": Language(tsjavascript.language()),
    ".mjs": Language(tsjavascript.language()),
    ".cjs": Language(tsjavascript.language()),
}
_EXTENSIONS = tuple(_LANGUAGES)
_JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs")

_FN_TYPES = ("arrow_function", "function_expression", "function")
_DOTTED_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


def module_qname_for_path(path: str) -> str:
    parts = path.split("/")
    for ext in _EXTENSIONS:
        if parts[-1].endswith(ext):
            parts[-1] = parts[-1].removesuffix(ext)
            break
    if parts[-1] == "index" and len(parts) >= 2:
        parts.pop()
    return ".".join(parts)


def _qname_from_repo_path(path: str) -> str:
    return module_qname_for_path(path)


def _text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line(node: Node) -> int:
    return node.start_point.row + 1


def _string_value(source: bytes, node: Node) -> str:
    fragment = next(
        (c for c in node.named_children if c.type == "string_fragment"), None
    )
    return _text(source, fragment) if fragment is not None else _text(source, node).strip("\"'`")


def _dotted(source: bytes, node: Node) -> str | None:
    """Node text if it is a plain dotted identifier chain, else None."""
    text = _text(source, node)
    return text if _DOTTED_RE.match(text) else None


def _this_binds_to_class(node: Node) -> bool:
    """True when `this` at this node is the class instance: reached from the
    class body without crossing a plain function expression (whose `this` is
    rebound by the caller). Arrow functions keep the lexical `this`."""
    parent = node.parent
    while parent is not None:
        if parent.type in ("function_expression", "function_declaration", "function"):
            return False
        if parent.type in ("method_definition", "class_body"):
            return True
        parent = parent.parent
    return True


class TypeScriptExtractor:
    language = "typescript"
    extensions = _EXTENSIONS

    def _resolve_specifier(
        self,
        spec: str,
        importing_path: str,
        context: TsResolutionContext | None = None,
    ) -> str:
        if spec.startswith("."):
            joined = posixpath.normpath(
                posixpath.join(posixpath.dirname(importing_path), spec)
            )
            return _qname_from_repo_path(joined)
        if context is not None:
            importing_dir = posixpath.dirname(importing_path)
            if spec.startswith("/"):
                # Meteor-style root-absolute import, relative to the app root
                joined = posixpath.normpath(
                    posixpath.join(
                        context.nearest_package_dir(importing_dir),
                        spec.lstrip("/"),
                    )
                )
                # ".." segments escaping the repo namespace are not a real
                # module; treat like an external specifier (dropped downstream)
                if joined == ".." or joined.startswith("../"):
                    return spec.replace("/", ".")
                return _qname_from_repo_path(joined)
            mapped = context.resolve_alias(spec, importing_dir)
            if mapped is None:
                mapped = context.resolve_workspace(spec)
            if mapped is not None:
                return _qname_from_repo_path(posixpath.normpath(mapped))
        # external ("react", "lodash/fp"): the resolver drops what it can't find
        return spec.replace("/", ".")

    def _collect_imports(
        self,
        source: bytes,
        root: Node,
        path: str,
        context: TsResolutionContext | None = None,
    ) -> list[ImportRecord]:
        records: list[ImportRecord] = []

        def module_for(node: Node) -> str | None:
            src_node = node.child_by_field_name("source")
            if src_node is None:
                return None
            return self._resolve_specifier(
                _string_value(source, src_node), path, context
            )

        def visit(node: Node) -> None:
            if node.type == "import_statement":
                module = module_for(node)
                if module is None:
                    return
                line = _line(node)
                clause = next(
                    (c for c in node.named_children if c.type == "import_clause"), None
                )
                if clause is None:
                    return  # side-effect import
                for child in clause.named_children:
                    if child.type == "identifier":
                        records.append(
                            ImportRecord(_text(source, child), f"{module}.default", line)
                        )
                    elif child.type == "named_imports":
                        for spec in child.named_children:
                            if spec.type != "import_specifier":
                                continue
                            name = spec.child_by_field_name("name")
                            alias = spec.child_by_field_name("alias")
                            if name is None:
                                continue
                            local = _text(source, alias if alias is not None else name)
                            records.append(
                                ImportRecord(local, f"{module}.{_text(source, name)}", line)
                            )
                    elif child.type == "namespace_import":
                        ident = next(
                            (c for c in child.named_children if c.type == "identifier"),
                            None,
                        )
                        if ident is not None:
                            records.append(
                                ImportRecord(_text(source, ident), module, line)
                            )
                return
            if node.type == "export_statement":
                module = module_for(node)
                if module is not None:  # re-export
                    line = _line(node)
                    clause = next(
                        (c for c in node.named_children if c.type == "export_clause"),
                        None,
                    )
                    if clause is None:
                        # export * from "./mod" (optionally * as ns)
                        ns = next(
                            (
                                c
                                for c in node.named_children
                                if c.type == "namespace_export"
                            ),
                            None,
                        )
                        if ns is not None:
                            ident = next(
                                (c for c in ns.named_children if c.type == "identifier"),
                                None,
                            )
                            if ident is not None:
                                records.append(
                                    ImportRecord(_text(source, ident), module, line)
                                )
                        else:
                            records.append(ImportRecord("*", module, line))
                    else:
                        for spec in clause.named_children:
                            if spec.type != "export_specifier":
                                continue
                            name = spec.child_by_field_name("name")
                            alias = spec.child_by_field_name("alias")
                            if name is None:
                                continue
                            local = _text(source, alias if alias is not None else name)
                            records.append(
                                ImportRecord(local, f"{module}.{_text(source, name)}", line)
                            )
                    return
            if node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                name = node.child_by_field_name("name")
                if (
                    value is not None
                    and name is not None
                    and name.type in ("identifier", "object_pattern")
                    and value.type == "call_expression"
                ):
                    fn = value.child_by_field_name("function")
                    args = value.child_by_field_name("arguments")
                    if (
                        fn is not None
                        and _text(source, fn) == "require"
                        and args is not None
                        and args.named_children
                        and args.named_children[0].type == "string"
                    ):
                        spec = _string_value(source, args.named_children[0])
                        module = self._resolve_specifier(spec, path, context)
                        line = _line(node)
                        if name.type == "identifier":
                            records.append(
                                ImportRecord(_text(source, name), module, line)
                            )
                        else:
                            # const { app, dialog: d } = require("electron")
                            for prop in name.named_children:
                                if prop.type == "shorthand_property_identifier_pattern":
                                    prop_name = _text(source, prop)
                                    records.append(
                                        ImportRecord(
                                            prop_name, f"{module}.{prop_name}", line
                                        )
                                    )
                                elif prop.type == "pair_pattern":
                                    key = prop.child_by_field_name("key")
                                    val = prop.child_by_field_name("value")
                                    if (
                                        key is not None
                                        and val is not None
                                        and val.type == "identifier"
                                    ):
                                        records.append(
                                            ImportRecord(
                                                _text(source, val),
                                                f"{module}.{_text(source, key)}",
                                                line,
                                            )
                                        )
            for child in node.named_children:
                visit(child)

        visit(root)
        return records

    def extract(
        self,
        path: str,
        source: bytes,
        context: TsResolutionContext | None = None,
    ) -> FileExtraction:
        module_qname = module_qname_for_path(path)
        ext = "." + path.rsplit(".", 1)[-1]
        parser = Parser(_LANGUAGES.get(ext, _LANGUAGES[".ts"]))
        root = parser.parse(source).root_node

        imports = self._collect_imports(source, root, path, context)
        imported_locals = {rec.local_name for rec in imports if rec.local_name != "*"}

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
        refs: list[RefRecord] = []
        field_assigns: list[FieldAssignRecord] = []
        scopes: list[tuple[str, str]] = [("module", module_qname)]

        def span_for(node: Node) -> Node:
            # spans include the `export` wrapper, like Python decorator spans
            outer = node
            while outer.parent is not None and outer.parent.type == "export_statement":
                outer = outer.parent
            if outer.parent is not None and outer.parent.type in (
                "lexical_declaration",
                "variable_declaration",
            ):
                outer = outer.parent
                if outer.parent is not None and outer.parent.type == "export_statement":
                    outer = outer.parent
            return outer

        used: set[tuple[str, str]] = {(module_qname, "module")}

        def emit_symbol(kind: str, name: str, anchor: Node) -> str:
            qname = f"{scopes[-1][1]}.{name}"
            span = span_for(anchor)
            start_line = _line(span)
            if (qname, kind) in used:
                # Sibling anonymous scopes can legitimately define the same
                # name — four useEffect callbacks each declaring
                # handleCreateSuccess — and nothing but position tells them
                # apart. Suffixing keeps them distinct (the DB has a unique
                # constraint on (repository_id, qualified_name, kind)) and
                # traceable. The first occurrence keeps the clean name.
                qname = f"{qname}@L{start_line}"
            used.add((qname, kind))
            symbols.append(
                SymbolRecord(
                    kind=kind,
                    name=name,
                    qualified_name=qname,
                    start_line=start_line,
                    end_line=span.end_point.row + 1,
                    content_hash=hash_content(source[span.start_byte : span.end_byte]),
                )
            )
            return qname

        def emit_heritage(class_node: Node, qname: str) -> None:
            heritage = next(
                (c for c in class_node.named_children if c.type == "class_heritage"),
                None,
            )
            if heritage is None:
                return
            clauses = [
                c
                for c in heritage.named_children
                if c.type in ("extends_clause", "implements_clause")
            ]
            # the javascript grammar puts the extends expression directly
            # under class_heritage with no clause node
            targets = (
                [t for clause in clauses for t in clause.named_children]
                if clauses
                else list(heritage.named_children)
            )
            for target in targets:
                text = _dotted(source, target)
                if text is not None:
                    refs.append(RefRecord("inherits", qname, text, _line(target)))

        def visit_class(node: Node) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            qname = emit_symbol("class", _text(source, name_node), node)
            emit_heritage(node, qname)
            scopes.append(("class", qname))
            body = node.child_by_field_name("body")
            for child in (body.named_children if body is not None else []):
                visit(child)
            scopes.pop()

        def visit_fn_scope(kind: str, name: str, anchor: Node, body_owner: Node) -> None:
            qname = emit_symbol(kind, name, anchor)
            scopes.append((kind, qname))
            for child in body_owner.named_children:
                visit(child)
            scopes.pop()

        def visit(node: Node) -> None:
            if node.type == "import_statement":
                return
            if node.type == "export_statement":
                if node.child_by_field_name("source") is not None:
                    return  # re-export, handled in the import pass
                target = node.child_by_field_name("declaration")
                if target is None:
                    target = node.child_by_field_name("value")
                if target is None:
                    target = next(
                        (
                            c
                            for c in node.named_children
                            if c.type not in ("export_clause", "string", "comment")
                        ),
                        None,
                    )
                if target is None:
                    return  # export { A }; of locals — no new symbols
                is_default = any(c.type == "default" for c in node.children)
                is_anonymous = target.child_by_field_name("name") is None
                if is_default and is_anonymous:
                    if target.type in _FN_TYPES:
                        visit_fn_scope("function", "default", target, target)
                        return
                    if target.type in ("class", "class_declaration"):
                        qname = emit_symbol("class", "default", target)
                        emit_heritage(target, qname)
                        scopes.append(("class", qname))
                        body = target.child_by_field_name("body")
                        for child in (body.named_children if body is not None else []):
                            visit(child)
                        scopes.pop()
                        return
                visit(target)
                return
            if node.type == "class_declaration":
                visit_class(node)
                return
            if node.type in ("interface_declaration", "type_alias_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    # no dedicated kind in the schema; they matter as
                    # inheritance/implementation targets
                    emit_symbol("class", _text(source, name_node), node)
                return
            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    kind = "method" if scopes[-1][0] == "class" else "function"
                    visit_fn_scope(kind, _text(source, name_node), node, node)
                return
            if node.type == "method_definition":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    visit_fn_scope("method", _text(source, name_node), node, node)
                return
            if (
                node.type in ("lexical_declaration", "variable_declaration")
                and scopes[-1][0] == "module"
            ):
                for declarator in node.named_children:
                    if declarator.type != "variable_declarator":
                        continue
                    name_node = declarator.child_by_field_name("name")
                    value = declarator.child_by_field_name("value")
                    if (
                        name_node is not None
                        and name_node.type == "identifier"
                        and value is not None
                        and value.type in _FN_TYPES
                    ):
                        visit_fn_scope(
                            "function", _text(source, name_node), declarator, value
                        )
                    elif (
                        name_node is not None
                        and name_node.type == "identifier"
                        and value is not None
                        and value.type == "object"
                    ):
                        # An object literal's methods belong to the binding, not
                        # the module: three sibling codec objects each defining
                        # encode/decode would otherwise all become
                        # <module>.encode and collide on (qualified_name, kind).
                        # The binding itself emits no symbol — it only namespaces.
                        scopes.append(
                            ("object", f"{scopes[-1][1]}.{_text(source, name_node)}")
                        )
                        for child in value.named_children:
                            visit(child)
                        scopes.pop()
                    else:
                        visit(declarator)
                return
            if node.type == "assignment_expression":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if (
                    left is not None
                    and right is not None
                    and left.type == "member_expression"
                    and right.type == "new_expression"
                ):
                    obj = left.child_by_field_name("object")
                    prop = left.child_by_field_name("property")
                    ctor = right.child_by_field_name("constructor")
                    cls = next(
                        (q for k, q in reversed(scopes) if k == "class"), None
                    )
                    if (
                        obj is not None
                        and prop is not None
                        and ctor is not None
                        and cls is not None
                        and _text(source, obj) == "this"
                        and _this_binds_to_class(node)
                    ):
                        ctor_text = _dotted(source, ctor)
                        if ctor_text is not None:
                            field_assigns.append(
                                FieldAssignRecord(
                                    cls,
                                    _text(source, prop),
                                    ctor_text,
                                    _line(node),
                                )
                            )
            elif (
                node.type in ("public_field_definition", "field_definition")
                and scopes[-1][0] == "class"
            ):
                # class property initializer: `svc = new OrderService()`
                prop = node.child_by_field_name("name")
                value = node.child_by_field_name("value")
                if (
                    prop is not None
                    and value is not None
                    and value.type == "new_expression"
                ):
                    ctor = value.child_by_field_name("constructor")
                    ctor_text = (
                        _dotted(source, ctor) if ctor is not None else None
                    )
                    if ctor_text is not None:
                        field_assigns.append(
                            FieldAssignRecord(
                                scopes[-1][1],
                                _text(source, prop),
                                ctor_text,
                                _line(node),
                            )
                        )
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                if fn is not None:
                    callee = _dotted(source, fn)
                    if callee is not None:
                        refs.append(RefRecord("call", scopes[-1][1], callee, _line(node)))
            elif node.type == "new_expression":
                ctor = node.child_by_field_name("constructor")
                if ctor is not None:
                    callee = _dotted(source, ctor)
                    if callee is not None:
                        refs.append(RefRecord("call", scopes[-1][1], callee, _line(node)))
            elif node.type in ("jsx_opening_element", "jsx_self_closing_element"):
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    tag = _dotted(source, name_node)
                    if tag is not None and (tag[0].isupper() or "." in tag):
                        refs.append(RefRecord("call", scopes[-1][1], tag, _line(node)))
            elif node.type == "member_expression":
                parent = node.parent
                is_callee = parent is not None and (
                    (
                        parent.type == "call_expression"
                        and parent.child_by_field_name("function") == node
                    )
                    or (
                        parent.type == "new_expression"
                        and parent.child_by_field_name("constructor") == node
                    )
                    or parent.type
                    in ("jsx_opening_element", "jsx_self_closing_element")
                )
                is_topmost = parent is None or parent.type != "member_expression"
                if not is_callee and is_topmost:
                    expr = _dotted(source, node)
                    if expr is not None and expr.split(".")[0] in imported_locals:
                        refs.append(
                            RefRecord("attr_ref", scopes[-1][1], expr, _line(node))
                        )
            for child in node.named_children:
                visit(child)

        for child in root.named_children:
            visit(child)

        return FileExtraction(
            path=path,
            language="javascript" if ext in _JS_EXTENSIONS else "typescript",
            module_qname=module_qname,
            symbols=symbols,
            imports=imports,
            refs=refs,
            field_assigns=field_assigns,
        )
