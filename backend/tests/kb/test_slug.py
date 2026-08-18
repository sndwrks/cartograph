import pytest

from cartograph.kb.slug import slugify

# Kept in sync with the migration's SQL by test_slugify_matches_migration_regex
# in test_migration.py — ASCII and under the length cap, which is every case
# the two implementations both have to handle.
SHARED_CASES = [
    ("PSN", "psn"),
    ("PS-N", "ps-n"),
    ("PS N", "ps-n"),
    ("Order Service", "order-service"),
    ("  spaced  out  ", "spaced-out"),
    ("Already-slugged", "already-slugged"),
    ("Mixed_Case/Slashes", "mixed-case-slashes"),
    ("trailing---", "trailing"),
    ("!!!", "entry"),
    ("", "entry"),
]


@pytest.mark.parametrize(("value", "expected"), SHARED_CASES)
def test_slugify_basic_cases(value, expected):
    assert slugify(value) == expected


def test_slugify_folds_non_ascii():
    assert slugify("Café Ordering") == "cafe-ordering"


def test_slugify_truncates_on_a_separator():
    slug = slugify("word " * 40, max_len=20)
    assert len(slug) <= 20
    assert not slug.endswith("-")
    assert slug == "word-word-word-word"


def test_slugify_truncates_a_single_long_run():
    assert slugify("a" * 100, max_len=10) == "a" * 10
