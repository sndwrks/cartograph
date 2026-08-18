from pathlib import Path

import pytest

from cartograph.extractors.base import FileExtraction, RefRecord, SymbolRecord
from cartograph.extractors.python import PythonExtractor
from cartograph.extractors.resolve import resolve

FIXTURES = Path(__file__).parent / "fixtures" / "py_sample"

CLEAN_FILES = (
    "pkg/__init__.py",
    "pkg/models.py",
    "pkg/util.py",
    "pkg/services.py",
    "pkg/cli.py",
)


@pytest.fixture(scope="module")
def edges():
    extractor = PythonExtractor()
    extractions = [
        extractor.extract(rel, (FIXTURES / rel).read_bytes()) for rel in CLEAN_FILES
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


def test_import_edges_resolved(edges):
    expected = [
        ("pkg.services", "pkg.models.Node"),
        ("pkg.cli", "pkg.services.OrderService"),
        ("pkg.cli", "pkg.util"),
    ]
    for src, dst in expected:
        hits = find(edges, src=src, dst=dst, rel="imports")
        assert len(hits) == 1 and hits[0].confidence == "resolved", (src, dst)


def test_external_imports_dropped(edges):
    assert not [
        e for e in edges if e.dst_qname.split(".")[0] in ("requests", "functools")
    ]


def test_cross_file_call_resolved(edges):
    hits = find(
        edges,
        src="pkg.services.OrderService.save",
        dst="pkg.models.Node",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_aliased_and_relative_resolve(edges):
    svc = find(
        edges, src="pkg.cli.main", dst="pkg.services.OrderService", rel="calls"
    )
    assert len(svc) == 1 and svc[0].confidence == "resolved"
    helper = find(edges, src="pkg.cli.main", dst="pkg.util.helper", rel="calls")
    assert len(helper) == 1 and helper[0].confidence == "resolved"


def test_self_call_resolved(edges):
    hits = find(
        edges,
        src="pkg.services.OrderService.save",
        dst="pkg.services.OrderService.check",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_name_match_both_candidates(edges):
    hits = find(
        edges,
        src="pkg.services.OrderService.save",
        rel="calls",
        confidence="name_match",
    )
    render_hits = [e for e in hits if e.dst_qname.endswith(".render")]
    assert {e.dst_qname for e in render_hits} == {
        "pkg.models.render",
        "pkg.util.render",
    }


def test_external_call_no_edge(edges):
    assert not [e for e in edges if "requests" in e.dst_qname]


def test_inherits_edge(edges):
    hits = find(
        edges, src="pkg.models.Node", dst="pkg.models.Base", rel="inherits"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_attr_ref_references_edge(edges):
    hits = find(edges, src="pkg.cli", dst="pkg.util.helper", rel="references")
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_sibling_resolution(edges):
    hits = find(
        edges, src="pkg.util.cached_helper", dst="pkg.util.helper", rel="calls"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def _module_extraction(qname, symbols=(), refs=()):
    return FileExtraction(
        path=qname.replace(".", "/") + ".py",
        language="python",
        module_qname=qname,
        symbols=[
            SymbolRecord("module", qname.rsplit(".", 1)[-1], qname, 1, 1, "h"),
            *symbols,
        ],
        imports=[],
        refs=list(refs),
    )


def test_candidate_cap_and_dedupe():
    definers = [
        _module_extraction(
            f"m{i}",
            symbols=[SymbolRecord("function", "dup", f"m{i}.dup", 1, 1, "h")],
        )
        for i in range(7)
    ]
    caller = _module_extraction(
        "caller",
        refs=[
            RefRecord("call", "caller", "dup", 3),
            RefRecord("call", "caller", "dup", 3),  # dedupes to one edge each
        ],
    )
    edges = resolve([*definers, caller])
    name_matches = [e for e in edges if e.confidence == "name_match"]
    assert len(name_matches) == 5
    assert [e.dst_qname for e in name_matches] == [
        "m0.dup",
        "m1.dup",
        "m2.dup",
        "m3.dup",
        "m4.dup",
    ]
