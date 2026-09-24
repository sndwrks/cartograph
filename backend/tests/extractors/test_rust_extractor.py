from pathlib import Path

import pytest

from cartograph.extractors import get_extractor_for
from cartograph.extractors.base import ImportRecord
from cartograph.extractors.rust import RustExtractor, module_qname_for_path
from cartograph.extractors.rust_context import discover_rust_context

FIXTURES = Path(__file__).parent / "fixtures" / "rs_sample"
CONTEXT = discover_rust_context(FIXTURES)


def extract(rel: str, context=CONTEXT):
    return RustExtractor().extract(rel, (FIXTURES / rel).read_bytes(), context)


@pytest.mark.parametrize(
    ("path", "qname"),
    [
        # no context (or no crate found for this path): best-effort flat
        # dotted path, no lib/main/bin disambiguation
        ("pkg/foo.rs", "pkg.foo"),
        ("pkg/mod.rs", "pkg"),
        ("lib.rs", "crate"),
        ("main.rs", "crate"),
    ],
)
def test_module_qname_derivation_no_context(path, qname):
    assert module_qname_for_path(path) == qname


@pytest.mark.parametrize(
    ("path", "qname"),
    [
        ("src/lib.rs", "sample_lib"),
        ("src/main.rs", "sample.main"),
        ("src/models.rs", "sample_lib.models"),
        ("src/util.rs", "sample_lib.util"),
        ("src/psn/mod.rs", "sample_lib.psn"),
        ("src/psn/decode.rs", "sample_lib.psn.decode"),
    ],
)
def test_module_qname_with_context(path, qname):
    assert module_qname_for_path(path, CONTEXT) == qname


def test_models_symbols():
    result = extract("src/models.rs")
    kinds = {s.qualified_name: (s.kind, s.name) for s in result.symbols}
    assert kinds["sample_lib.models"] == ("module", "models")
    assert kinds["sample_lib.models.Greet"] == ("class", "Greet")
    assert kinds["sample_lib.models.Base"] == ("class", "Base")
    assert kinds["sample_lib.models.Base.save"] == ("method", "save")
    assert kinds["sample_lib.models.Node"] == ("class", "Node")
    assert kinds["sample_lib.models.Node.new"] == ("method", "new")
    assert kinds["sample_lib.models.Node.validate"] == ("method", "validate")
    assert kinds["sample_lib.models.Node.greet"] == ("method", "greet")
    assert kinds["sample_lib.models.render"] == ("function", "render")
    # trait bodies aren't recursed into — only the trait's own symbol exists
    assert "sample_lib.models.Greet.greet" not in kinds


def test_impl_for_trait_adds_inherits_ref():
    result = extract("src/models.rs")
    inherits = [r for r in result.refs if r.kind == "inherits"]
    assert len(inherits) == 1
    ref = inherits[0]
    assert ref.src_qualified_name == "sample_lib.models.Node"
    assert ref.target_expr == "Greet"


def test_self_call_in_impl():
    result = extract("src/models.rs")
    calls = {(r.src_qualified_name, r.target_expr) for r in result.refs if r.kind == "call"}
    assert ("sample_lib.models.Node.greet", "self.validate") in calls


def test_use_import_forms():
    services = extract("src/services.rs")
    assert ImportRecord("Node", "sample_lib.models.Node", 1) in services.imports
    assert ImportRecord("HashMap", "std.collections.HashMap", 2) in services.imports


def test_module_qname_for_main_and_lib_no_collision():
    lib = extract("src/lib.rs")
    main = extract("src/main.rs")
    assert lib.module_qname == "sample_lib"
    assert main.module_qname == "sample.main"


def test_bin_call_into_lib_by_external_crate_name():
    main = extract("src/main.rs")
    calls = [r for r in main.refs if r.kind == "call"]
    assert len(calls) == 1
    assert calls[0].target_expr == "sample_lib.run"


def test_nested_module_symbol_and_super_resolution():
    result = extract("src/util.rs")
    kinds = {s.qualified_name: s.kind for s in result.symbols}
    assert kinds["sample_lib.util.tests"] == "module"
    assert kinds["sample_lib.util.tests.test_helper"] == "function"
    assert ImportRecord("helper", "sample_lib.util.helper", 15) in result.imports
    calls = {(r.src_qualified_name, r.target_expr) for r in result.refs if r.kind == "call"}
    assert ("sample_lib.util.tests.test_helper", "sample_lib.util.render") in calls


def test_crate_relative_call_resolved_text():
    services = extract("src/services.rs")
    calls = {(r.src_qualified_name, r.target_expr) for r in services.refs if r.kind == "call"}
    assert ("sample_lib.services.OrderService.save", "sample_lib.util.render") in calls


def test_sibling_submodule_call_left_relative():
    psn = extract("src/psn/mod.rs")
    calls = [r for r in psn.refs if r.kind == "call"]
    assert ("sample_lib.psn.describe", "decode.name") in {
        (r.src_qualified_name, r.target_expr) for r in calls
    }


def test_field_assign_self_struct_literal():
    services = extract("src/services.rs")
    assert len(services.field_assigns) == 1
    fa = services.field_assigns[0]
    assert fa.class_qname == "sample_lib.services.OrderService"
    assert fa.field_name == "repo"
    assert fa.ctor_expr == "Node"


def test_syntax_error_file_extracts():
    result = extract("src/broken.rs")
    qnames = {s.qualified_name for s in result.symbols}
    assert "sample_lib.broken.good" in qnames
    assert "sample_lib.broken.Recovered" in qnames


def test_registry():
    extractor = get_extractor_for("a/b.rs")
    assert extractor is not None and extractor.language == "rust"
    assert extractor.language != "typescript"
