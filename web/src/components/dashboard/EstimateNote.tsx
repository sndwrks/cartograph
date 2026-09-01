import styles from "./dashboard.module.css";

export default function EstimateNote({ charsPerToken }: { charsPerToken: number }) {
  return (
    <p className={styles.note}>
      Token figures are estimates: bytes ÷ {charsPerToken} ≈ tokens. “Reading files”
      is the size of the source files an agent would otherwise have had to open to get
      the same answer (search results, a node and its callers, a neighbourhood, an
      impact set) — capped per file, and the same file can count across calls. “Saved”
      is that baseline minus what the tool actually returned, over the calls that have
      a baseline. Knowledge-base and board tools have no file baseline and are left out
      of the ratio. Timings are server-side. The number that settles the question is an
      A/B of the same task with and without the server — this page is the proxy.
    </p>
  );
}
