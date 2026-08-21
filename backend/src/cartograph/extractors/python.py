"""Tier-1 Python extractor built on tree-sitter (slice 03)."""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from .base import (
    FieldAssignRecord,
    FileExtraction,
    ImportRecord,
    RefRecord,
    SymbolRecord,
    hash_content,
)

_PY_LANGUAGE = Language(tspython.language())


def module_qname_for_path(path: str) -> str:
    parts = list(path.split("/"))
    parts[-1] = parts[-1].removesuffix(".py")
    if parts[-1] == "__init__" and len(parts) >= 2:
        parts.pop()
    return ".".join(parts)


def _text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line(node: Node) -> int:
    return node.start_point.row + 1


def _dotted_text(source: bytes, node: Node) -> str | None:
    """Flatten an identifier/attribute chain to dotted text; None for anything else."""
    if node.type == "identifier":
        return _text(source, node)
    if node.type == "attribute":
        obj = node.child_by_field_name("object")
        attr = node.child_by_field_name("attribute")
        if obj is None or attr is None:
            return None
        left = _dotted_text(source, obj)
        if left is None:
            return None
        return f"{left}.{_text(source, attr)}"
    return None


def _collect_imports(
    source: bytes, root: Node, module_qname: str, is_package: bool
) -> list[ImportRecord]:
    records: list[ImportRecord] = []

    def relative_base(dots: int) -> list[str]:
        parts = module_qname.split(".")
        if not is_package:
            parts = parts[:-1]
        drop = dots - 1
        return parts[: len(parts) - drop] if drop else parts

    def visit(node: Node) -> None:
        if node.type == "import_statement":
            line = _line(node)
            for child in node.named_children:
                if child.type == "dotted_name":
                    target = _text(source, child)
                    records.append(ImportRecord(target.split(".")[0], target, line))
                elif child.type == "aliased_import":
                    name = child.child_by_field_name("name")
                    alias = child.child_by_field_name("alias")
                    if name is not None and alias is not None:
                        records.append(
                            ImportRecord(_text(source, alias), _text(source, name), line)
                        )
            return
        if node.type == "import_from_statement":
            line = _line(node)
            module_node = node.child_by_field_name("module_name")
            if module_node is None:
                return
            if module_node.type == "relative_import":
                prefix = next(
                    (c for c in module_node.named_children if c.type == "import_prefix"),
                    None,
                )
                dotted = next(
                    (c for c in module_node.named_children if c.type == "dotted_name"),
                    None,
                )
                dots = len(_text(source, prefix)) if prefix is not None else 1
                base = relative_base(dots)
                if dotted is not None:
                    base = base + _text(source, dotted).split(".")
                module = ".".join(base)
            else:
                module = _text(source, module_node)
            for child in node.named_children:
                if child == module_node:
                    continue
                if child.type == "dotted_name":
                    name = _text(source, child)
                    records.append(
                        ImportRecord(name.split(".")[-1], f"{module}.{name}", line)
                    )
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias = child.child_by_field_name("alias")
                    if name_node is not None and alias is not None:
                        records.append(
                            ImportRecord(
                                _text(source, alias),
                                f"{module}.{_text(source, name_node)}",
                                line,
                            )
                        )
                elif child.type == "wildcard_import":
                    records.append(ImportRecord("*", module, line))
            return
        for child in node.named_children:
            visit(child)

    visit(root)
    return records


class PythonExtractor:
    language = "python"
    extensions = (".py",)

    def extract(
        self, path: str, source: bytes, context: object | None = None
    ) -> FileExtraction:
        # context is repo-resolution data for other languages; Python needs none
        module_qname = module_qname_for_path(path)
        is_package = path.split("/")[-1] == "__init__.py"
        parser = Parser(_PY_LANGUAGE)
        tree = parser.parse(source)
        root = tree.root_node

        imports = _collect_imports(source, root, module_qname, is_package)
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

        def emit_definition(node: Node) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:  # fragmentary node inside an ERROR region
                return
            name = _text(source, name_node)
            qname = f"{scopes[-1][1]}.{name}"
            if node.type == "class_definition":
                kind = "class"
            else:
                kind = "method" if scopes[-1][0] == "class" else "function"
            # span includes decorators
            span = (
                node.parent
                if node.parent is not None and node.parent.type == "decorated_definition"
                else node
            )
            symbols.append(
                SymbolRecord(
                    kind=kind,
                    name=name,
                    qualified_name=qname,
                    start_line=_line(span),
                    end_line=span.end_point.row + 1,
                    content_hash=hash_content(source[span.start_byte : span.end_byte]),
                )
            )
            if node.type == "class_definition":
                superclasses = node.child_by_field_name("superclasses")
                if superclasses is not None:
                    for base in superclasses.named_children:
                        base_text = _dotted_text(source, base)
                        if base_text is not None:
                            refs.append(
                                RefRecord("inherits", qname, base_text, _line(base))
                            )
            scopes.append((kind, qname))
            # recurse only into the body: superclasses were already emitted as
            # inherits refs above, and re-visiting them would double-count
            # dotted bases as attr_refs
            body = node.child_by_field_name("body")
            for child in (body.named_children if body is not None else node.named_children):
                visit(child)
            scopes.pop()

        def visit(node: Node) -> None:
            if node.type in ("class_definition", "function_definition"):
                emit_definition(node)
                return
            if node.type == "assignment":
                # self.field = Collaborator(...), for this/self field typing
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if (
                    left is not None
                    and right is not None
                    and left.type == "attribute"
                    and right.type == "call"
                ):
                    obj = left.child_by_field_name("object")
                    attr = left.child_by_field_name("attribute")
                    fn = right.child_by_field_name("function")
                    cls = next(
                        (q for k, q in reversed(scopes) if k == "class"), None
                    )
                    if (
                        obj is not None
                        and attr is not None
                        and fn is not None
                        and cls is not None
                        and obj.type == "identifier"
                        and _text(source, obj) == "self"
                    ):
                        ctor = _dotted_text(source, fn)
                        if ctor is not None:
                            field_assigns.append(
                                FieldAssignRecord(
                                    cls, _text(source, attr), ctor, _line(node)
                                )
                            )
            if node.type == "call":
                fn = node.child_by_field_name("function")
                if fn is not None:
                    callee = _dotted_text(source, fn)
                    if callee is not None:
                        refs.append(RefRecord("call", scopes[-1][1], callee, _line(node)))
            elif node.type == "attribute":
                parent = node.parent
                is_callee = (
                    parent is not None
                    and parent.type == "call"
                    and parent.child_by_field_name("function") == node
                )
                is_topmost = parent is None or parent.type != "attribute"
                if not is_callee and is_topmost:
                    expr = _dotted_text(source, node)
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
            language=self.language,
            module_qname=module_qname,
            symbols=symbols,
            imports=imports,
            refs=refs,
            field_assigns=field_assigns,
        )
