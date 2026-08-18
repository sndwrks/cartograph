import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { KbEntryOut } from "../../api/types";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
  Textarea,
} from "../../ui";
import KbTypeBadge from "./KbTypeBadge";
import styles from "./ProposalCard.module.css";

interface Props {
  proposal: KbEntryOut;
  /** The live entry this proposal would replace, if there is one. */
  incumbent: KbEntryOut | null;
  onPublish: (replacesId: number | null) => void;
  onReject: (reason: string) => void;
  busy: boolean;
  error: string | null;
}

function age(iso: string): string {
  const minutes = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / (60 * 24))}d ago`;
}

export default function ProposalCard({
  proposal,
  incumbent,
  onPublish,
  onReject,
  busy,
  error,
}: Props) {
  const navigate = useNavigate();
  const [reason, setReason] = useState("");

  return (
    <article className={styles.card}>
      <header className={styles.header}>
        <KbTypeBadge type={proposal.type} />
        <span className={styles.slug}>{proposal.slug}</span>
        <span className={styles.by}>{proposal.created_by ?? "unknown"}</span>
        <span className={styles.age}>{age(proposal.created_at)}</span>
      </header>

      <h2 className={styles.title}>{proposal.title}</h2>

      {incumbent ? (
        <div className={styles.sideBySide}>
          <section>
            <h3 className={styles.columnHeading}>Published</h3>
            <pre className={styles.body}>{incumbent.body}</pre>
          </section>
          <section>
            <h3 className={styles.columnHeading}>Proposed</h3>
            <pre className={styles.body}>{proposal.body}</pre>
          </section>
        </div>
      ) : (
        <pre className={styles.body}>{proposal.body}</pre>
      )}

      {Object.keys(proposal.payload).length > 0 && (
        <pre className={styles.payload}>
          {JSON.stringify(proposal.payload, null, 2)}
        </pre>
      )}

      {error && <p className={styles.error}>{error}</p>}

      <footer className={styles.actions}>
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => onPublish(incumbent ? incumbent.id : null)}
        >
          {incumbent ? "Publish, replacing" : "Publish"}
        </Button>
        {/* The common case, and it has to be one click — the alternative is a
            human publishing something almost-right. */}
        <Button
          disabled={busy}
          onClick={() => navigate(`/kb/${proposal.id}/edit`)}
        >
          Edit &amp; publish
        </Button>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="danger" disabled={busy}>
              Reject
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogTitle>Reject “{proposal.title}”</DialogTitle>
            <DialogDescription>
              The reason is kept forever, and an agent that re-proposes this slug
              gets it back. It is the only way your judgment reaches a later
              session.
            </DialogDescription>
            <Textarea
              className={styles.reason}
              aria-label="rejection reason"
              placeholder="why this is not knowledge-base material…"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <Button
              variant="danger"
              disabled={!reason.trim() || busy}
              onClick={() => onReject(reason.trim())}
            >
              Reject
            </Button>
          </DialogContent>
        </Dialog>
      </footer>
    </article>
  );
}
