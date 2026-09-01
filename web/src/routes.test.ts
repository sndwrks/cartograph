import { describe, expect, it } from "vitest";

import {
  boardPath,
  communityPath,
  graphPath,
  isGraphRoute,
  isIdScopedRoute,
  kbEditPath,
  kbNewPath,
  kbPath,
  kbReviewPath,
  legacyToScoped,
  matchRepoScope,
  nodePath,
  parseView,
  repoPath,
  rescopePath,
} from "./routes";

const U = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b";

describe("path builders", () => {
  it("build the prefixed shape", () => {
    expect(repoPath(U)).toBe(`/repo/${U}`);
    expect(graphPath(U)).toBe(`/repo/${U}/graph`);
    expect(communityPath(U, 12)).toBe(`/repo/${U}/c/12`);
    expect(nodePath(U, 5)).toBe(`/repo/${U}/n/5`);
    expect(boardPath(U)).toBe(`/repo/${U}/board`);
    expect(kbPath(U)).toBe(`/repo/${U}/kb`);
    expect(kbPath(U, { sel: 7 })).toBe(`/repo/${U}/kb?sel=7`);
    expect(kbReviewPath(U)).toBe(`/repo/${U}/kb/review`);
    expect(kbNewPath(U)).toBe(`/repo/${U}/kb/new`);
    expect(kbEditPath(U, 9)).toBe(`/repo/${U}/kb/9/edit`);
  });

  it("url-encodes the uuid segment", () => {
    expect(repoPath("a/b c")).toBe("/repo/a%2Fb%20c");
    expect(matchRepoScope("/repo/a%2Fb%20c/kb")).toEqual({ uuid: "a/b c", rest: "/kb" });
  });
});

describe("matchRepoScope malformed escapes", () => {
  it("treats an undecodable segment as not a repo URL instead of throwing", () => {
    expect(matchRepoScope("/repo/abc%/graph")).toBeNull();
    expect(isGraphRoute("/repo/abc%/graph")).toBe(false);
    expect(rescopePath("/repo/abc%/graph", "u")).toBe("/repo/u");
  });
});

describe("matchRepoScope", () => {
  it("splits uuid and rest", () => {
    expect(matchRepoScope(`/repo/${U}`)).toEqual({ uuid: U, rest: "" });
    expect(matchRepoScope(`/repo/${U}/kb/review`)).toEqual({ uuid: U, rest: "/kb/review" });
  });
  it("rejects unprefixed and malformed paths", () => {
    expect(matchRepoScope("/graph")).toBeNull();
    expect(matchRepoScope("/repository/x")).toBeNull();
    expect(matchRepoScope("/repo/")).toBeNull();
    expect(matchRepoScope("/repo")).toBeNull();
  });
});

describe("parseView", () => {
  it("maps id routes to their view", () => {
    expect(parseView(`/repo/${U}/c/12`)).toEqual({ mode: "community", id: 12 });
    expect(parseView(`/repo/${U}/n/5`)).toEqual({ mode: "ego", nodeId: 5 });
  });
  it("falls back to overview everywhere else, legacy included", () => {
    expect(parseView(`/repo/${U}`)).toEqual({ mode: "overview" });
    expect(parseView(`/repo/${U}/kb`)).toEqual({ mode: "overview" });
    expect(parseView("/c/12")).toEqual({ mode: "overview" });
  });
});

describe("isGraphRoute", () => {
  it.each([`/repo/${U}/graph`, `/repo/${U}/c/1`, `/repo/${U}/n/1`])("true for %s", (p) => {
    expect(isGraphRoute(p)).toBe(true);
  });
  it.each([
    `/repo/${U}`,
    `/repo/${U}/kb`,
    `/repo/${U}/board`,
    `/repo/${U}/graph/extra`,
    "/graph",
  ])("false for %s", (p) => {
    expect(isGraphRoute(p)).toBe(false);
  });
});

describe("isIdScopedRoute", () => {
  it("is true only for /c/:id and /n/:id under a repo", () => {
    expect(isIdScopedRoute(`/repo/${U}/c/3`)).toBe(true);
    expect(isIdScopedRoute(`/repo/${U}/n/3`)).toBe(true);
    expect(isIdScopedRoute(`/repo/${U}/graph`)).toBe(false);
    expect(isIdScopedRoute(`/repo/${U}`)).toBe(false);
    expect(isIdScopedRoute("/c/3")).toBe(false);
  });
});

describe("rescopePath", () => {
  it("keeps the page under the new uuid", () => {
    expect(rescopePath("/repo/a/kb/review", "b")).toBe("/repo/b/kb/review");
    expect(rescopePath("/repo/a", "b")).toBe("/repo/b");
  });
  it("drops repo-specific ids onto the graph", () => {
    expect(rescopePath("/repo/a/c/3", "b")).toBe("/repo/b/graph");
    expect(rescopePath("/repo/a/n/3", "b")).toBe("/repo/b/graph");
  });
  it("sends unscoped paths to the dashboard", () => {
    expect(rescopePath("/graph", "b")).toBe("/repo/b");
    expect(rescopePath("/", "b")).toBe("/repo/b");
  });
});

describe("legacyToScoped", () => {
  it("prefixes and keeps the search string", () => {
    expect(legacyToScoped("/kb", "?sel=3", U)).toBe(`/repo/${U}/kb?sel=3`);
    expect(legacyToScoped("/kb/9/edit", "", U)).toBe(`/repo/${U}/kb/9/edit`);
    expect(legacyToScoped("/c/4", "", U)).toBe(`/repo/${U}/c/4`);
  });
});
