import { describe, expect, it } from "vitest";

import { ApiError } from "./client";

/**
 * These guard the fix for 422s rendering as "[object Object]".
 *
 * FastAPI sends `detail` as a STRING for errors the routers raise by hand and
 * as an ARRAY of {loc, msg} for request validation — and the KB editor hits the
 * array form on every malformed payload. Typing it as a string put
 * "[object Object]" in front of the human instead of the problem.
 */
describe("ApiError", () => {
  it("keeps a hand-raised string detail readable", () => {
    const error = new ApiError(409, "already exists: PSN", "already exists: PSN");
    expect(error.message).toBe("already exists: PSN");
    expect(error.fieldErrors()).toBeNull();
  });

  it("summarizes a 422 detail array instead of stringifying objects", () => {
    const detail = [
      { loc: ["body", "title"], msg: "Field required", type: "missing" },
    ];
    const error = new ApiError(422, "body.title: Field required", detail);
    expect(error.message).not.toContain("[object Object]");
    expect(error.fieldErrors()).toEqual({ title: "Field required" });
  });

  it("strips only a real FastAPI scope prefix from loc", () => {
    // request validation: loc[0] is the scope and must go
    expect(
      new ApiError(422, "", [
        { loc: ["body", "payload", "avoid"], msg: "bad" },
      ]).fieldErrors(),
    ).toEqual({ "payload.avoid": "bad" });

    // a payload rejected by its KB type has NO scope prefix — dropping loc[0]
    // unconditionally turned this into a useless "request"
    expect(
      new ApiError(422, "", [
        { loc: ["decision_status"], msg: "Input should be 'accepted'" },
      ]).fieldErrors(),
    ).toEqual({ decision_status: "Input should be 'accepted'" });
  });

  it("falls back to 'request' when loc carries no field", () => {
    expect(
      new ApiError(422, "", [{ loc: ["body"], msg: "bad" }]).fieldErrors(),
    ).toEqual({ request: "bad" });
  });

  it("returns null for shapes that are not field errors", () => {
    expect(new ApiError(500, "boom").fieldErrors()).toBeNull();
    expect(new ApiError(422, "x", { nope: 1 }).fieldErrors()).toBeNull();
  });
});
