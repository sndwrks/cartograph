# Slice 04 — Tier-1 TypeScript/JS extractor

## Goal

`extractors/typescript.py` implements the slice-03 contract for `.ts`, `.tsx`, `.js`, `.jsx` files using the tree-sitter TypeScript/JavaScript grammars. The shared resolver from slice 03 is reused unchanged; anything it can't handle generically gets fixed in the resolver, not forked.

## Depends on

Slice 03 (contract + resolver + test style).

## Spec references

`initial-spec.md` §3 Tier 1.

## Requirements

### 1. Setup

1. Add `tree-sitter-typescript` and `tree-sitter-javascript` to `pyproject.toml`, pinned exact (grammar upgrades shift node types → treat as re-extraction events).
2. `.ts` uses the `typescript` grammar, `.tsx` the `tsx` grammar, `.js`/`.jsx` the javascript grammar. One extractor class handles all four extensions.

### 2. Module qnames

Path-derived, extension stripped, posix separators → dots: `src/orders/service.ts → src.orders.service`. `index.ts` collapses to its directory: `src/orders/index.ts → src.orders`.

### 3. Symbols emitted

- One `module` symbol per file.
- `class` for class declarations (incl. `export class`, `export default class`).
- `function` for: function declarations, exported function declarations, and **const/let arrow or function expressions at module scope** (`const foo = () => {...}`, `const bar = function () {...}`) — name from the declarator.
- `method` for methods and constructors inside class bodies (incl. static); getters/setters count as methods.
- Interfaces and type aliases: emit as `class`-kind symbols (the schema has no dedicated kind; they matter as inheritance/implementation targets). TS-only.
- `export default` of an anonymous function/class: name it `default`, qname `module.default`.

### 4. Imports emitted (`ImportRecord`)

Resolve module specifiers to module qnames before recording:

- Relative specifiers (`./x`, `../y/z`) resolve against the importing file's directory, then qname-ify (strip extension, collapse `/index`). Non-relative specifiers (`react`, `lodash/fp`) are external unless they match a repo path after applying **`tsconfig.json` `paths`/`baseUrl` aliases if a tsconfig exists at the repo root** (support the common `@/* → src/*` form; full tsconfig semantics not required).
- `import { A, B as C } from "./mod"` → locals `A`, `C` with targets `<mod_qname>.A`, `<mod_qname>.B`.
- `import D from "./mod"` → local `D`, target `<mod_qname>.default`.
- `import * as ns from "./mod"` → local `ns`, target `<mod_qname>`.
- `export { A } from "./mod"` and `export * from "./mod"` → re-exports: emit an ImportRecord AND a symbol-visibility note is NOT needed — the resolver's prefix matching already lets `pkg.index` re-exports resolve because `index` collapses to the directory qname. Just emit the import records.
- CommonJS in `.js`: `const x = require("./mod")` → local `x`, target `<mod_qname>`.

### 5. Refs emitted

- `call` for call expressions and `new X()` expressions (callee text as written, e.g. `svc.save`, `new OrderService`→ target_expr `OrderService`).
- `inherits` for `extends` clauses of classes **and** for `implements` clauses (both map to the `inherits` rel; confidence comes from the resolver as usual).
- `attr_ref` for member accesses on imported locals outside calls (same conservative rule as Python: leftmost identifier must be an imported local, including namespace imports `ns.thing`).
- JSX: a JSX element whose tag is capitalized (`<OrderTable />`) emits a `call` ref with target_expr `OrderTable` from the enclosing component/function.

### 6. Resolver compatibility

The slice-03 resolver must handle TS without language branching. Two things it must already do (verify; fix in `resolve.py` if not): prefix-substitution through namespace imports (`ns.save` where `ns → src.orders.service` → try `src.orders.service.save`), and `.default` targets resolving to the `module.default` symbol.

## Files

- `backend/src/cartograph/extractors/typescript.py` (+ registry entry in `base.py`)
- `backend/tests/extractors/fixtures/ts_sample/` — small fake app (see below), including a root `tsconfig.json` with a `@/*` path alias
- `backend/tests/extractors/test_typescript_extractor.py`

## Acceptance criteria

`uv run pytest tests/extractors/` passes (slice-03 tests still green), with `ts_sample` covering at least:

1. `src/models/order.ts` (class + interface, one class `implements` the interface), `src/services/orderService.ts` (class importing the model with named import, methods calling across files), `src/util.ts` (exported arrow functions), `src/index.ts` (re-export barrel), `src/components/OrderTable.tsx` (React component as const arrow fn, JSX usage of another component), `src/legacy.js` (CommonJS require + call).
2. Assertions mirroring slice 03: exact qnames/spans; named-import cross-file call → `resolved`; ambiguous bare name → `name_match` to all candidates; `extends` and `implements` → `inherits` edges; default import resolving to `module.default`; namespace import member call resolving `resolved`; `@/`-alias import resolving; `import "react"` producing no edge; a syntax-error file still yielding parseable symbols.
3. The tsx fixture's `<OrderTable />` yields a `calls` edge to the component symbol.

## Out of scope

- Database writes (slice 05).
- Full tsconfig resolution semantics, monorepo workspaces, `.d.ts` declaration merging.
- Decorator metadata, type-level references (generics arguments etc.) — types are only extracted as inheritance targets.
