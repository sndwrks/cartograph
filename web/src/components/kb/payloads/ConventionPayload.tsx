import { Chips, Prose, Section, type PayloadProps, list, records, str } from "./helpers";
import styles from "./payload.module.css";

export default function ConventionPayload({ payload }: PayloadProps) {
  const examples = records(payload, "examples");
  return (
    <>
      <Prose heading="Rationale" text={str(payload, "rationale")} />
      <Chips heading="Applies to" items={list(payload, "applies_to")} />
      {examples.length > 0 && (
        <Section heading="Examples">
          {examples.map((example, index) => (
            <div key={index}>
              {str(example, "good") && (
                <pre className={styles.code}>{str(example, "good")}</pre>
              )}
              {str(example, "bad") && (
                <pre className={styles.code}>{str(example, "bad")}</pre>
              )}
              {str(example, "note") && (
                <p className={styles.prose}>{str(example, "note")}</p>
              )}
            </div>
          ))}
        </Section>
      )}
    </>
  );
}
