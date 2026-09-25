from pathlib import Path

import pytest

from cartograph.extractors.base import (
    FileExtraction,
    ImportRecord,
    RefRecord,
    SymbolRecord,
)
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


def _dup_definers(count, name="dupe"):
    return [
        _module_extraction(
            f"m{i}",
            symbols=[SymbolRecord("function", name, f"m{i}.{name}", 1, 1, "h")],
        )
        for i in range(count)
    ]


def test_ambiguous_bare_name_emits_nothing():
    caller = _module_extraction(
        "caller", refs=[RefRecord("call", "caller", "dupe", 3)]
    )
    edges = resolve([*_dup_definers(7), caller])
    assert not [e for e in edges if e.confidence == "name_match"]


def test_bare_name_within_cap_and_dedupe():
    caller = _module_extraction(
        "caller",
        refs=[
            RefRecord("call", "caller", "dupe", 3),
            RefRecord("call", "caller", "dupe", 3),  # dedupes to one edge each
        ],
    )
    edges = resolve([*_dup_definers(3), caller])
    name_matches = [e for e in edges if e.confidence == "name_match"]
    assert [e.dst_qname for e in name_matches] == ["m0.dupe", "m1.dupe", "m2.dupe"]


def test_short_bare_name_emits_nothing():
    definer = _module_extraction(
        "m0", symbols=[SymbolRecord("function", "t", "m0.t", 1, 1, "h")]
    )
    caller = _module_extraction("caller", refs=[RefRecord("call", "caller", "t", 3)])
    edges = resolve([definer, caller])
    assert not [e for e in edges if e.confidence == "name_match"]


def test_short_ambiguous_name_emits_nothing():
    # generic 3-char verbs (set, has, get) with multiple candidates are
    # framework-style globals, not evidence of these particular targets
    caller = _module_extraction(
        "caller", refs=[RefRecord("call", "caller", "has", 3)]
    )
    edges = resolve([*_dup_definers(2, name="has"), caller])
    assert not [e for e in edges if e.confidence == "name_match"]


def test_short_unambiguous_name_still_matches():
    # a single repo-wide candidate stays plausible even at 3 chars
    caller = _module_extraction(
        "caller", refs=[RefRecord("call", "caller", "has", 3)]
    )
    edges = resolve([*_dup_definers(1, name="has"), caller])
    assert [e.dst_qname for e in edges if e.confidence == "name_match"] == ["m0.has"]


def test_python_self_field_call_resolved():
    service = b"class OrderService:\n    def save(self):\n        return 1\n"
    app = (
        b"from pkg.svc import OrderService\n\n"
        b"class App:\n"
        b"    def __init__(self):\n"
        b"        self.svc = OrderService()\n"
        b"    def run(self):\n"
        b"        return self.svc.save()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/svc.py", service),
            extractor.extract("pkg/app.py", app),
        ]
    )
    hits = find(
        edges, src="pkg.app.App.run", dst="pkg.svc.OrderService.save", rel="calls"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_self_call_inherited_same_module_resolved():
    # self._run() where _run is defined only on the base class, called from
    # a subclass method in the same module (the MonitorTestCase/_run shape).
    source = (
        b"class Base:\n"
        b"    def _run(self):\n"
        b"        return 1\n\n"
        b"class Sub(Base):\n"
        b"    def test_x(self):\n"
        b"        return self._run()\n"
    )
    edges = resolve([PythonExtractor().extract("pkg/tests.py", source)])
    hits = find(
        edges,
        src="pkg.tests.Sub.test_x",
        dst="pkg.tests.Base._run",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_self_call_inherited_cross_module_resolved():
    base = b"class Base:\n    def _run(self):\n        return 1\n"
    sub = (
        b"from pkg.base import Base\n\n"
        b"class Sub(Base):\n"
        b"    def test_x(self):\n"
        b"        return self._run()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/base.py", base),
            extractor.extract("pkg/sub.py", sub),
        ]
    )
    hits = find(
        edges, src="pkg.sub.Sub.test_x", dst="pkg.base.Base._run", rel="calls"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_self_call_in_closure_inside_method_resolved():
    # a nested function (closure) inside a test method calling self.x();
    # lexical `self` should still bind to the enclosing class, and the
    # method it names may live on a base class (the test_priority_order/
    # `run` shape).
    base = b"class Base:\n    def _prime(self):\n        return 1\n"
    sub = (
        b"from pkg.base import Base\n\n"
        b"class Sub(Base):\n"
        b"    def test_it(self):\n"
        b"        def run():\n"
        b"            return self._prime()\n"
        b"        return run()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/base.py", base),
            extractor.extract("pkg/sub.py", sub),
        ]
    )
    hits = find(
        edges,
        src="pkg.sub.Sub.test_it.run",
        dst="pkg.base.Base._prime",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_self_field_method_via_inherited_field_resolved():
    # self.world = Collaborator() assigned in the base class's setUp; called
    # as self.world.ingest() from a subclass method (the
    # SnapshotTestCase/self.world shape).
    base = (
        b"class Collaborator:\n"
        b"    def ingest(self):\n"
        b"        return 1\n\n"
        b"class Base:\n"
        b"    def setUp(self):\n"
        b"        self.world = Collaborator()\n"
    )
    sub = (
        b"from pkg.base import Base\n\n"
        b"class Sub(Base):\n"
        b"    def test_it(self):\n"
        b"        return self.world.ingest()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/base.py", base),
            extractor.extract("pkg/sub.py", sub),
        ]
    )
    hits = find(
        edges,
        src="pkg.sub.Sub.test_it",
        dst="pkg.base.Collaborator.ingest",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_classmethod_cls_call_inherited_resolved():
    base = (
        b"class Base:\n"
        b"    @classmethod\n"
        b"    def create(cls):\n"
        b"        return 1\n"
    )
    sub = (
        b"from pkg.base import Base\n\n"
        b"class Sub(Base):\n"
        b"    @classmethod\n"
        b"    def build(cls):\n"
        b"        return cls.create()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/base.py", base),
            extractor.extract("pkg/sub.py", sub),
        ]
    )
    hits = find(
        edges, src="pkg.sub.Sub.build", dst="pkg.base.Base.create", rel="calls"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_super_call_resolved():
    base = b"class Base:\n    def save(self):\n        return 1\n"
    sub = (
        b"from pkg.base import Base\n\n"
        b"class Sub(Base):\n"
        b"    def save(self):\n"
        b"        return super().save()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/base.py", base),
            extractor.extract("pkg/sub.py", sub),
        ]
    )
    hits = find(
        edges, src="pkg.sub.Sub.save", dst="pkg.base.Base.save", rel="calls"
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_unresolvable_self_call_dropped_not_name_matched():
    # `self._seed()` on a class whose only base is external (unittest) and
    # which does not define `_seed` itself must be DROPPED, not fanned out
    # to an unrelated same-named method elsewhere in the repo (`Other._seed`
    # below is a plausible, cap-eligible, non-generic 5-char name that would
    # previously have matched via the bare-name fallback).
    other = b"class Other:\n    def _seed(self):\n        return 1\n"
    base = (
        b"import unittest\n\n"
        b"class Base(unittest.TestCase):\n"
        b"    def test_it(self):\n"
        b"        return self._seed()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/other.py", other),
            extractor.extract("pkg/base.py", base),
        ]
    )
    assert not find(edges, src="pkg.base.Base.test_it")


def test_unresolvable_super_call_dropped_not_name_matched():
    other = b"class Other:\n    def setUp(self):\n        return 1\n"
    sub = (
        b"import unittest\n\n"
        b"class Sub(unittest.TestCase):\n"
        b"    def setUp(self):\n"
        b"        super().setUp()\n"
    )
    extractor = PythonExtractor()
    edges = resolve(
        [
            extractor.extract("pkg/other.py", other),
            extractor.extract("pkg/sub.py", sub),
        ]
    )
    assert not find(edges, src="pkg.sub.Sub.setUp")


def test_failed_import_ref_dropped():
    definer = _module_extraction(
        "other",
        symbols=[SymbolRecord("function", "useState", "other.useState", 1, 1, "h")],
    )
    caller = FileExtraction(
        path="caller.py",
        language="python",
        module_qname="caller",
        symbols=[SymbolRecord("module", "caller", "caller", 1, 1, "h")],
        imports=[ImportRecord("react", "react", 1)],
        refs=[RefRecord("call", "caller", "react.useState", 3)],
    )
    edges = resolve([definer, caller])
    # the ref's base is a known (external) import; it must not degrade to a
    # name_match against an unrelated local `useState`
    assert not [e for e in edges if e.dst_qname == "other.useState"]
