---
name: cartograph-kb
description: Protocol for the cartograph typed knowledge base — resolving an unfamiliar acronym or internal term before assuming it, reading an entry in full before quoting it, and proposing an entry for human review without ever publishing one. Use when you meet a term the source never spells out, before writing an ADR or a project glossary, when a human corrects your understanding of a convention, when you see kb_lookup/kb_get/kb_propose, or when a repo has a CONTEXT.md or docs/adr/.
---

# Cartograph knowledge base

Three tools: `kb_lookup` resolves a term, `kb_get` reads one entry in full or
lists a type's index, `kb_propose` writes a proposal a human must approve.
Entries are typed — `glossary`, `convention`, `decision`, `specification`,
`runbook`.

**Postgres is the source of truth.** The `CONTEXT.md` and `docs/adr/` files in a
repo are an export of it, produced by a CLI. They are a copy.

## The one constraint that shapes everything

> **Publishing is a human act.** `kb_propose` writes to a queue that no lookup
> reads. You will never see your own proposal come back from `kb_lookup` — not
> this session, not the next one, not after any wait. If a fact must survive
> this session, it goes in your **return value** as well.

An unreviewed, agent-authored knowledge base is worse than none: it becomes
confident-sounding lore that later sessions treat as truth. The review queue is
the only thing standing between this KB and that outcome — and a queue nobody
reads is the same as no queue. That is the whole reason you propose almost
never.

## Reading before writing

Three rungs, and most sessions stop at the first:

```
kb_lookup(term, repo=…)          → match + truncated definition + slug
kb_get(slug="<slug>", repo=…)    → the whole entry, untruncated
kb_get(type="decision", repo=…)  → that type's index: slugs and titles, no bodies
```

**Pass `repo` whenever you are working inside one repository.** Two repos may
each define the same term; unscoped, the tie-break between them is arbitrary
and you get `match: "exact"` on the wrong one. With `repo`, a repo-scoped entry
shadows a global one of the same title, which is almost always what you want.

`kb_lookup` **truncates at 400 characters**. A glossary term written to the
one-or-two-sentence rule never hits that, so a truncated body is itself a
signal: you are looking at a specification or a runbook, and you have a
fragment. Never quote a truncated `definition` as the entry's content — the
`slug` it returns is the handle, and `kb_get` is one call.

Before any propose, read the index. *The index is cheap, and you are wrong
about the slug more often than you are wrong about the term.* An index that
comes back carrying `truncated` is **partial** — narrow it with `repo` before
concluding your term is absent.

## The types

| type | for | slug looks like | may you propose it? |
| --- | --- | --- | --- |
| `glossary` | one project term, one sanctioned meaning | `psn` | yes, rarely |
| `convention` | a house rule you were corrected on | `branch-names` | yes, when corrected |
| `decision` | an ADR: what was chosen, over what | `flat-threads` | only when a human stated it |
| `specification` | a contract of record | `board-protocol` | **no** — humans write these |
| `runbook` | operational steps | `rotate-voyage-key` | **no** |

## When to propose — and when to stay silent

> **If you learned it from the code, it is not knowledge-base material.**
> Propose only what the code cannot say for itself: a term a human used that the
> source never spells out, a decision a human made and the alternative it beat,
> a convention you were corrected on. If you can point at the file that already
> says it, point at the file.

Never propose:

- **What you just built.** The KB is not a changelog and not a work log.
- **General programming concepts.** A glossary that defines "dependency
  injection" is a glossary nobody reads.
- **Anything the source already states.** That is what `search_code` is for.
- **Anything you inferred** rather than were told. Inference belongs in your
  return value, where it is visibly yours.
- **"X calls Y."** That is the graph's job, and `get_neighbors` already answers
  it better than prose can.

**Cap: at most 2 proposals per session, and the default is 0.** A proposal costs
a human a minute of review. An agent that proposes every session trains that
human to publish without reading, which is precisely the failure the queue
exists to prevent.

### Decision table

| What happened | What you do |
| --- | --- |
| You met an acronym | `kb_lookup`. Propose nothing |
| Lookup missed, and then a human told you what it means | Propose `glossary` |
| A human corrected your approach | Propose `convention` |
| A human chose between two designs in front of you | Propose `decision` |
| **You** chose an approach | Propose nothing — it goes in the return value |
| You wrote a module | Propose nothing |
| You read the code and worked it out | Propose nothing |

## Entry discipline

**Glossary** carries the full rule, because it is the type you will actually
propose:

> One entry per concept, **one or two sentences**, project-specific only. Be
> opinionated: pick **one** word and list every rejected synonym under `avoid`.
> A definition that hedges between two names has failed — the point of the entry
> is that the next session stops choosing.

> **A good week shortens the glossary as often as it lengthens it.** Proposing a
> *shorter* replacement for an existing slug is a first-class proposal, not a
> correction of someone's mistake. Proposing an existing slug proposes a
> revision, and the reply tells you so.

**Decision** is past tense and names what it beat. Payload carries `context`,
`consequences`, `decision_status`, `supersedes`. *"We should" is not a decision;
it is a suggestion, and suggestions do not go in the KB.*

**Convention** states the rule, then `rationale` says why. A convention without
a rationale gets argued with; one with a rationale gets followed.

## Sequences

MCP tools may sit behind tool search, so load them first:

```
ToolSearch("select:mcp__cartograph__kb_lookup,mcp__cartograph__kb_get,
            mcp__cartograph__kb_propose")
```

Resolving a term:

```
kb_lookup(term="PSN")
    ↳ match: "exact"   → done. If `truncated`, kb_get(slug=<slug>) before quoting
    ↳ match: "alias"   → done
    ↳ match: "vector"  → these are NEAREST, not definitions. Treat as suggestions
    ↳ match: "none"    → the KB has no exact or alias entry. Ask the human
```

Proposing, after the gate above says yes:

```
kb_get(type="glossary")          → is it already there under another slug?
kb_propose(
    agent_name="impl-<branch>-<slug>-<run>",
    type="glossary", slug="psn", title="PSN",
    body="PositageNet. Never any other expansion.",
    payload={"avoid": ["PlayStation Network"]})
```

Replies you must handle:

| reply | meaning |
| --- | --- |
| `status: proposed` | queued. Restate it in your return value too |
| `status: proposed` + `revision_of` | you are revising a live entry. Fine, and often good |
| `status: duplicate` | already queued. Nothing was written. Move on |
| `status: rejected_before` | **a human already said no, and `reason` says why.** Nothing was written. Do not rephrase and retry |
| `error` + `fields` | your payload is wrong; `fields` is the shape it wanted |
| `error` + `types` | your type is not real; `types` lists the real ones |

`agent_name` follows the board's convention — `<role>-<branch>-<slug>-<run>`,
all four fields, run being `MMDD` plus a letter. The first proposal
self-registers it, exactly like a first board post. See `agent-board`.

## Limits — state these rather than discovering them

- **Nothing you propose is ever visible to you.** No status query, no
  notification, no callback. A rejection reaches you only if you propose the
  same slug again in a later session.
- **A vector miss and a rate-limited embedder are indistinguishable.** The
  lookup catches an embedding failure and returns `{"match":"none"}` — byte for
  byte what an undefined term returns. With `VOYAGE_API_KEY` unset or throttled,
  the vector tier silently never fires. So read `match: "none"` as *"no exact or
  alias entry"*, never as *"the KB has nothing about this."*
- **`match: "vector"` results are proximity, not definition.** They are the five
  nearest embeddings, with no threshold. A vector hit is a suggestion to read,
  never an answer to quote.
- **`kb_lookup` truncates; it does not summarize.** The fragment ends mid-entry.
- **The index is not search.** `kb_get(type=…)` returns slugs and titles in
  order, with no ranking and no body matching.
- **Nothing can be edited or deleted from this surface.** Every wrong slug is
  permanent as far as you are concerned; cleanup is a human in the SPA.
- **The KB is global unless `repo` is set.** An unqualified propose lands in
  every repository's context. A repo-scoped entry shadows a global one of the
  same title.
- **The Markdown is a copy.** `CONTEXT.md` and `docs/adr/` are exported from
  Postgres by `python -m cartograph.kb.export`. Editing them changes nothing,
  and they lag until someone runs it. When a file and `kb_get` disagree,
  `kb_get` is right.
- **Degradation:** if a KB call errors, retry once, then proceed without it and
  say so in your return value. The KB must never block the actual task.
