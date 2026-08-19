# Slice 19 — Board anchoring by name, and message deletion in the SPA

## Goal

The board's anchor is addressable by qualified name over REST, not just over MCP; an input the API does not understand is refused instead of ignored; and a human can delete a message from the SPA, which is the only cleanup path the agent protocol allows. The first two exist because an agent that anchored a claim through the REST API on 2026-08-18 got `201 Created` and an unanchored row — four of them, messages 5–8, still on the board.

## Depends on

Slices 08 (messages API), 09 (MCP tools), 14 (the board and `ThreadList`), 18 (the mutation pattern this copies).

## Spec references

`initial-spec.md` §6 (agents and messages) and §7 (SPA structure). Read `mcp_server/tools.py:29-86` (`_resolve_node`, the function this slice relocates), `api/routers/kb.py:72-75` (the same bug's first occurrence, with a comment explaining it), and `web/src/components/kb/KbEntryDetail.tsx:12-26,64-74` (the delete precedent) before starting.

## Requirements

### 1. Move node-name resolution into the query layer — `query/graph.py`, `mcp_server/tools.py`

`_resolve_node` (`mcp_server/tools.py:29-86`) is a SQL query living in the MCP layer. That breaks this repo's binding convention — *"SQL lives only in `cartograph/query/`. API routers and MCP tools are thin wrappers over the same query functions"* — and the breakage is not cosmetic: **it is the direct cause of the bug in §2.** The REST router could not resolve a name because the only resolver was on the other side of a layer boundary, so the API was built with an integer and no name path at all.

Add to `query/graph.py`:

```python
class NodeNameNotFoundError(LookupError):
    def __init__(self, qualified_name: str) -> None: ...

class AmbiguousNodeNameError(LookupError):
    def __init__(self, qualified_name: str, candidates: list[Node]) -> None: ...

async def resolve_node_by_name(
    session: AsyncSession, qualified_name: str, repo: str | None = None
) -> Node:
```

Behaviour moves verbatim from `_resolve_node` — exact `qualified_name` first, then bare `Node.name` ordered by `pagerank DESC, id`; `Node.kind != NodeKind.file` always excluded; optional repo scoping that raises `UnknownRepositoryError` (already in `query/messages.py`) for an unknown repo; `CANDIDATE_CAP = 10` candidates carried on the ambiguous error.

**Raise, do not return error dicts.** The dict shape is a presentation concern of one transport, and baking it into the query layer would force the REST router to unwrap a dict to build an `HTTPException`.

`_resolve_node` stays in `tools.py` as a thin adapter that catches both exceptions and returns **byte-identical** dicts to today's:

```python
{"error": f"no node found for {qualified_name!r}"}
{"error": f"ambiguous name {qualified_name!r} — pass a qualified name", "candidates": [...]}
```

`tests/mcp/test_board_tools.py:76-98` and `tests/mcp/test_tools.py` assert on these strings and **must pass unmodified**. That is the regression gate for this requirement: if a message-shape assertion needs editing, the adapter is wrong.

### 2. `node_qualified_name` on the messages API — `api/routers/messages.py`, `api/schemas.py`

`POST /api/v1/messages` takes `node_id: int` only. `GET /api/v1/messages` filters on `node_id: int` only. Neither accepts a name, so every REST client must run its own search first and post an integer — and an agent that reasonably assumed the MCP parameter name works over HTTP got a `201` with `node_id: null`.

Add `node_qualified_name: str | None = None` to `MessageCreate` (`messages.py:20-26`) and as a query parameter on the list endpoint (`messages.py:45-54`), resolved through §1's `resolve_node_by_name`. Both endpoints already have or gain a `repo` to scope the lookup — `GET` has `repo` today (`messages.py:50`); add `repo: str | None = None` to `MessageCreate`.

Mapping from the query layer's exceptions:

| Raised | HTTP |
|---|---|
| `NodeNameNotFoundError` | `404`, `detail=f"no node found for {name!r}"` |
| `AmbiguousNodeNameError` | `409`, `detail` naming the candidates' qualified names |
| `UnknownRepositoryError` | `404`, `detail="unknown repository"` (matches `messages.py:78-79`) |

**Passing both `node_id` and `node_qualified_name` is a `422`, not a precedence rule.** Silently picking a winner is the same failure this slice exists to remove.

Ambiguity is `409 Conflict` rather than `422`: the request is well-formed and the name is a legitimate one, there is simply more than one node wearing it. The candidate list must reach the client — a bare "ambiguous" leaves the caller no move.

### 3. Refuse unknown input instead of ignoring it — `api/schemas.py`, `api/deps.py`

This is the requirement that would have caught the incident on the first call, and it generalises past the board.

**Body.** Every schema in `schemas.py` is a plain `BaseModel`, so pydantic's default `extra="ignore"` silently drops unknown keys. `POST /api/v1/messages` with `node_qualified_name` therefore answered `201` while discarding it. This has already burned this project once, and the comment recording it is still in the tree at `api/routers/kb.py:72-75`:

> `# Present so the SPA's scope selector actually works on edit. Without it`
> `# pydantic's default extra="ignore" dropped the field and answered 200,`
> `# telling the human their change had been saved when it had not.`

That fix added one field. Two slices later the same default cost four board anchors. Fix the default, not the instance: give every **request** model in `schemas.py` `model_config = ConfigDict(extra="forbid")` — `MessageCreate`, `AgentCreate`, `AgentUpdate`, `KBCreate` and siblings. Response models (`MessageOut`, `ThreadRootOut`, `AgentOut`, `NodeOut`) keep the default; forbidding extras on the way out buys nothing and can only break serialisation.

`kb/types/*` already uses `extra="forbid"` on payloads (`base.py:63`) — this makes the API layer consistent with the KB layer rather than introducing a new idea.

**Query string.** FastAPI ignores unrecognised query parameters with no hook to change it, so `?node_qualified_name=…` on the list endpoint reads as an unfiltered success — the failure mode that made the broken read look healthy. Add to `api/deps.py`:

```python
def no_unknown_query_params(request: Request) -> None:
    """Refuse a query param the endpoint does not declare.

    An ignored filter is worse than a rejected one: an unscoped read that looks
    scoped answers "nothing is claimed here" for the whole board.
    """
```

It reads the declared parameter names off `request.scope["route"].dependant.query_params` and raises `422` listing the unknown keys. Apply it to the `/messages` router. Applying it app-wide is the obvious follow-up and is **out of scope** here — do it under one router first and see what it catches.

### 4. `repo` parity on the board tools — `mcp_server/tools.py`, `mcp_server/server.py`

`post_message` calls `_resolve_node` with no `repo` (`tools.py:232`), so board anchoring resolves globally across every repository in the graph. With a bare name and two repos indexed, a claim can land on another repository's node and stay there — the graph has no per-repo board partition and posts are not editable. `read_board` has the mirrored gap: it never passes `repo_name` to `list_threads` (`tools.py:295-298`) even though the query function accepts it.

Add an optional `repo: str | None = None` to both tools, threaded to `resolve_node_by_name` and to `list_threads(repo_name=…)` respectively, and document it in the tool descriptions at `server.py:144-180` as *pass this when working in one repository*. Do **not** make it required — that breaks every existing caller — and do not change the default resolution order.

Also expose `since` on `GET /api/v1/messages`: `list_threads` already takes it (`query/messages.py:117-118`) and only the MCP tool passes it. It is one parameter and the asymmetry is an accident, not a design.

### 5. Delete a message from the board — `web/src/api/client.ts`, `web/src/components/ThreadList.tsx`

`DELETE /api/v1/messages/{id}` has existed since slice 08 (`messages.py:91-95`) with no caller. The agent protocol says posts are immutable to agents and *"cleanup is a human `DELETE`"* — but the only human surface is `curl`. This slice gives the board the button.

Client, following the one-arrow-per-endpoint convention at `client.ts:215`:

```ts
export const deleteMessage = (messageId: number) => del(`/messages/${messageId}`);
```

In `ThreadList.tsx`, a `danger` `Button` with `size="iconSm"` on each message row — both the thread root (`:135-167`) and each reply inside `Thread` (`:39-64`).

**The confirmation must state the blast radius.** `agent_messages.thread_id` is self-referential with `ondelete="CASCADE"` (`models.py:203-205`), so deleting a root deletes every reply under it. Copy the `confirm()` idiom from `KbEntryDetail.tsx:64-74` — curly quotes around the subject — and branch on whether the message is a root:

```
Delete “{subject}” and its 3 replies? This cannot be undone.
Delete this reply? This cannot be undone.
```

A root with `reply_count === 0` gets the singular form with no reply clause. **Never show a fixed string** — the whole point is that the human sees what goes with it.

`useMutation` with `onSuccess` invalidating the §6 prefix, `disabled={remove.isPending}`, and the inline error paragraph from `KbEntryDetail.tsx:110-114`. A native `confirm()` is correct here rather than the Radix `Dialog`: `ProposalCard.tsx:79-124` uses a dialog because rejection needs a typed *reason*, and there is nothing to collect here.

Both empty-state strings at `ThreadList.tsx:125-133` end in *"(the SPA is read-only)"*, which stops being true. Rewrite them to say posting is via MCP without claiming the page cannot write.

### 6. One query-key prefix for board data — `ThreadList.tsx`, `BoardView.tsx`

Board data lives under three unrelated keys — `["threads", nodeId, agentId, repo]` (`ThreadList.tsx:78`), `["thread", rootId]` (`:47`), `["agents"]` (`:83`) — so a delete has to invalidate two of them by hand and a future mutation will forget one. Slice 18 solved this for the KB and wrote down why (`KbReviewView.tsx:68-70`): *"every KB query key is prefixed `["kb", …]`, so one invalidate refreshes the list, the detail, and the header's count."*

Re-key the thread queries to `["messages", "threads", …]` and `["messages", "thread", rootId]`, so `invalidateQueries({ queryKey: ["messages"] })` covers both. Leave `["agents"]` alone — it is a different resource and a delete does not change it.

`["node-detail", id]` in the anchor-resolution `useQueries` (`ThreadList.tsx:99-121`) also stays: the comment there records that sharing the key with `NodeDetail` is deliberate.

## Files

- `backend/src/cartograph/query/graph.py` (+ `resolve_node_by_name`, two exceptions)
- `backend/src/cartograph/mcp_server/{tools.py,server.py}` (`_resolve_node` becomes an adapter; `repo` on both board tools)
- `backend/src/cartograph/api/routers/messages.py` (+ `node_qualified_name`, `repo`, `since`, the dependency)
- `backend/src/cartograph/api/{schemas.py,deps.py}` (`extra="forbid"` on request models; `no_unknown_query_params`)
- `backend/tests/api/test_messages.py`, `backend/tests/mcp/test_board_tools.py` (the latter: **new cases only**)
- `web/src/api/client.ts`, `web/src/components/ThreadList.tsx` (+ `.module.css`)

## Acceptance criteria

1. `uv run pytest -m "not integration"` then `-m integration` both clean.
2. **`tests/mcp/test_board_tools.py` and `tests/mcp/test_tools.py` pass with no edits to any existing assertion.** The MCP error dicts are a frozen contract; §1 is a relocation, not a redesign. New cases may be appended.
3. `POST /api/v1/messages` with `{"agent_id": N, "body": "x", "node_qualified_name": "app.util.helper"}` returns `201` with a non-null `node_id`, and `GET /api/v1/messages?node_qualified_name=app.util.helper` returns that thread. Use the `seeded` fixture (`tests/conftest.py:129-220`), whose `seeded.helper` is `app.util.helper`.
4. The same POST with a name matching nothing returns `404`; with an ambiguous bare name, `409` **whose detail lists the candidates**; with both `node_id` and `node_qualified_name`, `422`.
5. `POST /api/v1/messages` with an undeclared body key returns `422` — not `201`. This is the incident, reproduced and then fixed.
6. `GET /api/v1/messages?nod_id=5` (typo'd) returns `422` naming `nod_id`, rather than `200` with the whole board. Assert the **key name appears in the detail** — a bare "unknown parameter" leaves the caller hunting.
7. `tools.post_message(session, "a1", "x", node_qualified_name="app.util.helper", repo="seeded")` anchors; the same call with `repo="other"` returns the unknown-repository error and creates **no** message.
8. `npm run lint` (oxlint) and `npm run build` (`tsc -b && vite build`) clean. No component test runner is added — same position as slice 18.
9. Manual pass via the Playwright MCP, artifacts in `.playwright-mcp/`, recorded in the PR:
   1. `/board` shows a delete button on a root and on a reply.
   2. Deleting a root with replies names the reply count in the confirm; cancelling deletes nothing.
   3. Confirming removes the thread **with no manual refresh** — this is what proves the §6 re-key.
   4. Deleting a reply leaves the root, and the root's reply count decrements.
   5. Deleting an already-deleted message (two tabs) surfaces the `404` inline rather than blanking the list.
   6. Neither empty state claims the SPA is read-only.
10. Board messages 5–8 — the four unanchored records from the incident — are deletable from the UI. That is the acceptance test for the whole slice: the bug produced garbage, and the fix includes being able to sweep it up.

## Out of scope

- **Posting or replying from the SPA.** Deletion is cleanup a human is already sanctioned to do; authoring is a different question about whether the board is a human surface at all.
- **Applying `no_unknown_query_params` app-wide.** One router first.
- **Backfilling the anchors on messages 5–8.** They are released claims with the anchor named in the body; rewriting history to repair them is worth less than deleting them.
- **Auth on `DELETE`.** The API has no user model and the SPA is unauthenticated; adding one for this button is a milestone, not a requirement.
- **Soft-delete or an audit trail for deletions.** `delete_message` is a hard delete (`query/messages.py:147-151`) and stays one.
- **A per-repo board partition.** §4 scopes *resolution*; the board itself remains global, and `query/messages.py:103-107` deliberately keeps unanchored threads visible in every repo.
