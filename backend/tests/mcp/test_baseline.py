"""Pure extraction rules for the usage baseline (no DB)."""

from cartograph.mcp_server.baseline import extract_refs, result_meta


def _node(qname, path, id_=None):
    return {"id": id_, "qualified_name": qname, "file_path": path}


def test_search_code_refs_are_result_files():
    refs = extract_refs(
        "search_code",
        {
            "degraded": False,
            "results": [_node("a.b", "a/b.py"), _node("a.c", "a/b.py"), _node("d", "d.py")],
        },
    )
    assert refs.file_paths == {"a/b.py", "d.py"}
    assert refs.qualified_names == frozenset()


def test_search_code_empty_is_zero_not_none():
    refs = extract_refs("search_code", {"degraded": True, "results": []})
    assert refs is not None and refs.empty


def test_get_node_counts_own_file_and_callers_only():
    refs = extract_refs(
        "get_node",
        {
            "node": _node("app.svc.save", "app/svc.py", id_=7),
            "edge_counts": {},
            "edges_out": [{"qualified_name": "app.models.validate"}],
            "edges_in": [{"qualified_name": "app.cli.main"}, {"qualified_name": "app.cli.other"}],
        },
    )
    assert refs.file_paths == {"app/svc.py"}
    assert refs.qualified_names == {"app.cli.main", "app.cli.other"}
    assert refs.node_ids == {7}


def test_get_neighbors_includes_root():
    refs = extract_refs(
        "get_neighbors",
        {"nodes": [_node("r", "r.py", 1), _node("n", "n.py", 2)], "edges": []},
    )
    assert refs.file_paths == {"r.py", "n.py"}
    assert refs.node_ids == {1, 2}


def test_impact_of_excludes_root():
    refs = extract_refs(
        "impact_of",
        {
            "root": "r",
            "direction": "upstream",
            "items": [
                {"node": _node("r", "r.py", 1), "depth": 0},
                {"node": _node("c", "c.py", 2), "depth": 1},
            ],
        },
    )
    assert refs.file_paths == {"c.py"}
    assert refs.node_ids == {2}


def test_non_graph_tools_have_no_baseline():
    for tool in ("kb_lookup", "kb_get", "kb_propose", "post_message", "read_board"):
        assert extract_refs(tool, {"results": []}) is None


def test_error_results_have_no_baseline():
    assert extract_refs("get_node", {"error": "no node", "candidates": []}) is None


def test_result_meta_counts():
    assert result_meta("search_code", {"degraded": True, "results": [{}]}) == {
        "n_results": 1,
        "degraded": True,
    }
    assert result_meta("impact_of", {"items": [{"depth": 1}, {"depth": 3}]}) == {
        "n_items": 2,
        "max_depth_seen": 3,
    }
    assert result_meta("read_board", {"threads": [1, 2]}) == {"n_threads": 2}
    assert result_meta("kb_get", {"type": "glossary", "index": [1], "truncated": True}) == {
        "n_index": 1,
        "truncated": True,
    }
    assert result_meta("get_node", {"error": "ambiguous", "candidates": [1, 2]}) == {
        "error": True,
        "n_candidates": 2,
    }
