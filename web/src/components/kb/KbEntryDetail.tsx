import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { archiveKbEntry, deleteKbEntry } from "../../api/client";
import type { KbEntryOut } from "../../api/types";
import { Badge, Button } from "../../ui";
import KbStatusBadge from "./KbStatusBadge";
import KbTypeBadge from "./KbTypeBadge";
import { payloadRenderer } from "./payloads";
import styles from "./KbEntryDetail.module.css";

export default function KbEntryDetail({ entry }: { entry: KbEntryOut | null }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Every KB key is prefixed ["kb", …], so one invalidate covers the list, the
  // detail and the header count.
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["kb"] });
  const archive = useMutation({ mutationFn: archiveKbEntry, onSuccess: invalidate });
  const remove = useMutation({
    mutationFn: deleteKbEntry,
    onSuccess: () => {
      invalidate();
      navigate("/kb");
    },
  });

  if (entry === null) {
    return <p className={styles.empty}>Select an entry.</p>;
  }

  const Payload = payloadRenderer(entry.type);

  return (
    <article className={styles.detail}>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <KbTypeBadge type={entry.type} />
          <h2 className={styles.title}>{entry.title}</h2>
          {entry.seq !== null && (
            <span className={styles.seq}>#{String(entry.seq).padStart(4, "0")}</span>
          )}
          <KbStatusBadge status={entry.status} />
        </div>
        <div className={styles.actions}>
          {/* Button is a plain <button>, not a Radix Slot — it has no asChild,
              so navigation goes through the router hook rather than a nested
              <Link>. */}
          <Button variant="ghost" onClick={() => navigate(`/kb/${entry.id}/edit`)}>
            Edit
          </Button>
          {/* Archiving is the only way back from a published entry, and until
              this existed the `archived` status was unreachable from the UI —
              so the badge that renders it could never have been seen. */}
          {entry.status === "published" && (
            <Button
              variant="ghost"
              disabled={archive.isPending}
              onClick={() => archive.mutate(entry.id)}
            >
              Archive
            </Button>
          )}
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={() => {
              if (confirm(`Delete “${entry.title}” permanently?`)) {
                remove.mutate(entry.id);
              }
            }}
          >
            Delete
          </Button>
        </div>
      </header>

      <dl className={styles.meta}>
        <dt>slug</dt>
        <dd className={styles.mono}>{entry.slug}</dd>
        <dt>scope</dt>
        <dd>{entry.repository ?? "global"}</dd>
        <dt>updated</dt>
        <dd>{new Date(entry.updated_at).toLocaleString()}</dd>
        {entry.created_by && (
          <>
            <dt>by</dt>
            <dd className={styles.mono}>{entry.created_by}</dd>
          </>
        )}
      </dl>

      {/* Not a markdown renderer — pre-wrap keeps the author's line breaks
          without pulling in a parser the rest of the app does not have. */}
      <pre className={styles.body}>{entry.body}</pre>

      {entry.aliases && entry.aliases.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.heading}>Aliases</h3>
          <div className={styles.chips}>
            {entry.aliases.map((alias) => (
              <Badge key={alias}>{alias}</Badge>
            ))}
          </div>
        </section>
      )}

      <Payload payload={entry.payload} />

      {(archive.isError || remove.isError) && (
        <p className={styles.error}>
          {String(archive.error ?? remove.error)}
        </p>
      )}

      {entry.review_note && (
        <section className={styles.section}>
          <h3 className={styles.heading}>Review note</h3>
          <p className={styles.note}>{entry.review_note}</p>
        </section>
      )}
    </article>
  );
}
