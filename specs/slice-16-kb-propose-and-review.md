# Slice 16 — KB propose & review

## Goal

Agents read the knowledge base and propose entries to it; humans publish. `kb_lookup` becomes type-aware and truncates long bodies to a pointer, `kb_get` fetches the whole entry or a type's index, and `kb_propose` writes a `proposed` row that no lookup returns. The publish/reject/archive lifecycle lands behind three API endpoints, and `skills/cartograph-kb/SKILL.md` gives agents the protocol — most importantly, when *not* to propose.

## Depends on

Slice 15 (the typed model, the registry, `status`, `review_note`). Slice 09 (the MCP server's three-layer tool pattern).

## Spec references

`initial-spec.md` §6 (MCP tool surface; "tool descriptions instruct the model to prefer `kb_lookup`"). Read [`skills/agent-board/SKILL.md`](../skills/agent-board/SKILL.md) in full before writing the new skill — it is the house voice, and the sections it chooses are the sections to choose.

## Requirements

### 1. Status lifecycle — `query/kb.py`

Four statuses. Each must answer "who sees it, and what does export do":

| status | lookup / related_kb / MCP | default list | export (slice 17) |
|---|---|---|---|
| `proposed` | invisible | no | no |
| `published` | visible | yes | yes |
| `archived` | invisible | no | no — the exporter *deletes* its previously-written file |
| `rejected` | invisible | no | no |

No `draft`: it would answer identically to `proposed`. **Rejected rows are retained forever with their `review_note`** — that note is the only channel by which a human's judgment reaches a future session.

One function owns every transition; anything else raises `InvalidTransitionError` → 409:

```
publish:  proposed | archived -> published
reject:   proposed            -> rejected
archive:  published           -> archived
```

`set_status(session, entry_id, status, *, replaces_id=None, reason=None)`.

**Publishing is the uniqueness gate.** Because slice 15's unique indexes are `WHERE status='published'`, proposals may freely shadow a published entry; publishing into a taken `(scope, type, lower(title))` raises `DuplicateTermError` → 409 carrying the incumbent's id. `{"replaces_id": 42}` archives the incumbent and publishes the proposal **in one transaction** — this is the mechanism by which the KB gets *shorter*, which the reference model names as the success signal, so it must be one call and not a two-step dance.

### 2. API — `api/routers/kb.py`

```
POST /api/v1/kb/propose            create with status forced to "proposed"
POST /api/v1/kb/{id}/publish       {replaces_id?}
POST /api/v1/kb/{id}/reject        {reason}  — required, persisted to review_note
POST /api/v1/kb/{id}/archive
```

`/propose` must be declared **above** `/{entry_id}`, with the same hazard comment slice 15 added for `/types` and `/lookup`.

Reject with an empty or missing reason is 422. The reason is not optional because it is the payload of the `rejected_before` response in §4 — an unexplained rejection teaches the next agent nothing.

### 3. `kb_lookup` goes typed — `mcp_server/tools.py`

Signature unchanged: `kb_lookup(session, term)`.

**Rejected: a `type` filter.** You call lookup because you do not know what the term is; requiring the caller to pre-classify the answer is incoherent, and every optional parameter is schema tokens in every session that never uses it.

Result objects gain `type` and `slug`, keep `term`/`definition`/`aliases`/`category`, and truncate:

> Cut `definition` at **400 characters**, backing up to the last sentence-ending punctuation before the cap (never mid-word), append `" …"`, and set `truncated: true`.

400 is the number already in the house — the agent-board skill's body cap, picked for the same reason (an N-result read materializes N complete bodies into context). A glossary entry written to the 1–2-sentence rule never reaches the cap, so the common path stays lossless; the cap only ever bites a `specification` or `runbook`, which is exactly where a pointer beats a payload. `truncated` appears **only** when the body was cut. `status` is never returned — it is a constant, and constants are pure context cost.

Implement as `_truncate(body) -> tuple[str, bool]` used by `kb_lookup` and **never by `kb_get`**; `kb_get` is the escape hatch and must have no way to fail you.

`also_matched` is included only when non-empty — see slice 15 §8.1.

### 4. Two new tools — `mcp_server/tools.py`, `mcp_server/server.py`

Seven tools become nine. Descriptions, verbatim:

```python
@server.tool(description=(
    "Resolve company acronyms and internal terms. ALWAYS call this "
    "before assuming what an acronym means. Bodies come back "
    "truncated — pass the returned slug to kb_get for the whole entry."))
async def kb_lookup(term: str) -> dict: ...

@server.tool(description=(
    "Read one knowledge-base entry in full by slug. With only `type` and "
    "no slug, returns that type's index — every slug and title, no bodies. "
    "Read the index before proposing: most things you are about to "
    "define already exist under a slug you did not guess."))
async def kb_get(slug: str | None = None, type: str | None = None) -> dict: ...

@server.tool(description=(
    "Propose a knowledge-base entry for human review. A proposal is "
    "invisible to kb_lookup until a human publishes it, so nothing you "
    "write here reaches another session on its own — never cite your own "
    "proposal as established. Proposing an existing slug proposes a "
    "revision to it. Propose only what the code cannot say for itself: a "
    "term a human used and you had to ask about, or a decision a human "
    "stated and the alternative it beat. Never propose general "
    "programming concepts, and never propose a record of what you just "
    "built."))
async def kb_propose(agent_name: str, type: str, slug: str, title: str,
                     body: str, payload: dict | None = None,
                     repo: str | None = None) -> dict: ...
```

`kb_get` is deliberately two-mode. The alternative is a tenth tool whose entire job is returning a list of strings.

`kb_propose` forces `status="proposed"`, `source="mcp"`, `created_by=f"agent:{agent_name}"`, rejects any client-supplied status, and routes `agent_name` through the existing `get_or_create_agent` so a first proposal self-registers exactly like a first board post.

Errors must teach, following the `_resolve_node` precedent at `tools.py:27-84` where the error carries what you need to retry:

| situation | return |
|---|---|
| unknown type | `{"error": "unknown type 'adr'", "types": [...]}` |
| payload invalid | `{"error": …, "fields": {"context": "str, required", …}, "detail": [pydantic errors]}` — `fields` is derived from the registry, so a new type is self-documenting on first misuse |
| slug already published | `{"status":"proposed", "id": N, "revision_of": "<slug>"}` — a revision, not an error |
| slug already proposed | `{"status":"duplicate", "id": N}`, **no second row**. Without this one agent re-run buries the queue, and the queue is the whole feature |
| slug previously rejected | `{"status":"rejected_before", "reason": "<review_note>", "rejected_at": …}` and **no row written** |
| success | `{"status":"proposed", "id": N, "type": …, "slug": …}` |

Two implementation notes. `type` shadows the builtin inside the closure — legal, no ruff is configured, and `type` is the right *wire* name; do not rename it to `kb_type`. And verify at server boot that the SDK renders `payload: dict | None` as `{"type":"object"}`; if it chokes, fall back to a JSON string parsed in `tools.py` — decide by running the server, not by reading docs.

**Rejected: a separate `kb_search`.** `lookup` tier 3 is already a semantic vector search over the whole table; a second tool would be 80% the same query. Add it only if sessions are observed calling `kb_get(type=…)` then `kb_get(slug=…)` three or more times in a row to find one entry. The trigger is written down so the decision gets made on evidence.

**Rejected: folding propose into `post_message`.** The board has no schema, no validation, no status, and nothing reads it into a review queue. A proposal posted there is a message, not a proposal.

`INSTRUCTIONS` (`server.py:14-21`) gains one clause: the knowledge base is typed (glossary, specification, decision, convention, runbook), and you may propose entries but never publish them.

> ### This is enforcement by surface, not a security boundary
> The API has no auth — slice 08 lists it as an explicit non-goal. Anything that can reach `POST /kb/{id}/publish` can publish. What actually holds is that agents reach Cartograph through the bearer-authed MCP server and **the MCP server has no publish tool** — not "not exposed", *not implemented on that layer*. Do not describe it as a security boundary in any doc. `test_mcp_exposes_no_publish_tool` is what keeps it true.

### 5. The skill — `skills/cartograph-kb/SKILL.md`

Frontmatter `name: cartograph-kb` with a trigger-rich description: an unfamiliar acronym or internal term, before writing an ADR, when a human corrects your understanding of a convention, when tempted to write a project glossary yourself, when you see `kb_lookup`/`kb_get`/`kb_propose`, when a `CONTEXT.md` or `docs/adr/` exists in the repo.

**## The one constraint that shapes everything**

> **Publishing is a human act.** `kb_propose` writes to a queue that no lookup reads. You will never see your own proposal come back from `kb_lookup` — not this session, not the next one, not after any wait. If a fact must survive this session, it goes in your return value as well.

> An unreviewed, agent-authored knowledge base is worse than none: it becomes confident-sounding lore that later sessions treat as truth. The queue is the only thing standing between this KB and that outcome, and a queue nobody reads is the same as no queue — which is why you propose almost never.

**## Reading before writing** — the ladder: `kb_lookup(term)` → truncated `definition` + `slug` → `kb_get(slug)` for the whole thing; and `kb_get(type=…)` before any propose, because *"the index is cheap and you are wrong about the slug more often than you are wrong about the term."*

**## The types** — a table of type | what it is for | what its slug looks like | may an agent propose it. `specification` and `runbook`: **no**. `decision`: only when a human stated it.

**## When to propose — and when to stay silent** — the anti-noise gate, the KB's equivalent of the board's "if you are the only writer in the session, post nothing":

> **If you learned it from the code, it is not knowledge-base material.** Propose only what the code cannot say for itself: a term a human used that the source never spells out, a decision a human made and the alternative it beat, a convention you were corrected on. If you can point at the file that already says it, point at the file.

Then the propose-nothing list — what you just built; general programming concepts (a glossary defining "dependency injection" is a glossary nobody reads); anything the source already states; anything you inferred rather than were told; anything whose whole content is "X calls Y", which is the graph's job. Cap: **≤2 per session, default 0** — because a proposal costs a human a minute of review, and an agent that proposes every session trains that human to publish without reading, which is the exact failure mode the queue exists to prevent.

**## Entry discipline** — per type, with glossary carrying the full rule:

> One entry per concept, **one or two sentences**, project-specific only. Be opinionated: pick **one** word and list every rejected synonym under `_Avoid_`. A definition that hedges between two names has failed — the point of the entry is that the next session stops choosing.

> **A good week shortens the glossary as often as it lengthens it.** Proposing a *shorter* replacement for an existing slug is a first-class proposal, not a correction of someone's mistake.

Decisions are past tense, with the alternative it beat: *"'We should' is not a decision; it is a suggestion, and suggestions do not go in the KB."*

**## Decision table** — heard an acronym → `kb_lookup`, propose nothing; lookup missed and a human then told you → propose glossary; a human corrected your approach → propose convention; a human chose between two designs in front of you → propose decision; you chose an approach yourself → propose nothing, put it in the return value; you wrote a module → propose nothing.

**## Sequences** — the `ToolSearch("select:mcp__cartograph__kb_lookup,mcp__cartograph__kb_get,mcp__cartograph__kb_propose")` line and the propose call shape, laid out like the board skill's.

**## Limits — state these rather than discovering them**

- Nothing you propose is ever visible to you. No status query, no notification, no callback. A rejection reaches you only if you propose the same slug again.
- **A vector-path miss and a rate-limited embedder are indistinguishable.** `query/kb.py` catches the embedding failure and returns `{"match":"none","results":[]}` — byte-identical to "the KB does not define this." If `VOYAGE_API_KEY` is unset or throttled, tier 3 silently never fires. Treat `match:"none"` as "no *exact or alias* entry", never as "the KB has nothing about this."
- `definition` from `kb_lookup` is **truncated, not summarized**. Never quote it as the entry's full content.
- The index is not search: `kb_get(type=…)` returns slugs and titles, ordered, with no ranking and no body matching.
- Nothing can be edited or deleted from the MCP surface. Every wrong slug is permanent as far as you are concerned; cleanup is a human in the SPA.
- The KB is global unless `repo` is set. An unqualified propose lands in every repo's context.
- **The Markdown is a copy.** `CONTEXT.md` and `docs/adr/` are exported from Postgres by a CLI. Editing them changes nothing, and they lag until someone runs the export. When the file and `kb_get` disagree, `kb_get` is right.
- Degradation: if a KB call errors, retry once, then proceed without it and say so in the return value. The KB must never block the task.

### 6. Installer and house rules

`scripts/install-skill.sh` hard-codes `skills/agent-board` — change it to loop over `skills/*/SKILL.md` and symlink each by directory name, or the new skill silently never installs. Keep the usage line and the default `~/.claude/skills`.

Root `CLAUDE.md` gains the three tool names in its header list, and two bullets under **Terms and acronyms**: `kb_lookup` truncates — call `kb_get` with the returned slug before quoting an entry; and you may propose entries but never publish them, and must never cite your own proposal as established.

## Files

- `backend/src/cartograph/query/kb.py` (`set_status`, the propose-time checks)
- `backend/src/cartograph/api/routers/kb.py` (four endpoints)
- `backend/src/cartograph/mcp_server/{tools.py,server.py}`
- `backend/tests/api/test_kb_proposals.py`, `backend/tests/mcp/test_tools.py` (append only)
- `skills/cartograph-kb/SKILL.md`, `scripts/install-skill.sh`, `CLAUDE.md`

## Acceptance criteria

1. **The invisibility test, once per read surface** — a proposed entry is returned by none of `kb_lookup`, `kb_get`, `related_kb`, or the default `GET /kb`. This is the feature; if it ever fails, nothing else about the slice matters.
2. `test_kb_lookup_psn_determinism` still passes **unmodified**, including `assert none == {"match":"none","results":[]}`. A one-line comment now sits above it recording that the top level is frozen at `{match, results}` and new fields go inside a result.
3. Truncation: a 2000-character specification body comes back ≤402 characters, ending `"…"`, cut on a sentence boundary, with `truncated: true`. A 1–2 sentence glossary entry has **no `truncated` key at all**. The same entry through `kb_get` is untruncated and carries `updated_at`.
4. `kb_get(type="decision")` returns slugs and titles and no bodies.
5. Propose behaviour: a second identical propose returns `{"status":"duplicate"}` and creates no second row; proposing a slug that is already published returns `revision_of`; proposing a previously-rejected slug returns the reason and writes nothing; an invalid payload returns `fields` derived from the registry.
6. Publish makes the entry visible to `kb_lookup`; publishing into a taken title is 409; `{"replaces_id": …}` archives the incumbent so exactly one live row per `(scope, type, title)` remains; publishing an already-published entry is 409.
7. Reject without a reason is 422; with one, the row persists, is invisible, and its title is immediately reusable by a new proposal.
8. `test_mcp_exposes_no_publish_tool` — enumerate the registered tools and assert the set is exactly the nine expected names.
9. `./scripts/install-skill.sh /tmp/skills-test` symlinks **both** `agent-board` and `cartograph-kb`.
10. `cd backend && uv run pytest` fully green.

## Out of scope

- Any SPA surface for reviewing proposals — until slice 18 the review path is `curl`, and that is fine; documenting it in the README is part of this slice.
- The export CLI (slice 17).
- `kb_search` (see §4 for the trigger that would justify it).
- Auth on the REST endpoints — the enforcement story is the MCP surface, and this slice must not pretend otherwise.
