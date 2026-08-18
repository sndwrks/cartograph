import { Chips, Items, Prose, type PayloadProps, list, str } from "./helpers";

export default function SpecificationPayload({ payload }: PayloadProps) {
  return (
    <>
      <Prose heading="Summary" text={str(payload, "summary")} />
      <Prose heading="Owner" text={str(payload, "owner")} />
      <Items heading="Requirements" items={list(payload, "requirements")} ordered />
      {/* qualified names, a soft link to the graph — not an FK */}
      <Chips heading="Related code" items={list(payload, "related_nodes")} />
    </>
  );
}
