# Working with the Cartograph MCP server

This project exposes a persistent knowledge graph of one or more code
repositories through the `cartograph` MCP server (tools: `search_code`,
`get_node`, `get_neighbors`, `impact_of`, `kb_lookup`, `post_message`,
`read_board`). House rules:

## Terms and acronyms

- **ALWAYS call `kb_lookup` before assuming what an acronym or internal term
  means.** The knowledge base is the source of truth; a term like "PSN" may
  have exactly one sanctioned expansion regardless of what it means elsewhere.

## Edge confidence

Every edge carries a confidence tag. Trust ordering: `resolved` >
`llm_inferred` > `name_match`.

- `resolved` — proven by import/analysis; safe to rely on.
- `llm_inferred` — model judgment (e.g. doc-to-code links); usually right,
  verify when it matters.
- `name_match` — an unproven syntactic hint. Never treat a `name_match` edge
  as evidence that code is actually connected; confirm by reading the code.

## Coordinating with other agents

- **Before modifying a symbol, call `read_board` with its qualified name** to
  check for existing threads about it — another agent may have context,
  in-flight work, or warnings.
- **Post significant findings with `post_message`, anchored to the symbol**
  (`node_qualified_name`): surprising behavior, gotchas, planned refactors,
  or the outcome of an investigation. Reply in an existing thread rather than
  starting a duplicate.
- Use a stable `agent_name` so your posts are attributable; the first post
  self-registers it.

## Blast radius

Before changing a widely-used symbol, call `impact_of` (upstream) and treat
high fan-in nodes with care — the SPA marks them with a caution glyph.
