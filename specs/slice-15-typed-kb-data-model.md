# Slice 15 — Typed KB data model & registry

## Goal

Turn the flat `knowledge_base` table into a typed store: every entry carries a `type` that is a key into a code-defined registry (`glossary`, `specification`, `decision`, `convention`, `runbook`), a per-type validated `payload`, a stable `slug`, a publication `status`, and optional repository scoping. The registry — a pure, DB-free package — owns each type's fields, its lookup keys, the text it embeds, and how it renders on export. Everything visible from outside keeps working byte-for-byte: the PSN determinism contract, the existing API request/response vocabulary, and every embedding already in the HNSW index.

## Depends on

Slices 08 (KB CRUD + the lookup contract) and 13 (the `kb` enrich phase, `related_kb`). Nothing in M1–M5 depends on this.

## Spec references

`initial-spec.md` §4 (`KnowledgeEntry`, `EMBED_DIM`, the extensions created in the initial migration), §5 (KB lookup determinism — "the PSN case must be deterministic"). Read [`slice-08`](slice-08-kb-agents-messages-api.md) §1 in full: its lookup ordering is the contract this slice extends without breaking.

## Requirements

### 1. Model — `models.py`

Replace `KnowledgeEntry` (currently lines 218–236). Keep the class name and `__tablename__`; nothing FKs to it, but `id` is exposed through the API and one table keeps a single HNSW index serving both `lookup` tier 3 and `related_kb`.

| column | notes |
|---|---|
| `type` | registry key. **`Text`, not `sa.Enum`** — adding a type must never need an `ALTER TYPE` (cf. the `NodeKind` name-vs-value gotcha at line 77). Validated in `query/kb.py`, not the DB |
| `slug` | stable identity **and** export filename stem. One identifier column, not two |
| `title` | was `term` |
| `body` | was `definition` |
| `aliases` | **unchanged** `ARRAY(Text)`, still nullable — the tier-2 lookup surface |
| `payload` | `JSONB`, server default `'{}'::jsonb` |
| `status` | `proposed \| published \| rejected \| archived`, server default `'published'` |
| `review_note` | the human's reason on reject; read back by `kb_propose` in slice 16 |
| `seq` | `Integer`, nullable — the ADR number |
| `repository_id` | FK `repositories.id` `ON DELETE CASCADE`, nullable. **NULL = global**, visible to every repo |
| `category` | **legacy** glossary sub-tag, superseded by `type`. Kept so `?category=` and `RelatedKbTerm` keep working; remove in a follow-up |
| `source` | `api \| mcp \| cli \| seed \| legacy` |
| `created_by` | `"human:john"` \| `"agent:impl-main.kb-0818a"` |
| `created_at` | new; `updated_at` and `embedding` unchanged |

Indexes — write the three unique ones as raw DDL, they are expression + partial:

```sql
CREATE UNIQUE INDEX ix_kb_ident       ON knowledge_base
  (coalesce(repository_id,0), type, lower(slug))  WHERE status = 'published';
CREATE UNIQUE INDEX ix_kb_title_lower ON knowledge_base
  (coalesce(repository_id,0), type, lower(title)) WHERE status = 'published';
CREATE UNIQUE INDEX ix_kb_seq         ON knowledge_base
  (coalesce(repository_id,0), type, seq)          WHERE seq IS NOT NULL;
CREATE INDEX ix_kb_type_status ON knowledge_base (type, status);
-- ix_kb_embedding_hnsw is NOT touched
```

`coalesce(repository_id, 0)` rather than the bare column: a plain multi-column unique index treats NULLs as distinct, so two global "PSN" rows would both be allowed. PG18 has `NULLS NOT DISTINCT`, but SQLAlchemy's `postgresql_nulls_not_distinct` needs ≥2.0.41 and `pyproject.toml` pins `>=2.0.40`.

**Uniqueness covers `published` rows only.** An agent must be able to propose a competing definition for a term that already exists, so the 409 moves from create time to publish time (slice 16). Rejected rows sit outside the indexes — rejecting "PSN" never blocks a later good "PSN".

**Within `type='glossary'` and `repository_id IS NULL`, `ix_kb_title_lower` degenerates to exactly today's `ix_kb_term_lower`.** That is the whole preservation argument for PSN; state it in a comment on the index.

### 2. Migration — `alembic/versions/<hash>_typed_kb.py`

`down_revision = '64f9f7a7d426'`. **Hand-write it** — generate the stub with `alembic revision -m "typed kb"` and no `--autogenerate`, which cannot reproduce `text()`-expression partial unique indexes. Copy the DDL style from the initial revision (`sa.literal_column('lower(term)')`, line 48).

Order matters:

1. Add every new column nullable, no defaults.
2. Backfill in plain SQL — **no ORM, the model has already moved on**: `type='glossary'`, `title=term`, `body=definition`, `status='published'`, `payload='{}'::jsonb`, `source='legacy'`, `created_at=updated_at` (the best proxy available). `category` untouched; `repository_id` stays NULL, which is the correct read of today's global flat table.
3. Slug backfill: `nullif(trim(both '-' from regexp_replace(lower(term),'[^a-z0-9]+','-','g')), '')`, then `'entry-'||id` for anything that empties out.
4. **Dedupe slugs before the unique index exists.** `lower(term)` was unique but slugify is lossy — "PS-N", "PS N" and "psn" all collapse. `row_number() OVER (PARTITION BY slug ORDER BY id)`, and suffix every `rn > 1` with `'--' || id`. The double hyphen is load-bearing: the regexp collapses runs of non-alphanumerics to a single `-`, so no slugified term can ever spell `--`, which makes the suffix unreachable by any natural slug. A single-hyphen row-number suffix is NOT safe — "PS-N"/"PS N"/"PS N 2" would rewrite the second to `ps-n-2`, colliding with the third and aborting step 7 on a live table.
5. `SET NOT NULL` on `type`, `slug`, `title`, `body`, `status`, `payload`, `created_at`; add the server defaults.
6. Drop `ix_kb_term_lower`; drop `term` and `definition`.
7. Create the new indexes via `op.execute`.

Downgrade deletes every row that is not a **published glossary** entry, and says so in the docstring and a `RAISE NOTICE`. Dropping the unpublished ones is required, not tidying: a surviving `rejected` row would lose its status and review_note and come back as a live term — turning a definition a human refused into fact — and `ix_kb_term_lower` is not partial, so a published entry plus a proposed revision of it (both legal, and what the documented revision flow creates) would abort the downgrade halfway.

### 3. Type registry — `cartograph/kb/`

New package. **No SQL in it**, per the global "SQL lives only in `query/`" convention — which also makes the whole type layer unit-testable with no database.

```
cartograph/kb/slug.py    slugify(text, max_len=60)
cartograph/kb/views.py   KbEntryView — frozen slots dataclass, from_model(entry)
cartograph/kb/types/     base.py glossary.py decision.py specification.py
                         convention.py runbook.py __init__.py
```

`KbEntryView` exists so `embed_text` and `export` are pure functions over a projection rather than over an ORM row bound to a session.

`base.py` declares `LookupKey = Literal["title","slug","aliases"]`, the frozen `ExportContext(repository_name, context_name, context_description, marker)`, and:

```python
class KbType(ABC):
    name: ClassVar[str]
    label: ClassVar[str]
    lookup_keys: ClassVar[tuple[LookupKey, ...]] = ("title",)
    assigns_seq: ClassVar[bool] = False
    export_dir: ClassVar[str | None] = None          # None => repo-root artifact
    class Payload(BaseModel):
        model_config = ConfigDict(extra="forbid")

    @classmethod def validate_payload(cls, raw) -> dict     # raises pydantic.ValidationError
    @classmethod def default_slug(cls, title, payload) -> str
    @classmethod def validate_entry(cls, view) -> list[str] # non-fatal lint; NEVER blocks a write
    @classmethod def embed_text(cls, view) -> str           # abstract
    @classmethod def sort_key(cls, view) -> tuple           # deterministic export order
    @classmethod def export(cls, entries, ctx) -> dict[Path, str]   # abstract
```

Classes, not instances — `REGISTRY: dict[str, type[KbType]]`. There is no per-instance state, and `Glossary.Payload` / `Glossary.export(...)` read naturally.

`export` returns a mapping so one type can emit one file for all its entries (glossary) or one per entry (everything else). It takes `ctx` because `CONTEXT.md` opens with `# {Context Name}` and a blurb — repo-level facts a *type* cannot invent from a list of entries. The CLI (slice 17) builds it from the `Repository` row.

The five types:

| type | `lookup_keys` | `export_dir` | payload |
|---|---|---|---|
| `glossary` | `title`, `aliases` | `None` → `CONTEXT.md` | `avoid: list[str]` |
| `convention` | `title`, `slug`, `aliases` | `docs/convention` | `applies_to: list[str]` (globs), `rationale`, `examples: list[ConventionExample]` |
| `decision` | `title`, `slug` | `docs/adr` | `decision_status: Literal[...] = "accepted"`, `date`, `deciders`, `context`, `consequences`, `supersedes: list[str]` |
| `specification` | `title`, `slug` | `docs/spec` | `summary`, `owner`, `requirements: list[str]`, `related_nodes: list[str]` (qualified names — a soft link to the graph, deliberately not an FK) |
| `runbook` | `title`, `slug` | `docs/runbook` | `trigger`, `severity`, `steps: list[str]`, `verification`, `rollback` |

`Decision.assigns_seq = True`, `sort_key -> (view.seq,)`. The ADR's own `## Status` is `payload.decision_status` — named apart from the row's publication `status` so the collision is impossible to trip over in code.

**`Glossary.Payload` must NOT declare `aliases`.** `aliases` is the top-level column the sacred tier-2 SQL reads; a second home guarantees drift. `lookup_keys = ("title","aliases")` unambiguously names the column.

**`Glossary.embed_text` returns exactly `f"{title}: {body}"`** — byte-identical to the hardcoded f-string at `enrich/kb.py:24`, so every migrated row keeps its embedding and no Voyage spend is repeated. There is a test pinning the literal.

`types/__init__.py` exports `REGISTRY`, `LOOKUP_PRECEDENCE = ("glossary","convention","decision","specification","runbook")`, `DEFAULT_TYPE`, `UnknownKbTypeError`, `get_type`, `types_with_lookup_key(key)`, `type_rank(name)` — and runs an **import-time self-check**: names unique and equal to the dict keys, every name present in `LOOKUP_PRECEDENCE`, every `lookup_keys` member a valid `LookupKey`, every `export_dir` relative with no `..`.

### 4. Query layer — `query/kb.py`

`lookup(session, term, *, type=None, repo_filter="*", embedder=None)`. Tier 1 splits into two sequential index probes rather than one `OR` — more obviously deterministic, and each probe hits a unique index:

```
1a  lower(title) = lower(:q)  AND type = ANY(:types_with_title_key)   → match:"exact"
1b  lower(slug)  = lower(:q)  AND type = ANY(:types_with_slug_key)    → match:"exact"
2   EXISTS (SELECT 1 FROM unnest(aliases) AS al WHERE lower(al)=lower(:term))
                              AND type = ANY(:types_with_alias_key)   → match:"alias"
3   embedding IS NOT NULL, cosine order, limit 5                      → match:"vector"
```

Every tier gains `status='published'` and the repo scope. **The tier-2 predicate text is copied verbatim from the current lines 105–108** — only conjunctive filters are added, which is a narrowing and cannot change behavior for a corpus in which no other status could previously exist.

`lookup_keys` resolves over **physical columns** — not JSONB, not a `kb_aliases` table. Tier 1 must be an equality probe against a *unique* index to guarantee at-most-one-row, and no partial unique index can cover an element of a JSONB array, so JSONB cannot express the determinism contract at all. A join table is the better answer once lookup keys become open-ended; today there are exactly two sources and it would buy a join inside the sacred SQL. **Do not index the alias tier** either — a GIN index needs an `IMMUTABLE kb_lower_array()` helper and a rewritten predicate, which is precisely the change slice 08 forbids. Revisit above ~50k entries.

When two types match one term, return the **single highest-precedence row** plus a stub list. Both orderings are total (the precedence tuple; repo-scoped outranks global) and uniqueness is per `(scope, type)`, so the winner is provably unique:

```python
{"match": …, "results": [entry], "also_matched": [entry, …]}
```

Other functions:

- `create_entry(session, title, body, aliases=None, category=None, *, type="glossary", slug=None, payload=None, repository_id=None, status="published", source=None, created_by=None)` — **the positional order is load-bearing**, see §8.
- `list_entries(session, category=None, limit=50, offset=0, *, type=None, status="published", repo_filter="*", q=None)` and `count_entries(...)` — `category`/`limit`/`offset` stay positional so the slice-08 call shape still works. Plus `list_entry_index(session, type, ...)` returning `(slug, title)` columns only, for the MCP index.
- `next_seq(session, type, repository_id)` — "scan for the highest and increment", made race-safe without a retry loop by `pg_advisory_xact_lock(hashtext('kb_seq:'||type||':'||coalesce(repo,0)))` before the `max(seq)+1`. `ix_kb_seq` is the backstop.
- `entries_for_export(session, type, repository_id, include_global=True)` — `DISTINCT ON (lower(title))` ordered `lower(title), (repository_id IS NULL), slug, id` so a repo-scoped entry **shadows** a global of the same title and `CONTEXT.md` never lists a term twice. This belongs here, not in `KbType.export`; the type layer stays DB-ignorant.
- `update_entry` widens its embedding-invalidation trigger from `{term, definition}` to `{title, body, payload, type}`, because `embed_text` now reads payload and differs per type. Do not introspect `embed_text` to narrow it — the coarse rule is correct and cheap.
- New errors `UnknownKbTypeError`, `PayloadValidationError`, `InvalidTransitionError`. `DuplicateTermError` **keeps its name** — routers and tests import it, and a lost uniqueness race translates the resulting `IntegrityError` into it so the racing case answers 409 like the non-racing one.

`RepoFilter = int | None | Literal["*"]`: an int means that repo plus globals, `None` means globals only, `"*"` (the default) means no filter.

### 5. API — `api/routers/kb.py`, `api/schemas.py`

| method | path | notes |
|---|---|---|
| `POST` | `/kb` | `type` defaults `glossary`, `status` defaults `published` |
| `GET` | `/kb` | `?type=&status=&repo=&category=&q=&limit=&offset=` → `{entries, total}`; `status` defaults `published` |
| `GET` | `/kb/types` | `name`, `label`, `lookup_keys`, `export_dir`, `Payload.model_json_schema()` |
| `GET` | `/kb/lookup` | `?term=&type=&repo=` — unchanged semantics |
| `GET/PUT/DELETE` | `/kb/{id}` | |

**`/types` and `/lookup` must both be declared above `/{entry_id}`.** The file already documents this hazard for `/lookup` (line 57 vs 66); `test_kb_types_endpoint_lists_registry` is what guards it.

`KBCreate` accepts **both vocabularies** — `term`/`definition` as deprecated aliases for `title`/`body`, plus `repository: str | None` (a repo *name*, resolved to an id) and `payload`. A `model_validator(mode="after")` requires exactly one of each pair. This compat layer is the single decision that lets every existing test in `tests/api/test_kb.py` pass unedited.

`KBEntryOut.from_entry` gains `type`, `slug`, `title`, `body`, `payload`, `status`, `seq`, `repository_id`, `created_at`, and **retains** `term` (= title), `definition` (= body), `category`, `aliases`, `updated_at` — with a comment marking the three legacy fields for removal once the SPA (slice 18) moves to `type`/`title`/`body`/`payload`.

Codes: 201 create; 409 duplicate; **422** unknown type or payload validation, returning pydantic's error list verbatim; 404 unknown id.

### 6. Enrichment — `enrich/kb.py`, `query/enrich.py`

Replace only the `texts = [...]` line (`enrich/kb.py:24`) with a guarded build that maps each entry through `REGISTRY[entry.type].embed_text(KbEntryView.from_model(entry))`, counting an unknown type or bad payload into `failed` and skipping the entry. The `batch_spans` loop, the per-batch commit, and the `{"embedded","failed"}` return are unchanged, so `failed_phases()` → `EXIT_PARTIAL_FAILURE` keeps working for free and resumability still rests on `embedding IS NULL`.

`kb_entries_needing_embedding` gains `status != 'rejected'`. **Embed proposals** — it costs nothing at KB scale and makes publishing instant instead of "wait for the next enrich run" — but never embed rejections, which are dead spend.

### 7. `related_kb` — `query/graph.py`, `api/routers/graph.py`

`related_kb(session, node_id, limit=5, types=None)` gains `status = 'published'` and repo scoping (`repository_id IS NULL OR repository_id = node.repository_id`, derived from the `Node` already loaded, so no extra query). The route gains an optional repeatable `?type=`.

This is the read surface that is easy to forget: today it selects `KnowledgeEntry` with no status awareness and would leak unreviewed proposals straight into the graph side panel.

Returned dicts add `id`, `type`, `slug`, `title`, `body` and **keep `term`, `definition`, `category`, `score` verbatim**, so `web/src/api/client.ts` and `NodeDetail.tsx` need no changes until slice 18.

### 8. The compatibility contract

Four decisions, each currently asserted by a test. Breaking any of them means the design is wrong, not the test.

1. **`{match, results}` is the frozen top level of the lookup response**, at both the HTTP and MCP layers. `tests/api/test_kb.py:35` and `tests/mcp/test_tools.py:113` assert **exact dict equality** on the `"none"` case. Therefore `also_matched` is **omitted by both serializers when empty**, and any future field goes inside a result object. Add a one-line comment above both assertions saying so.
2. `KBCreate` accepts `term`/`definition`; `KBEntryOut` and `related_kb` keep emitting `term`/`definition`/`category`.
3. `create_entry`'s positional signature stays `(session, title, body, aliases, category)` — identical in shape to today's, which `tests/mcp/test_tools.py:96` and `tests/enrich/test_enrich_phases.py:20` call positionally.
4. `Glossary.embed_text` is byte-identical to the old f-string.

## Files

- `backend/src/cartograph/kb/{__init__.py,slug.py,views.py}`
- `backend/src/cartograph/kb/types/{__init__,base,glossary,decision,specification,convention,runbook}.py`
- `backend/alembic/versions/<hash>_typed_kb.py`
- `backend/src/cartograph/models.py`, `query/{kb.py,enrich.py,graph.py}`, `api/routers/{kb.py,graph.py}`, `api/schemas.py`, `enrich/kb.py`
- `backend/tests/kb/{__init__.py,conftest.py,test_types.py,test_slug.py,test_migration.py}`
- `backend/tests/api/test_kb.py` (append only), `tests/api/test_graph_endpoints.py`, `tests/enrich/test_enrich_phases.py`, `tests/test_models_roundtrip.py`

## Acceptance criteria

1. **Every existing KB test passes byte-for-byte unmodified** — `tests/api/test_kb.py` (all six) and `test_kb_lookup_psn_determinism` in `tests/mcp/test_tools.py`. If one needs editing, the §8 compat layer is wrong; fix that, not the test.
2. **PSN under types:** create glossary `PSN` and a `runbook` titled `PSN`. `GET /kb/lookup?term=psn` still returns `match:"exact"`, exactly one result, the glossary one — and names the runbook in `also_matched`. `?type=runbook` returns the runbook.
3. `test_glossary_embed_text_matches_legacy_format` asserts the exact `f"{title}: {body}"` string, so the migration cannot silently invalidate every embedding.
4. Export formats are pinned by golden strings, with no DB: `CONTEXT.md` renders `## Language`, `**Order**:`, `_Avoid_: Purchase, transaction`, and omits the `_Avoid_` line entirely when empty; a decision renders `docs/adr/0001-use-postgres.md` zero-padded. Shuffled input produces identical bytes, and calling `export` twice is identical.
5. Uniqueness: same slug in a different type is allowed; in a different repository is allowed; same `(repo, type, slug)` while published is 409. A `decision` gets `seq` 1, 2, 3 within a repo, independently per repo.
6. `GET /kb/types` lists all five with their payload JSON Schema — and by existing, proves `/types` was declared above `/{entry_id}`.
7. The `kb` enrich phase embeds a `decision` in decision format rather than `"title: body"`, counts an unknown type into `failed`, skips `rejected` rows, and re-embeds after a payload change.
8. `related_kb` returns both the typed and the legacy fields, excludes non-published rows, and is scoped to the node's repository plus globals.
9. `tests/kb/test_migration.py` runs `alembic downgrade -1`, inserts legacy-shaped rows by raw SQL, runs `upgrade head`, and asserts the glossary backfill and the slug dedupe. **It needs its own throwaway database** — it mutates schema and cannot use the session-scoped engine and outer-transaction fixture at `tests/conftest.py:90`. Use a module-scoped fixture on the same raw-asyncpg pattern as `_ensure_test_database`.
10. `test_slugify_matches_migration_regex` runs the migration's exact SQL expression against the same fixtures through the DB, so the two implementations cannot drift.
11. `cd backend && uv run pytest` fully green.

## Out of scope

- The `proposed`/`rejected`/`archived` lifecycle beyond storing the column — no publish, reject or archive endpoint yet (slice 16).
- Any MCP change (slice 16).
- The export CLI; `entries_for_export` lands here but nothing calls it yet (slice 17).
- Any SPA change; §5 and §7 exist precisely so the SPA needs none (slice 18).
- Dropping the legacy `category` column and the `term`/`definition` aliases — a follow-up, after slice 18.
- A `kb_aliases` join table, and any index on the alias tier.
