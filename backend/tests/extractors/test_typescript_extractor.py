from pathlib import Path

import pytest

from cartograph.extractors import get_extractor_for
from cartograph.extractors.base import ImportRecord
from cartograph.extractors.resolve import resolve
from cartograph.extractors.typescript import (
    TypeScriptExtractor,
    aliases_from_tsconfig,
    module_qname_for_path,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ts_sample"

FILES = (
    "src/models/order.ts",
    "src/services/orderService.ts",
    "src/util.ts",
    "src/index.ts",
    "src/components/Widget.tsx",
    "src/components/OrderTable.tsx",
    "src/components/App.tsx",
    "src/legacy.js",
)


def make_extractor():
    aliases = aliases_from_tsconfig((FIXTURES / "tsconfig.json").read_text())
    return TypeScriptExtractor(aliases=aliases)


def extract(rel: str):
    return make_extractor().extract(rel, (FIXTURES / rel).read_bytes())


@pytest.fixture(scope="module")
def edges():
    extractor = make_extractor()
    return resolve(
        [extractor.extract(rel, (FIXTURES / rel).read_bytes()) for rel in FILES]
    )


def find(edges, *, src=None, dst=None, rel=None, confidence=None):
    return [
        e
        for e in edges
        if (src is None or e.src_qname == src)
        and (dst is None or e.dst_qname == dst)
        and (rel is None or e.rel == rel)
        and (confidence is None or e.confidence == confidence)
    ]


@pytest.mark.parametrize(
    ("path", "qname"),
    [
        ("src/orders/service.ts", "src.orders.service"),
        ("src/orders/index.ts", "src.orders"),
        ("src/components/OrderTable.tsx", "src.components.OrderTable"),
        ("src/legacy.js", "src.legacy"),
    ],
)
def test_module_qname_derivation(path, qname):
    assert module_qname_for_path(path) == qname


def test_tsconfig_aliases():
    assert aliases_from_tsconfig((FIXTURES / "tsconfig.json").read_text()) == {
        "@/*": "src/*"
    }


def test_order_symbols_exact():
    result = extract("src/models/order.ts")
    expected = [
        ("module", "order", "src.models.order", 1, 17),
        ("class", "Orderable", "src.models.order.Orderable", 1, 3),
        ("class", "Order", "src.models.order.Order", 5, 11),
        ("method", "total", "src.models.order.Order.total", 8, 10),
        ("class", "SpecialOrder", "src.models.order.SpecialOrder", 13, 13),
        ("function", "render", "src.models.order.render", 15, 17),
    ]
    got = [
        (s.kind, s.name, s.qualified_name, s.start_line, s.end_line)
        for s in result.symbols
    ]
    assert got == expected


def test_arrow_function_symbols():
    util = {s.qualified_name: s for s in extract("src/util.ts").symbols}
    assert util["src.util.helper"].kind == "function"
    assert (util["src.util.helper"].start_line, util["src.util.helper"].end_line) == (1, 1)
    assert util["src.util.render"].kind == "function"


def test_default_export_symbol():
    widget = {s.qualified_name: s for s in extract("src/components/Widget.tsx").symbols}
    assert widget["src.components.Widget.default"].kind == "function"
    assert widget["src.components.Widget.default"].name == "default"


def test_import_forms():
    table = extract("src/components/OrderTable.tsx")
    assert table.imports == [
        ImportRecord("React", "react.default", 1),
        ImportRecord("svc", "src.services.orderService", 2),
        ImportRecord("Widget", "src.components.Widget.default", 3),
    ]
    service = extract("src/services/orderService.ts")
    assert service.imports == [ImportRecord("Order", "src.models.order.Order", 1)]


def test_reexport_barrel_imports():
    index = extract("src/index.ts")
    assert index.module_qname == "src"
    assert index.imports == [
        ImportRecord("Order", "src.models.order.Order", 1),
        ImportRecord("*", "src.util", 2),
    ]


def test_named_import_with_alias():
    result = make_extractor().extract(
        "src/x.ts", b'import { Order as O, render } from "./models/order";\n'
    )
    assert result.imports == [
        ImportRecord("O", "src.models.order.Order", 1),
        ImportRecord("render", "src.models.order.render", 1),
    ]


def test_commonjs_require():
    legacy = extract("src/legacy.js")
    assert legacy.language == "javascript"
    assert legacy.imports == [ImportRecord("util", "src.util", 1)]


def test_inherits_refs():
    refs = [r for r in extract("src/models/order.ts").refs if r.kind == "inherits"]
    got = {(r.src_qualified_name, r.target_expr) for r in refs}
    assert got == {
        ("src.models.order.Order", "Orderable"),
        ("src.models.order.SpecialOrder", "Order"),
    }


def test_jsx_component_ref():
    table = extract("src/components/OrderTable.tsx")
    jsx = [r for r in table.refs if r.target_expr == "Widget"]
    assert len(jsx) == 1
    assert jsx[0].kind == "call"
    assert jsx[0].src_qualified_name == "src.components.OrderTable.OrderTable"
    # lowercase intrinsic tags emit nothing
    assert not [r for r in table.refs if r.target_expr == "div"]


def test_syntax_error_file_extracts():
    result = extract("src/broken.ts")
    qnames = {s.qualified_name for s in result.symbols}
    assert "src.broken.good" in qnames


def test_registry_covers_all_extensions():
    for path in ("a.ts", "a.tsx", "a.js", "a.jsx"):
        extractor = get_extractor_for(path)
        assert extractor is not None and extractor.language == "typescript"


# --- resolver integration -------------------------------------------------


def test_named_import_cross_file_call_resolved(edges):
    hits = find(
        edges,
        src="src.services.orderService.OrderService.save",
        dst="src.models.order.Order",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_ambiguous_render_name_match(edges):
    hits = find(
        edges,
        src="src.services.orderService.OrderService.save",
        rel="calls",
        confidence="name_match",
    )
    assert {e.dst_qname for e in hits if e.dst_qname.endswith(".render")} == {
        "src.models.order.render",
        "src.util.render",
    }


def test_extends_and_implements_edges(edges):
    implements = find(
        edges,
        src="src.models.order.Order",
        dst="src.models.order.Orderable",
        rel="inherits",
    )
    extends = find(
        edges,
        src="src.models.order.SpecialOrder",
        dst="src.models.order.Order",
        rel="inherits",
    )
    assert len(implements) == 1 and implements[0].confidence == "resolved"
    assert len(extends) == 1 and extends[0].confidence == "resolved"


def test_default_import_resolves_to_module_default(edges):
    jsx = find(
        edges,
        src="src.components.OrderTable.OrderTable",
        dst="src.components.Widget.default",
        rel="calls",
    )
    assert len(jsx) == 1 and jsx[0].confidence == "resolved"
    imp = find(
        edges,
        src="src.components.OrderTable",
        dst="src.components.Widget.default",
        rel="imports",
    )
    assert len(imp) == 1 and imp[0].confidence == "resolved"


def test_namespace_member_new_resolved(edges):
    hits = find(
        edges,
        src="src.components.OrderTable.OrderTable",
        dst="src.services.orderService.OrderService",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_alias_import_edge_resolved(edges):
    hits = find(
        edges,
        src="src.components.OrderTable",
        dst="src.services.orderService",
        rel="imports",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_react_import_no_edge(edges):
    assert not [e for e in edges if e.dst_qname.split(".")[0] == "react"]


def test_jsx_ordertable_edge(edges):
    hits = find(
        edges,
        src="src.components.App.App",
        dst="src.components.OrderTable.OrderTable",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_commonjs_call_resolved(edges):
    hits = find(edges, src="src.legacy.main", dst="src.util.helper", rel="calls")
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_barrel_import_edges(edges):
    assert find(edges, src="src", dst="src.models.order.Order", rel="imports")
    assert find(edges, src="src", dst="src.util", rel="imports")
