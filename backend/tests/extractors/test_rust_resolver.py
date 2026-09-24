"""Cross-file resolution for the Rust extractor (mirrors test_resolver.py)."""

from pathlib import Path

import pytest

from cartograph.extractors.resolve import resolve
from cartograph.extractors.rust import RustExtractor
from cartograph.extractors.rust_context import discover_rust_context

FIXTURES = Path(__file__).parent / "fixtures" / "rs_sample"
CONTEXT = discover_rust_context(FIXTURES)

CLEAN_FILES = (
    "src/lib.rs",
    "src/main.rs",
    "src/models.rs",
    "src/util.rs",
    "src/services.rs",
    "src/psn/mod.rs",
    "src/psn/decode.rs",
)


@pytest.fixture(scope="module")
def edges():
    extractor = RustExtractor()
    extractions = [
        extractor.extract(rel, (FIXTURES / rel).read_bytes(), CONTEXT)
        for rel in CLEAN_FILES
    ]
    return resolve(extractions)


def find(edges, *, src=None, dst=None, rel=None, confidence=None):
    return [
        e
        for e in edges
        if (src is None or e.src_qname == src)
        and (dst is None or e.dst_qname == dst)
        and (rel is None or e.rel == rel)
        and (confidence is None or e.confidence == confidence)
    ]


def test_use_import_resolved(edges):
    hits = find(
        edges,
        src="sample_lib.services",
        dst="sample_lib.models.Node",
        rel="imports",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_external_import_dropped(edges):
    assert not [e for e in edges if "std.collections" in e.dst_qname]


def test_bin_calls_lib_across_crate_roots(edges):
    hits = find(
        edges, src="sample.main.main", dst="sample_lib.run", rel="calls"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_crate_relative_call_resolved(edges):
    hits = find(
        edges,
        src="sample_lib.services.OrderService.save",
        dst="sample_lib.util.render",
        rel="calls",
        confidence="resolved",
    )
    assert len(hits) == 1


def test_self_field_chain_resolved():
    # self.repo.validate() via `Self { repo: Node::new() }` in OrderService::new
    services = RustExtractor().extract(
        "src/services.rs", (FIXTURES / "src/services.rs").read_bytes(), CONTEXT
    )
    models = RustExtractor().extract(
        "src/models.rs", (FIXTURES / "src/models.rs").read_bytes(), CONTEXT
    )
    edges = resolve([services, models])
    hits = find(
        edges,
        src="sample_lib.services.OrderService.save",
        dst="sample_lib.models.Node.validate",
        rel="calls",
        confidence="resolved",
    )
    assert len(hits) == 1


def test_self_method_call_resolved(edges):
    hits = find(
        edges,
        src="sample_lib.services.OrderService.save",
        dst="sample_lib.services.OrderService.check",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_sibling_submodule_call_resolved(edges):
    hits = find(
        edges,
        src="sample_lib.psn.describe",
        dst="sample_lib.psn.decode.name",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_trait_impl_inherits_resolved(edges):
    hits = find(
        edges, src="sample_lib.models.Node", dst="sample_lib.models.Greet", rel="inherits"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_instance_call_bare_name_match(edges):
    # n.validate() — n is a local Node instance, not `self`; only resolvable
    # (weakly) via bare-name fallback, same as Python's `n.validate()`
    hits = find(
        edges,
        src="sample_lib.services.OrderService.save",
        dst="sample_lib.models.Node.validate",
        rel="calls",
        confidence="name_match",
    )
    assert len(hits) == 1


def test_nested_test_module_super_resolved():
    util = RustExtractor().extract(
        "src/util.rs", (FIXTURES / "src/util.rs").read_bytes(), CONTEXT
    )
    edges = resolve([util])
    helper_hit = find(
        edges,
        src="sample_lib.util.tests.test_helper",
        dst="sample_lib.util.helper",
        rel="calls",
    )
    assert len(helper_hit) == 1 and helper_hit[0].confidence == "resolved"
    render_hit = find(
        edges,
        src="sample_lib.util.tests.test_helper",
        dst="sample_lib.util.render",
        rel="calls",
    )
    assert len(render_hit) == 1 and render_hit[0].confidence == "resolved"
    # NOTE: resolve.py's import-edge loop attributes every `imports` edge to
    # the *file-level* module_qname regardless of which nested module scope
    # the `use` actually appeared in (Python/TS have no nested import scope,
    # so this was never a precision loss for them) — a known, documented
    # limitation for Rust's inline `mod { use ...; }`, not something fixed
    # here since it's shared, non-Rust-specific code.
    use_hit = find(
        edges,
        src="sample_lib.util",
        dst="sample_lib.util.helper",
        rel="imports",
    )
    assert len(use_hit) == 1 and use_hit[0].confidence == "resolved"
