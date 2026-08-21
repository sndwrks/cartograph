import { callMethod } from "@api/methods";
import { userAtom } from "@recoil/atoms";

export function Page(): number {
  userAtom();
  return callMethod("page");
}
