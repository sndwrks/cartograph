import { Chips, Items, Prose, type PayloadProps, list, str } from "./helpers";

export default function DecisionPayload({ payload }: PayloadProps) {
  return (
    <>
      <Items
        heading="Status"
        items={[str(payload, "decision_status"), str(payload, "date")].filter(Boolean)}
      />
      <Chips heading="Deciders" items={list(payload, "deciders")} />
      <Prose heading="Context" text={str(payload, "context")} />
      <Prose heading="Consequences" text={str(payload, "consequences")} />
      <Chips heading="Supersedes" items={list(payload, "supersedes")} />
    </>
  );
}
