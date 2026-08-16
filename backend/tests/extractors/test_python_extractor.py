import ast
from pathlib import Path

import pytest

from codegraph.extractors import get_extractor_for
from codegraph.extractors.base import ImportRecord
from codegraph.extractors.python import PythonExtractor, module_qname_for_path

FIXTURES = Path(__file__).parent / "fixtures" / "py_sample"
EXTRACTORS_SRC = (
    Path(__file__).parents[2] / "src" / "codegraph" / "extractors"
)


def extract(rel: str):
    return PythonExtractor().extract(rel, (FIXTURES / rel).read_bytes())


@pytest.mark.parametrize(
    ("path", "qname"),
    [
        ("pkg/orders.py", "pkg.orders"),
        ("pkg/__init__.py", "pkg"),
        ("main.py", "main"),
        ("pkg/sub/mod.py", "pkg.sub.mod"),
    ],
)
def test_module_qname_derivation(path, qname):
    assert module_qname_for_path(path) == qname


def test_models_symbols_exact():
    result = extract("pkg/models.py")
    expected = [
        ("module", "models", "pkg.models", 1, 12),
        ("class", "Base", "pkg.models.Base", 1, 3),
        ("method", "save", "pkg.models.Base.save", 2, 3),
        ("class", "Node", "pkg.models.Node", 6, 8),
        ("method", "validate", "pkg.models.Node.validate", 7, 8),
        ("function", "render", "pkg.models.render", 11, 12),
    ]
    got = [
        (s.kind, s.name, s.qualified_name, s.start_line, s.end_line)
        for s in result.symbols
    ]
    assert got == expected


def test_decorated_def_span_includes_decorator():
    result = extract("pkg/util.py")
    cached = next(
        s for s in result.symbols if s.qualified_name == "pkg.util.cached_helper"
    )
    assert (cached.start_line, cached.end_line) == (8, 10)


def test_method_vs_function_kind():
    models = {s.qualified_name: s for s in extract("pkg/models.py").symbols}
    util = {s.qualified_name: s for s in extract("pkg/util.py").symbols}
    assert models["pkg.models.Base.save"].kind == "method"
    assert util["pkg.util.helper"].kind == "function"


def test_import_forms():
    cli = extract("pkg/cli.py")
    assert cli.imports == [
        ImportRecord("Svc", "pkg.services.OrderService", 1),
        ImportRecord("u", "pkg.util", 3),
    ]
    services = extract("pkg/services.py")
    assert services.imports == [
        ImportRecord("requests", "requests", 1),
        ImportRecord("Node", "pkg.models.Node", 3),
    ]


def test_star_import_record():
    result = PythonExtractor().extract("x.py", b"from pkg.util import *\n")
    assert result.imports == [ImportRecord("*", "pkg.util", 1)]


def test_relative_import_from_package_init():
    result = PythonExtractor().extract(
        "pkg/sub/__init__.py", b"from ..models import Node\n"
    )
    assert result.imports == [ImportRecord("Node", "pkg.models.Node", 1)]


def test_call_refs_and_enclosing_scope():
    services = extract("pkg/services.py")
    calls = {(r.target_expr, r.line): r for r in services.refs if r.kind == "call"}
    assert calls[("render", 17)].src_qualified_name == "pkg.services.OrderService.save"
    assert calls[("Node", 8)].src_qualified_name == "pkg.services.OrderService.__init__"

    cli = extract("pkg/cli.py")
    helper_call = next(r for r in cli.refs if r.kind == "call" and r.line == 9)
    assert helper_call.target_expr == "u.helper"
    assert helper_call.src_qualified_name == "pkg.cli.main"
    module_level = next(r for r in cli.refs if r.line == 12)
    assert module_level.src_qualified_name == "pkg.cli"


def test_inherits_ref():
    result = extract("pkg/models.py")
    inherits = [r for r in result.refs if r.kind == "inherits"]
    assert len(inherits) == 1
    ref = inherits[0]
    assert (ref.src_qualified_name, ref.target_expr, ref.line) == (
        "pkg.models.Node",
        "Base",
        6,
    )


def test_attr_ref_conservative():
    cli = extract("pkg/cli.py")
    attr_refs = [r for r in cli.refs if r.kind == "attr_ref"]
    assert [(r.target_expr, r.line) for r in attr_refs] == [("u.helper", 12)]

    services = extract("pkg/services.py")
    # self.repo is not on an imported name; u.helper(2)-style calls are calls
    assert [r for r in services.refs if r.kind == "attr_ref"] == []


def test_syntax_error_file_extracts():
    result = extract("pkg/broken.py")
    qnames = {s.qualified_name for s in result.symbols}
    assert "pkg.broken.good" in qnames
    assert "pkg.broken" in qnames


def test_content_hash_stable_and_sensitive():
    source = (FIXTURES / "pkg/util.py").read_bytes()
    first = PythonExtractor().extract("pkg/util.py", source)
    second = PythonExtractor().extract("pkg/util.py", source)
    assert [s.content_hash for s in first.symbols] == [
        s.content_hash for s in second.symbols
    ]

    mutated = PythonExtractor().extract(
        "pkg/util.py", source.replace(b"x * 2", b"x * 3")
    )
    by_qname = {s.qualified_name: s for s in first.symbols}
    mutated_by_qname = {s.qualified_name: s for s in mutated.symbols}
    assert (
        mutated_by_qname["pkg.util.helper"].content_hash
        != by_qname["pkg.util.helper"].content_hash
    )
    assert (
        mutated_by_qname["pkg.util.render"].content_hash
        == by_qname["pkg.util.render"].content_hash
    )


def test_registry():
    extractor = get_extractor_for("a/b.py")
    assert extractor is not None and extractor.language == "python"
    assert get_extractor_for("a/b.rs") is None


def test_no_db_imports():
    forbidden = ("sqlalchemy", "codegraph.db", "codegraph.models")
    for module_file in EXTRACTORS_SRC.glob("*.py"):
        tree = ast.parse(module_file.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not any(
                    name == f or name.startswith(f + ".") for f in forbidden
                ), f"{module_file.name} imports {name}"
