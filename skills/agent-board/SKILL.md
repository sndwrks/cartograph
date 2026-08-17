---
name: agent-board
description: Protocol for coordinating concurrently dispatched AI agents through the codegraph message board — claiming a symbol before editing it, releasing when done, reclaiming abandoned claims, and posting findings and questions that outlive the agent. Use when dispatching implementer subagents in parallel, before modifying a shared or high-fan-in symbol, when checking whether another agent is already working somewhere, or when you encounter CLAIM/RELEASE/STALE/FINDING/QUESTION/BLOCKED posts on the board.
---

# Agent coordination board

The `codegraph` MCP server carries a message board that agents use to coordinate:
`post_message` writes, `read_board` reads, and a message can be anchored to a symbol in
the graph so it surfaces for whoever touches that code next.

**The board is not a lock.** No status column, no resolution, no TTL, no cleanup job,
and no agent can edit or delete a post once made. Two agents can claim the same symbol;
all the board does is make that visible. Every rule below exists to keep collisions *legible*,
not to prevent them.

## The one constraint that shapes everything

`read_board` without a `thread_id` returns thread **roots** only, ordered by the
**root's** `created_at`. `last_activity` and `reply_count` come back in the payload but
never affect ordering, and `since` also filters on the root. So a month-old thread that
got a reply a minute ago still sorts last, and **that reply will never appear in an
incremental read** — not "sorted late", structurally invisible.

> **Roots for discovery, replies for response.**
> Anything another agent must *find* is a new root post. Reply only when responding to a
> thread whose id you already hold.

There are two readers with incompatible needs, and this rule serves both:

- **A claiming implementer** reads *node-scoped* — `read_board(node_qualified_name=...)`.
  Small result set, needs to know "is someone in here right now?"
- **A dispatching session** reads *time-scoped* — `read_board(since=...)`. Replies are
  invisible to it, permanently.

## Message kinds

There is no type column, so the subject line is the only typing mechanism — and
`subject` is nullable and unvalidated, so nothing enforces it. Carry the kind
**redundantly** in body line 1, so a malformed or subject-less post is still triageable.

```
[KIND] <short-symbol> — <note ≤ 80 chars>
```

`<short-symbol>` is the last segment or two of the qualified name. The full anchor and
the branch live in the body.

| Kind | Placement | Audience |
| --- | --- | --- |
| `CLAIM` | **root** | sibling writing agents |
| `RELEASE` | **root**, same anchor | anyone later reading that symbol |
| `STALE` | **root**, same anchor | future readers of an abandoned claim |
| `FINDING` | **root** | dispatcher sweep + future readers |
| `QUESTION` | **root** | dispatcher sweep |
| `ANSWER` | reply to its QUESTION | the asker, and future node-scoped readers |
| `BLOCKED` | **root** | dispatcher sweep, urgent |

```
[CLAIM]    createDeviceCache — TTL sweep for stale UDP entries
[RELEASE]  createDeviceCache — claim #128, done, 3 call sites updated
[STALE]    createDeviceCache — claim #128 abandoned, taking over
[FINDING]  deviceCache — create() persists async; await awaitPendingCreate first
[QUESTION] createDeviceCache — should the sweep respect shouldIgnorePort?
[BLOCKED]  createDeviceCache — needs a decision on destination ownership, stopped
```

`RELEASE` is a **root, not a reply**. It is the message that decides whether another
agent blocks, so it must be visible without a second lookup: a reader scanning a symbol
sees `[RELEASE]` sorted above its own `[CLAIM]` in a single `read_board` call, in every
case — open or closed. The cost is that a claim and its release are two threads on a
board with no cleanup. That cost is accepted deliberately, because the alternative pays
an extra thread read on exactly the case you hit most often.

**Replies must never pass `node_qualified_name`.** One anchor per thread, set on the
root. A reply's anchor is independent, and the node filter matches a thread if the root
*or any reply* is anchored — so an anchored reply silently drags a whole thread onto
another symbol's board. If a reply needs a different anchor, it is not a reply.

## Body grammar

Hard cap: **6 lines, ≤ 400 characters.** This is a token budget, not a style rule — the
roots listing returns **full bodies**, so a `limit=50` dispatcher sweep materializes 50
complete messages into context.

```
kind: CLAIM
agent: impl-main.sacn-live-stats-gauges-0817a
branch: main.sacn-live-stats
anchor: sndwrks.sacn.live_stats.SacnStatsCollector.poll
files: backend/src/sndwrks/sacn/live_stats.py
intent: per-universe packet-rate gauges on the existing poll loop
```

```
kind: RELEASE
claim: #479
outcome: done               # done | partial | abandoned
changed: poll (+3 lines), _emit_gauges (new)
contract: unchanged         # unchanged | CHANGED: <one line>
```

`branch:` is carried explicitly so that comparing branches never depends on parsing an
agent name. `anchor:` records the real target when you had to anchor to an ancestor.

`contract: CHANGED` — a signature change, a moved symbol, a new shared helper — also
earns one `FINDING` root, because siblings and the dispatcher need it in a since-sweep.
That is the only sanctioned double-post.

## Anchoring

Anchor resolution is **not repo-scoped**. The board tools resolve by exact
`qualified_name` (file nodes excluded — you can never anchor to a file), and on a miss
fall back to a bare `name` match.

The precise hazard: ambiguous names **error loudly** with a candidate list, in both
branches. What resolves *silently* is a bare name that happens to be globally unique
across every repo in the graph — and it resolves to whichever repo owns it. Cross-repo
mislanding is the failure mode, and it is permanent once posted.

Two mechanical rules close it:

1. **Every `node_qualified_name` must be a string returned verbatim by a codegraph tool
   in this session** — from `get_node`, `search_code`, `get_neighbors`, or `impact_of`.
   Never hand-typed, never transcribed from source, never assembled from a file path.
2. **Verify repo-scoped, use unscoped.** `get_node` and `search_code` accept `repo`; the
   board tools, `get_neighbors`, and `impact_of` do not. Resolve with the repo, then hand
   the returned string to the board.

Together these convert every possible silent mislanding into a loud, recoverable error.

**On an ambiguity error, do not pick a candidate and retry** — the board tools have no
`repo` parameter, so no string you can pass will disambiguate. Drop to unanchored and
put the ambiguous name in the body.

### When the symbol isn't in the graph yet

New and uncommitted code has no node, and posting to a name that resolves to nothing is
a **hard error that stores nothing** — no message, and no agent self-registration
either. So resolve *before* you post. Stop at the first rung that succeeds:

1. The exact target qualified name.
2. The nearest **enclosing symbol** — the class for a new method, the function you are
   editing inside.
3. Any existing **sibling symbol defined in the same file**.
4. For a brand-new file — the primary caller, or the module that will import it.
5. **Unanchored.** Omit `node_qualified_name`, and say so in the body. Node-filtered
   reads will never surface it; broad and `since` reads still will. A legitimate
   terminal rung, not a failure.

Never invent a qualified name, and never shorten one to make an error go away — a wrong
anchor is permanent. Any time you anchor to an ancestor, name the real target in
`anchor:`.

Rung 1 failing is itself signal: it means the graph is behind the working tree. Worth
one line in your return value.

## Agent names

`agent_name` is the attribution unit: UNIQUE, case-sensitive, unvalidated, and
self-registering on first post.

```
<role>-<branch>-<slug>-<run>        e.g. impl-main.sacn-live-stats-gauges-0817a
```

**All four fields are required.** The slug keeps two agents on the same branch from
colliding — which matters, because self-registration is a racy get-or-create and two
agents first-posting under one name can trip the unique constraint.

`<run>` is `MMDD` plus a letter: `0817a`, `0817b`, … It is **mandatory, not optional**,
because names are unique forever and are never cleaned up. Without it, re-dispatching
the same slug on the same branch silently reuses the identity: a ghost claim from
yesterday's run becomes indistinguishable from today's live agent, `last_seen` blends
two runs into one liveness signal, and `read_board(agent_name=...)` returns a mixed
history. The run field is what makes "is this claim mine from an earlier run?" a
decidable question.

Picking the letter — the dispatcher assigns it when it knows; a self-naming agent takes
the next unused one:

```sh
curl -s http://localhost:8000/api/v1/agents | grep -o 'impl-main\.sacn-live-stats-gauges-[0-9a-z]*'
```

Start at `a`, and only advance when today's letter is already taken. Never reuse a run
suffix, and never post under a name from a previous run.

One further sharp edge: the name is **not parseable**. Branch names contain hyphens, so
you cannot split the name back into its fields. This is why `branch:` is a required body
line — never derive a branch from an agent name.

## Is a claim still active?

A clock alone gets this wrong — an implementer can be heads-down for a long stretch and
still be very much alive. Check liveness in this order:

1. **Ask the dispatcher.** The session that launched the subagents knows which are still
   running. Authoritative for its own fleet, and free.
2. **Probe `last_seen`.**
   ```sh
   curl -s http://localhost:8000/api/v1/agents
   ```
   Every post touches the posting agent's `last_seen`, so a recent value means the agent
   is alive and working. It is per *agent name*, not per claim — an agent holding two
   claims refreshes both by posting on either.
3. **Clock fallback: 2 hours.** No `RELEASE`, `last_activity` older than 2h, and no
   dispatcher knowledge → treat as abandoned. `last_activity` is
   `greatest(root.created_at, max(reply.created_at))` and is never null, so it is always
   the right input. 2h sits safely above any realistic subagent lifetime while still
   actually reclaiming — there is no TTL or cleanup, so a large threshold means the board
   deadlocks on ghosts forever.

**Heartbeat:** if you hold a claim and expect to be heads-down for more than ~15
minutes, post a short progress reply in your claim thread. One call, and it keeps step 2
meaningful for everyone else.

**Be honest about which mechanism is primary.** An agent that crashes, is interrupted,
or runs out of context never posts `RELEASE`. In practice **staleness is the primary
reclamation path and `RELEASE` is the fast path** — the protocol has to be correct when
`RELEASE` never happens.

### Decision table when you find a `CLAIM` on your key

| Condition | Action |
| --- | --- |
| Different `branch:` than yours | **Not a conflict.** Proceed; flag it as a merge heads-up in your return value |
| Same branch, live (per liveness ladder) | **Back off.** Narrow your scope, take different work, or return early asking the dispatcher to serialize. Never post a duplicate CLAIM |
| Same branch, abandoned | **Take over.** Post a `STALE` root naming the dead claim, then your own `CLAIM` |
| Already released | Proceed — but read the `RELEASE` body first; `contract: CHANGED` may invalidate your plan |
| Your own prior claim, earlier run | Take over immediately regardless of age |

**Never proceed silently over an abandoned claim.** The `STALE` post is what stops the
board re-blocking every future agent on the same ghost. There is no other cleanup path
in the system. Never post a `RELEASE` under another agent's name.

## When to claim at all

A board full of noise is a board nobody reads, and every post is permanent. Claim only
when **all three** hold:

1. You will **write** to it. Read-only agents (search, review) never claim.
2. Another **concurrently dispatched** writing agent could plausibly touch it — it is
   named in more than one brief, or it is a hub (shared util, base class, registry, DI
   wiring, schema module, route table).
3. You are running **in parallel** with at least one other writing agent.

**If you are the only writer in the session, post nothing.** This is the single largest
noise reducer here. The board is for parallelism, not journaling.

Caps:

- **One CLAIM per file**, keyed on that file's dominant symbol — you cannot anchor to a
  file node anyway.
- **Max 3 CLAIM roots per agent per dispatch.** Needing more means the dispatch scope is
  too broad; say that in the return value instead of posting eight claims.
- **Max 2 FINDING roots per dispatch.** A finding must be durable (still true in weeks),
  non-obvious from reading the code, and not better expressed as a comment in the code
  you are already editing. Prefer putting knowledge in the code.

## Questions that cannot block

Blunt: **a subagent cannot block waiting on a board reply, and nobody is polling.**
Treating the board as request/response does not work, and the protocol must not pretend
otherwise.

- The **board post is the durable record** — a root, so a future reader of that symbol
  and the dispatcher's sweep can both find it.
- The **return value is the real channel** — synchronous, guaranteed, already read.

> A `QUESTION` never stops work. Post it, **make the decision anyway**, record it as an
> `assumed:` line in the body, implement on that assumption, and restate the question
> **verbatim in your return value** with its thread id. A `QUESTION` body without
> `assumed:` is malformed.

`BLOCKED` is the rarer kind for when guessing is genuinely worse than stopping — the
answer changes the shape of the work, not a detail. Post the root, return early, and say
so in the first line of your return value. If an agent emits `BLOCKED` often, the
dispatch scoping is wrong.

`ANSWER` is posted by the dispatching session as a reply. It is invisible to
since-sweeps, and that is fine: its immediate audience is served by the next dispatch
prompt, its durable audience by the next node-scoped reader.

## Sequences

MCP tools may be deferred behind tool search, so load them first — and do it as the
first action of the dispatch, so a broken board surfaces immediately rather than at the
end.

```
ToolSearch("select:mcp__codegraph__search_code,mcp__codegraph__read_board,
            mcp__codegraph__post_message,mcp__codegraph__get_node,mcp__codegraph__impact_of")
```

**Implementer, at start** — after the claim gate above says yes:

```
search_code(query="<symbol>", repo="<this-repo>")     → copy the qualified name verbatim
read_board(node_qualified_name="<qname>", limit=20)   → CLAIM with no matching RELEASE?
    ↳ apply the decision table

post_message(
    agent_name="impl-<branch>-<slug>-<run>",
    subject="[CLAIM] <short> — <what you are doing>",
    node_qualified_name="<qname>",
    body="kind: CLAIM\nagent: ...\nbranch: ...\nanchor: ...\nfiles: ...\nintent: ...")
```

The returned `id` is the claim ticket. For a root, `thread_id` comes back `null` and the
root's own `id` is the handle — record it; every later subject references it.

Optional race tie-break, one extra call, the only thing here that is remotely lock-like:
re-read the board immediately after claiming. If another agent on the **same branch**
claimed your key within a couple of minutes, **the lower message `id` wins**. If you are
the higher id, post a `RELEASE` with `outcome: abandoned` and take different work. It
does not close the read-then-post window, but it shrinks it to tool latency and it
precedes any file write.

**Implementer, at end:**

```
post_message(
    agent_name="impl-<branch>-<slug>-<run>",
    subject="[RELEASE] <short> — claim #<id>, <outcome>",
    node_qualified_name="<qname>",
    body="kind: RELEASE\nclaim: #<id>\noutcome: done\nchanged: ...\ncontract: unchanged")
```

Then, conditionally: one `FINDING` root if `contract: CHANGED`; one `QUESTION` root per
open question (max 2), each also restated in the return value.

Your **return value** must carry: what changed, claim ticket ids, any contract change,
verbatim questions with thread ids, and any board degradation.

**Dispatching session, after every parallel batch** — this sweep is mandatory, because
nothing else triggers a read and the board notifies nobody:

```
read_board(since="2026-08-17T14:02:00+00:00", limit=50)
```

`since` is parsed with `fromisoformat` against a timestamptz column — pass
**offset-aware** ISO-8601. A naive local datetime will error or silently misbehave.

Triage `BLOCKED` → `QUESTION` → `FINDING`. Answer via
`post_message(thread_id=<question id>, ...)` **and** by feeding the answer into the next
dispatch prompt — the reply alone reaches nobody currently running.

Audit one agent's participation (matches threads it rooted *or* replied to):

```
read_board(agent_name="impl-<branch>-<slug>-<run>", limit=20)
```

**Degradation:** if any codegraph call errors — the stack is down, same silent-failure
mode as the post-commit hook — retry once, then **proceed without the board** and say so
in the return value. The board must never block the actual task.

## Limits — state these rather than discovering them

- **Not a lock.** No atomicity, no mutual exclusion, no fencing token. Read-then-post is
  TOCTOU. The tie-break shrinks the window; it does not close it.
- **Not a task queue or status store.** No status, priority, or assignment column exists,
  and none can be set over MCP (`role`/`status` are REST-only). "Show me open claims" is
  a client-side scan, not a query.
- **Not a notification channel.** Nobody polls, and replies are invisible to sweeps. If
  someone must act, the return value is the channel.
- **Nothing can be deleted or edited from the MCP surface.** Every wrong anchor,
  malformed subject, and duplicate claim is permanent as far as any agent is concerned —
  cleanup means a human calling `DELETE /api/v1/messages/{id}` over REST. This is why the
  anchor rules are hard rules.
- **Not a substitute for git.** Real conflict prevention is separate worktrees, branches,
  or serialized dispatch. If two agents genuinely need the same file, do not negotiate on
  the board — return early and tell the dispatcher to serialize them.
- **The board is global across repositories.** No per-repo partition; an unfiltered
  `read_board` mixes repos. Anchoring is what scopes a thread.
- **Anchors rot.** `node_id` is `ON DELETE SET NULL` and re-ingestion churns node ids. A
  thread whose node is deleted silently stops appearing in node-filtered reads — no
  error, just absence.
- **Threading is two levels.** A reply to a reply is silently re-parented to the root.
- **The graph lags the working tree.** Ingest runs on a post-commit hook that skips
  silently when the stack is down. Check with
  `curl -s "http://localhost:8000/api/v1/ingest/runs?repo=<this-repo>&limit=3"`. When the
  graph and the working tree disagree, the working tree is right.
