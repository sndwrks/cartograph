import { Items, Prose, type PayloadProps, list, str } from "./helpers";

export default function RunbookPayload({ payload }: PayloadProps) {
  return (
    <>
      <Prose heading="Severity" text={str(payload, "severity")} />
      <Prose heading="Trigger" text={str(payload, "trigger")} />
      <Items heading="Steps" items={list(payload, "steps")} ordered />
      <Prose heading="Verification" text={str(payload, "verification")} />
      <Prose heading="Rollback" text={str(payload, "rollback")} />
    </>
  );
}
