from pathlib import Path

import pytest

from cartograph.extractors.base import ImportRecord
from cartograph.extractors.resolve import resolve
from cartograph.extractors.ts_context import (
    TsResolutionContext,
    _parse_jsonc,
    discover_ts_context,
)
from cartograph.extractors.typescript import TypeScriptExtractor

FIXTURES = Path(__file__).parent / "fixtures" / "monorepo_sample"

FILES = (
    "apps/web/imports/api/methods.ts",
    "apps/web/imports/recoil/atoms.ts",
    "apps/web/client/page.tsx",
    "apps/web/client/usesCore.ts",
    "apps/web/client/orderPage.ts",
    "apps/web/client/usesDefault.ts",
    "apps/web/server/main.js",
    "apps/web/server/manager.js",
    "apps/web/server/bridge.js",
    "packages/core/src/index.ts",
    "packages/core/src/deep.ts",
    "legacy/helpers.cjs",
    "legacy/cjsApp.cjs",
)


@pytest.fixture(scope="module")
def context():
    return discover_ts_context(FIXTURES)


def extract(rel: str, context):
    return TypeScriptExtractor().extract(rel, (FIXTURES / rel).read_bytes(), context)


@pytest.fixture(scope="module")
def edges(context):
    return resolve([extract(rel, context) for rel in FILES])


def find(edges, *, src=None, dst=None, rel=None, confidence=None):
    return [
        e
        for e in edges
        if (src is None or e.src_qname == src)
        and (dst is None or e.dst_qname == dst)
        and (rel is None or e.rel == rel)
        and (confidence is None or e.confidence == confidence)
    ]


# --- discovery -------------------------------------------------------------


def test_discovery_aliases_scoped_and_repo_relative(context):
    assert set(context.alias_maps) == {"apps/web"}
    patterns = dict(context.alias_maps["apps/web"])
    # exact and glob targets are rewritten repo-relative through baseUrl
    assert patterns["@recoil/atoms"] == "apps/web/imports/recoil/atoms"
    assert patterns["@api/*"] == "apps/web/imports/api/*"


def test_discovery_exact_patterns_ordered_first(context):
    patterns = context.alias_maps["apps/web"]
    assert patterns[0][0] == "@recoil/atoms"


def test_discovery_workspace_prefers_src_index_over_main(context):
    # package.json main points at dist/, which is never ingested
    assert context.workspace_packages["@acme/core"] == (
        "packages/core",
        "packages/core/src/index",
    )


def test_discovery_package_dirs(context):
    assert context.package_dirs == frozenset({"", "apps/web", "packages/core"})


# --- specifier resolution --------------------------------------------------


def test_alias_glob_import(context):
    page = extract("apps/web/client/page.tsx", context)
    assert (
        ImportRecord("callMethod", "apps.web.imports.api.methods.callMethod", 1)
        in page.imports
    )


def test_alias_exact_import(context):
    page = extract("apps/web/client/page.tsx", context)
    assert (
        ImportRecord("userAtom", "apps.web.imports.recoil.atoms.userAtom", 2)
        in page.imports
    )


def test_alias_not_visible_outside_governing_tsconfig(context):
    deep = extract("packages/core/src/deep.ts", context)
    # apps/web's aliases must not leak into packages/core
    assert deep.imports == [ImportRecord("callMethod", "@api.methods.callMethod", 1)]


def test_workspace_package_import_resolves_to_src_index(context):
    uses = extract("apps/web/client/usesCore.ts", context)
    # src/index folds into the directory qname
    assert (
        ImportRecord("coreUtil", "packages.core.src.coreUtil", 1) in uses.imports
    )


def test_workspace_deep_import(context):
    uses = extract("apps/web/client/usesCore.ts", context)
    assert (
        ImportRecord("deepThing", "packages.core.src.deep.deepThing", 2)
        in uses.imports
    )


def test_meteor_root_absolute_import(context):
    main = extract("apps/web/server/main.js", context)
    # "/imports/..." resolves against the nearest package root (apps/web)
    assert main.imports == [
        ImportRecord("callMethod", "apps.web.imports.api.methods.callMethod", 1)
    ]


def test_destructured_require(context):
    app = extract("legacy/cjsApp.cjs", context)
    assert app.language == "javascript"
    assert ImportRecord("helper", "legacy.helpers.helper", 1) in app.imports
    assert ImportRecord("renamed", "legacy.helpers.other", 1) in app.imports


# --- end-to-end resolution -------------------------------------------------


def test_aliased_call_resolved(edges):
    hits = find(
        edges,
        src="apps.web.client.page.Page",
        dst="apps.web.imports.api.methods.callMethod",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_meteor_absolute_call_resolved(edges):
    hits = find(
        edges,
        src="apps.web.server.main.serve",
        dst="apps.web.imports.api.methods.callMethod",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_workspace_calls_resolved(edges):
    core = find(
        edges,
        src="apps.web.client.usesCore.combined",
        dst="packages.core.src.coreUtil",
        rel="calls",
    )
    deep = find(
        edges,
        src="apps.web.client.usesCore.combined",
        dst="packages.core.src.deep.deepThing",
        rel="calls",
    )
    assert len(core) == 1 and core[0].confidence == "resolved"
    assert len(deep) == 1 and deep[0].confidence == "resolved"


def test_cjs_destructured_calls_resolved(edges):
    helper = find(
        edges, src="legacy.cjsApp.run", dst="legacy.helpers.helper", rel="calls"
    )
    renamed = find(
        edges, src="legacy.cjsApp.run", dst="legacy.helpers.other", rel="calls"
    )
    assert len(helper) == 1 and helper[0].confidence == "resolved"
    assert len(renamed) == 1 and renamed[0].confidence == "resolved"


def test_field_assign_records_extracted(context):
    bridge = extract("apps/web/server/bridge.js", context)
    got = {(fa.class_qname, fa.field_name, fa.ctor_expr) for fa in bridge.field_assigns}
    assert got == {
        ("apps.web.server.bridge.BridgeServer", "manager", "CompanionManager"),
        ("apps.web.server.bridge.BridgeServer", "registry", "LocalRegistry"),
        ("apps.web.server.bridge.ConflictedHolder", "dep", "CompanionManager"),
        ("apps.web.server.bridge.ConflictedHolder", "dep", "LocalRegistry"),
        # arrow callbacks keep the lexical `this` and are recorded...
        ("apps.web.server.bridge.CallbackHolder", "arrowed", "LocalRegistry"),
        # ...while `hijacked`, assigned inside a plain function callback whose
        # `this` is rebound, must NOT appear
    }


def test_this_field_call_resolved_via_imported_class(edges):
    hits = find(
        edges,
        src="apps.web.server.bridge.BridgeServer.start",
        dst="apps.web.server.manager.CompanionManager.assign",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_this_field_call_resolved_via_sibling_class(edges):
    hits = find(
        edges,
        src="apps.web.server.bridge.BridgeServer.start",
        dst="apps.web.server.bridge.LocalRegistry.register",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_unresolvable_aliased_ref_emits_nothing(edges):
    # deep.ts's "@api/methods" import never resolved; its callMethod() ref
    # must be dropped, not name_matched into apps/web's callMethod
    assert not find(edges, src="packages.core.src.deep.deepThing")


def test_conflicting_field_types_emit_nothing(edges):
    # ConflictedHolder.dep is assigned two different constructors; a resolved
    # edge must not encode a branch-dependent guess (and `assign` has one
    # candidate, so name_match to CompanionManager.assign is still allowed)
    assert not find(
        edges,
        src="apps.web.server.bridge.ConflictedHolder.poke",
        confidence="resolved",
    )


def test_named_default_export_call_resolved(edges):
    # `import OrderPage from "./orderPage"` records <module>.default, but the
    # named default export emits OrderPage — the retry must connect them
    hits = find(
        edges,
        src="apps.web.client.usesDefault.show",
        dst="apps.web.client.orderPage.OrderPage",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


def test_renamed_default_import_falls_back_to_module(edges):
    hits = find(
        edges,
        src="apps.web.client.usesDefault.show",
        dst="apps.web.client.orderPage",
        rel="calls",
    )
    assert len(hits) == 1 and hits[0].confidence == "resolved"


# --- robustness ------------------------------------------------------------


def test_parse_jsonc_comments_and_strings():
    assert _parse_jsonc('{/* c */ "a": 1,}') == {"a": 1}
    assert _parse_jsonc('{"p": "@api/*", // c\n "q": [1,],}') == {
        "p": "@api/*",
        "q": [1],
    }
    # comma-brace sequences inside string values must survive
    assert _parse_jsonc('{"a": "x, }"}') == {"a": "x, }"}
    assert _parse_jsonc('{"a": "// not /* a comment */"}') == {
        "a": "// not /* a comment */"
    }


def test_bom_tsconfig_still_parses(tmp_path):
    (tmp_path / "tsconfig.json").write_text(
        '﻿{"compilerOptions": {"baseUrl": ".", "paths": {"@a/*": ["src/*"]}}}',
        encoding="utf-8",
    )
    ctx = discover_ts_context(tmp_path)
    assert ctx.alias_maps[""] == [("@a/*", "src/*")]


def test_malformed_manifests_do_not_abort(tmp_path):
    (tmp_path / "package.json").write_text("[1, 2]")
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": "x"}')
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "package.json").write_text('{"name": 12345}')
    (sub / "tsconfig.json").write_text('{"compilerOptions": {"paths": ["a"]}}')
    deep = tmp_path / "deep"
    deep.mkdir()
    (deep / "package.json").write_text('{"name": {"nested": true}}')
    (deep / "tsconfig.json").write_text("not json at all {")
    ctx = discover_ts_context(tmp_path)
    assert ctx.alias_maps == {}
    assert ctx.workspace_packages == {}
    assert ctx.package_dirs == frozenset({"", "sub", "deep"})
    assert ctx.resolve_workspace("anything/deep") is None


def test_alias_glob_suffix_patterns():
    ctx = TsResolutionContext(
        alias_maps={"": [("@x/*/y", "a/*/y"), ("@x/*", "b/*")]}
    )
    assert ctx.resolve_alias("@x/foo", "src") == "b/foo"
    assert ctx.resolve_alias("@x/foo/y", "src") == "a/foo/y"


def test_alias_starless_target_is_literal():
    ctx = TsResolutionContext(alias_maps={"": [("@app/*", "src/app")]})
    assert ctx.resolve_alias("@app/anything/deep", "x") == "src/app"


def test_workspace_prefix_requires_slash_boundary(context):
    # "@acme/corex" must not match the "@acme/core" package
    assert context.resolve_workspace("@acme/corex/deep") is None


def test_root_absolute_escape_is_not_resolved(context):
    result = TypeScriptExtractor().extract(
        "apps/web/server/esc.js",
        b'import { x } from "/../../outside/mod";\n',
        context,
    )
    # a ".."-escaping specifier must not mint a clean repo qname
    assert all(imp.target != "outside.mod" for imp in result.imports)
