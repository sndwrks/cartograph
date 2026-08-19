"""Knowledge-base type layer and Markdown export (slices 15/17).

`kb.types`, `kb.slug` and `kb.views` are deliberately DB-free: nothing in them
imports a session or emits SQL, so every type's payload rules, embed text and
export rendering are unit-testable without Postgres.

`kb.export` is the exception and has to be — it reads entries to render them.
It still emits no SQL of its own: every query goes through `cartograph.query.kb`,
per the project rule that SQL lives only in the query layer.
"""
