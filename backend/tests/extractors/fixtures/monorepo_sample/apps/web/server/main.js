import { callMethod } from "/imports/api/methods";

export function serve() {
  return callMethod("server");
}
