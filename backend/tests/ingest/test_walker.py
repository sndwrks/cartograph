from cartograph.ingest.walker import denied_dirs, is_excluded, walk_repo


def _seed(root, *paths):
    for p in paths:
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n")


def test_walk_repo_default_deny(tmp_path):
    _seed(tmp_path, "src/a.py", "gen/b.py", "node_modules/c.py", ".hidden/d.py")
    assert walk_repo(tmp_path) == ["gen/b.py", "src/a.py"]


def test_walk_repo_exclude(tmp_path):
    _seed(tmp_path, "src/a.py", "gen/b.py", "deep/gen/c.py")
    assert walk_repo(tmp_path, ["gen"]) == ["src/a.py"]


def test_is_excluded_matches_walk_pruning():
    deny = denied_dirs(["gen"])
    assert is_excluded("gen/b.py", deny)
    assert is_excluded("deep/gen/c.py", deny)
    assert is_excluded("a/node_modules/c.py", deny)
    assert is_excluded(".meteor/x.js", deny)
    assert not is_excluded("src/a.py", deny)
    # only directory components count, not the filename itself
    assert not is_excluded("src/gen.py", deny)
