import { Chips, type PayloadProps, list } from "./helpers";

/** The reference model's synonym control: the words this project gave up. */
export default function GlossaryPayload({ payload }: PayloadProps) {
  return <Chips heading="Avoid" items={list(payload, "avoid")} />;
}
