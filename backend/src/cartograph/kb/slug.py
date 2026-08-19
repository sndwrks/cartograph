"""Slug derivation for knowledge-base entries."""

from __future__ import annotations

import re
import unicodedata

FALLBACK = "entry"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str, max_len: int = 60) -> str:
    """Title -> stable slug: lowercase ASCII, non-alphanumerics collapsed to '-'.

    The typed-KB migration backfills slugs with the SQL equivalent

        nullif(trim(both '-' from regexp_replace(lower(term),
                                                 '[^a-z0-9]+', '-', 'g')), '')

    and `test_slugify_matches_migration_regex` pins the two together. The NFKD
    fold and the length cap here are refinements SQL does not do — they can
    only differ for a non-ASCII or over-long title, neither of which any
    pre-migration row can have had, because `lower(term)` was unique and the
    old corpus is glossary terms.
    """
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = _NON_ALNUM.sub("-", folded.lower()).strip("-")
    if len(slug) > max_len:
        head = slug[:max_len]
        # cut on a separator so the slug never ends mid-word
        slug = (head.rsplit("-", 1)[0] if "-" in head else head).strip("-")
    return slug or FALLBACK
