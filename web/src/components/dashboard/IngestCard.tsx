import { useQuery } from "@tanstack/react-query";

import { fetchIngestRun } from "../../api/client";
import type { IngestRunOut } from "../../api/types";
import { formatCompact, formatDuration, relativeTime } from "../../format";
import { useIngestRuns } from "../../hooks/useUsage";
import { Badge, type BadgeVariant } from "../../ui";
import styles from "./dashboard.module.css";

function statusVariant(status: string): BadgeVariant {
  if (status === "succeeded" || status === "success" || status === "ok") return "success";
  if (status === "failed" || status === "error") return "danger";
  if (status === "running") return "info";
  return "default";
}

function duration(run: IngestRunOut): string | null {
  if (!run.finished_at) return null;
  return formatDuration(new Date(run.finished_at).getTime() - new Date(run.started_at).getTime());
}

export default function IngestCard({ repo }: { repo: string }) {
  const runs = useIngestRuns(repo, 1);
  const latest = runs.data?.[0];
  // The list endpoint omits the error text; fetch the single run only when
  // there is one to show.
  const failed = latest?.status === "failed";
  const detail = useQuery({
    queryKey: ["ingest", "run", latest?.id ?? null],
    queryFn: () => fetchIngestRun(latest!.id),
    enabled: failed,
  });
  const stats = Object.entries(latest?.stats ?? {}).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number",
  );

  return (
    <section className={styles.card}>
      <h2 className={styles.sectionHeading}>Last ingest</h2>
      {runs.isPending ? (
        <p className={styles.empty}>Loading…</p>
      ) : !latest ? (
        <p className={styles.empty}>No ingest runs recorded for this repository.</p>
      ) : (
        <dl className={styles.kv}>
          <dt>status</dt>
          <dd>
            <Badge variant={statusVariant(latest.status)}>{latest.status}</Badge>
          </dd>
          <dt>trigger</dt>
          <dd className={styles.mono}>{latest.trigger}</dd>
          <dt>started</dt>
          <dd title={latest.started_at}>{relativeTime(latest.started_at)}</dd>
          {duration(latest) && (
            <>
              <dt>took</dt>
              <dd>{duration(latest)}</dd>
            </>
          )}
          {stats.length > 0 && (
            <>
              <dt>stats</dt>
              <dd className={styles.badges}>
                {stats.map(([key, value]) => (
                  <Badge key={key}>
                    {key} {formatCompact(value)}
                  </Badge>
                ))}
              </dd>
            </>
          )}
          {failed && detail.data?.error && (
            <>
              <dt>error</dt>
              <dd className={styles.mono}>{detail.data.error}</dd>
            </>
          )}
        </dl>
      )}
    </section>
  );
}
