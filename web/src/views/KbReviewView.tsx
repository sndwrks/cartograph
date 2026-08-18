import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, fetchKbEntries, publishKbEntry, rejectKbEntry } from "../api/client";
import ProposalCard from "../components/kb/ProposalCard";
import type { KbEntryOut } from "../api/types";
import { useAppStore } from "../store";
import { Button } from "../ui";
import styles from "./KbReviewView.module.css";
import viewFrameStyles from "./viewFrame.module.css";

const PROPOSAL_LIMIT = 100;
const PUBLISHED_LIMIT = 500; // the API maximum

/**
 * The live entry a proposal would replace.
 *
 * Matched on title OR slug, case-insensitively, because that is exactly what
 * the server's collision check does. Matching on slug alone left a
 * title-only collision looking new: the card offered "Publish", passed
 * replaces_id=null, and the server 409'd with no control able to supply one.
 */
function findIncumbent(live: KbEntryOut[], proposal: KbEntryOut): KbEntryOut | null {
  const slug = proposal.slug.toLowerCase();
  const title = proposal.title.toLowerCase();
  return (
    live.find(
      (entry) =>
        entry.type === proposal.type &&
        entry.id !== proposal.id &&
        (entry.slug.toLowerCase() === slug || entry.title.toLowerCase() === title),
    ) ?? null
  );
}

export default function KbReviewView() {
  const repo = useAppStore((state) => state.repo);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [errors, setErrors] = useState<Record<number, string>>({});

  const proposals = useQuery({
    // `limit` is part of the key. KbView asks the same question with limit:1
    // for its badge count; sharing a key meant this page rendered ONE card out
    // of N for the whole staleTime window.
    queryKey: ["kb", "entries", { status: "proposed", repo, limit: PROPOSAL_LIMIT }],
    queryFn: () =>
      fetchKbEntries({
        status: "proposed",
        repo: repo ?? undefined,
        limit: PROPOSAL_LIMIT,
      }),
  });

  // Published entries, so a proposal that shadows one can be shown side by side
  // and published with `replaces_id` in a single call.
  const published = useQuery({
    queryKey: ["kb", "entries", { status: "published", repo, limit: PUBLISHED_LIMIT }],
    queryFn: () =>
      fetchKbEntries({
        status: "published",
        repo: repo ?? undefined,
        limit: PUBLISHED_LIMIT,
      }),
  });

  // The app's first useMutation: every KB query key is prefixed ["kb", …], so
  // one invalidate refreshes the list, the detail, and the header's count.
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["kb"] });

  const onError = (id: number) => (error: unknown) =>
    setErrors((prev) => ({
      ...prev,
      [id]: error instanceof ApiError ? error.message : String(error),
    }));

  const publish = useMutation({
    mutationFn: ({ id, replacesId }: { id: number; replacesId: number | null }) =>
      publishKbEntry(id, replacesId),
    onSuccess: invalidate,
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      rejectKbEntry(id, reason),
    onSuccess: invalidate,
  });

  const rows = proposals.data?.entries ?? [];
  const live = published.data?.entries ?? [];
  // The incumbent index is capped at the server maximum. Past it a proposal
  // that revises a live entry would look new, publish with replaces_id=null,
  // and 409 with nothing in the UI able to fix it — so say so out loud.
  const incumbentsClipped = (published.data?.total ?? 0) > live.length;

  return (
    <div className={styles.review}>
      <div className={styles.header}>
        <h1 className={styles.title}>Proposals</h1>
        <Button variant="ghost" onClick={() => navigate("/kb")}>
          Back to knowledge base
        </Button>
      </div>

      <div className={styles.body}>
        {proposals.isPending ? (
          <div className={viewFrameStyles.canvasMessage}>Loading…</div>
        ) : proposals.isError ? (
          <div className={viewFrameStyles.canvasMessage}>
            Failed to load proposals: {String(proposals.error)}
          </div>
        ) : rows.length === 0 ? (
          <div className={viewFrameStyles.canvasMessage}>
            Nothing waiting. An empty queue is the healthy state — agents are
            told to propose almost never.
          </div>
        ) : (
          <>
          {incumbentsClipped && (
            <p className={styles.notice}>
              More than {PUBLISHED_LIMIT} published entries — the “replaces”
              match below may be incomplete.
            </p>
          )}
          {rows.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              incumbent={findIncumbent(live, proposal)}
              busy={publish.isPending || reject.isPending}
              error={errors[proposal.id] ?? null}
              onPublish={(replacesId) =>
                publish.mutate(
                  { id: proposal.id, replacesId },
                  { onError: onError(proposal.id) },
                )
              }
              onReject={(reason) =>
                reject.mutate(
                  { id: proposal.id, reason },
                  { onError: onError(proposal.id) },
                )
              }
            />
          ))}
          </>
        )}
      </div>
    </div>
  );
}
