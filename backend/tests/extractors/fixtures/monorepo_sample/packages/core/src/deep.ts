import { callMethod } from "@api/methods";

export function deepThing(): number {
  // @api/... is governed by apps/web's tsconfig, not visible from here
  return callMethod("deep");
}
