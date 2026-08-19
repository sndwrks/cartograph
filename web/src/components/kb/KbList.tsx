import type { KbEntryOut } from "../../api/types";
import { cx } from "../../ui";
import KbTypeBadge from "./KbTypeBadge";
import styles from "./KbList.module.css";

interface Props {
  entries: KbEntryOut[];
  selectedId: number | null;
  onSelect: (entry: KbEntryOut) => void;
  /** Group under type headings — only useful when the type filter is "all". */
  grouped: boolean;
}

function Row({
  entry,
  selected,
  onSelect,
  showType,
}: {
  entry: KbEntryOut;
  selected: boolean;
  onSelect: (entry: KbEntryOut) => void;
  showType: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        className={cx(styles.row, selected && styles.selected)}
        aria-current={selected ? "true" : undefined}
        onClick={() => onSelect(entry)}
      >
        {showType && <KbTypeBadge type={entry.type} />}
        <span className={styles.title}>{entry.title}</span>
        <span className={styles.slug}>{entry.slug}</span>
      </button>
    </li>
  );
}

export default function KbList({ entries, selectedId, onSelect, grouped }: Props) {
  if (entries.length === 0) {
    return <p className={styles.empty}>No entries.</p>;
  }

  if (!grouped) {
    return (
      <ul className={styles.list}>
        {entries.map((entry) => (
          <Row
            key={entry.id}
            entry={entry}
            selected={entry.id === selectedId}
            onSelect={onSelect}
            showType={false}
          />
        ))}
      </ul>
    );
  }

  // The API already orders by type precedence then title, so grouping is a
  // single pass and never re-sorts.
  const groups: { type: string; entries: KbEntryOut[] }[] = [];
  for (const entry of entries) {
    const last = groups.at(-1);
    if (last && last.type === entry.type) last.entries.push(entry);
    else groups.push({ type: entry.type, entries: [entry] });
  }

  return (
    <>
      {groups.map((group) => (
        <section key={group.type} className={styles.group}>
          <h2 className={styles.groupHeading}>
            <KbTypeBadge type={group.type} />
            <span className={styles.count}>{group.entries.length}</span>
          </h2>
          <ul className={styles.list}>
            {group.entries.map((entry) => (
              <Row
                key={entry.id}
                entry={entry}
                selected={entry.id === selectedId}
                onSelect={onSelect}
                showType={false}
              />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
