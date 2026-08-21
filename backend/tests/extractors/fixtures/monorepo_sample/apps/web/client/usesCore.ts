import { coreUtil } from "@acme/core";
import { deepThing } from "@acme/core/src/deep";

export function combined(): string {
  deepThing();
  return coreUtil();
}
