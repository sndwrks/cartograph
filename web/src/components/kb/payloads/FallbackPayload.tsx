import type { PayloadProps } from "./helpers";
import styles from "./payload.module.css";

/**
 * Every field, as a definition list. This is what a type the SPA has never
 * heard of renders through — which is the whole reason adding a backend type
 * does not require a frontend release. Do not delete it to "clean up".
 */
export default function FallbackPayload({ payload }: PayloadProps) {
  const entries = Object.entries(payload);
  if (entries.length === 0) return null;
  return (
    <div className={styles.section}>
      <p className={styles.unknownNote}>
        No renderer for this entry type yet — showing the raw payload.
      </p>
      <dl className={styles.fields}>
        {entries.map(([key, value]) => (
          <div key={key} style={{ display: "contents" }}>
            <dt>{key}</dt>
            <dd>
              {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
