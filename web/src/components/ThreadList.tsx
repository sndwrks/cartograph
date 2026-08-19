import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  deleteMessage,
  fetchAgents,
  fetchNode,
  fetchThread,
  fetchThreads,
} from "../api/client";
import type { MessageOut, ThreadRootOut } from "../api/types";
import { Button, cx } from "../ui";
import { Close } from "./icons";
import styles from "./ThreadList.module.css";

// Every board query key is prefixed ["messages", …], so one invalidate after a
// delete refreshes the thread list and any expanded thread's replies — same
// precedent as the KB's ["kb", …] prefix (KbEntryDetail.tsx).
function invalidateMessages(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["messages"] });
}

/** Delete button + native confirm() for one message row. Owns its own mutation
 *  so an error or pending state on one row never affects its siblings. */
function DeleteMessageButton({
  messageId,
  confirmText,
  title,
}: {
  messageId: number;
  confirmText: string;
  title: string;
}) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: deleteMessage,
    onSuccess: () => invalidateMessages(queryClient),
  });
  return (
    <div className={styles.deleteCell}>
      <Button
        variant="danger"
        size="iconSm"
        title={title}
        aria-label={title}
        disabled={remove.isPending}
        onClick={() => {
          if (confirm(confirmText)) remove.mutate(messageId);
        }}
      >
        <Close />
      </Button>
      {remove.isError && <p className={styles.error}>{String(remove.error)}</p>}
    </div>
  );
}

// Never a fixed string: the confirm must show what actually goes with the
// root — a cascading delete (thread_id is ondelete CASCADE) with no warning
// of the blast radius is how a human loses replies by accident.
function rootConfirmText(subject: string | null, replyCount: number): string {
  const label = subject ? `“${subject}”` : "this thread";
  if (replyCount === 0) return `Delete ${label}? This cannot be undone.`;
  return `Delete ${label} and its ${replyCount} repl${replyCount === 1 ? "y" : "ies"}? This cannot be undone.`;
}

function relativeTime(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function Message({
  message,
  agentName,
}: {
  message: MessageOut;
  agentName: string;
}) {
  return (
    <div className={styles.message}>
      <div className={styles.meta}>
        <span className={styles.agent}>{agentName}</span>
        <span className="muted">{relativeTime(message.created_at)}</span>
      </div>
      {message.subject && (
        <div className={styles.subject}>{message.subject}</div>
      )}
      <div className={styles.body}>{message.body}</div>
    </div>
  );
}

function Thread({
  rootId,
  agentNames,
}: {
  rootId: number;
  agentNames: Map<number, string>;
}) {
  const query = useQuery({
    queryKey: ["messages", "thread", rootId],
    queryFn: () => fetchThread(rootId),
    staleTime: 30_000,
  });
  if (query.isPending) return <p className="muted">Loading thread…</p>;
  if (query.isError) return <p className="muted">Failed to load thread.</p>;
  // list_thread returns [root, ...replies] — the root is already shown (with
  // its own cascade-aware delete button) in the collapsed row above, so only
  // the true replies get a delete affordance here. Giving the duplicated root
  // the singular "delete this reply" wording would understate what its
  // ondelete="CASCADE" actually does.
  const replies = query.data.messages.filter((message) => message.id !== rootId);
  return (
    <div className={styles.thread}>
      {replies.map((message) => (
        <div key={message.id} className={styles.messageRow}>
          <Message
            message={message}
            agentName={agentNames.get(message.agent_id) ?? `#${message.agent_id}`}
          />
          <DeleteMessageButton
            messageId={message.id}
            confirmText="Delete this reply? This cannot be undone."
            title="Delete reply"
          />
        </div>
      ))}
    </div>
  );
}

export default function ThreadList({
  nodeId,
  agentId,
  repo,
}: {
  nodeId?: number;
  agentId?: number;
  /** Scope to one repository. Only meaningful without `nodeId` — a node already
   *  belongs to exactly one repo, so the side-panel case needs no filter. */
  repo?: string;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const threads = useQuery({
    queryKey: ["messages", "threads", nodeId ?? null, agentId ?? null, repo ?? null],
    queryFn: () => fetchThreads({ nodeId, agentId, repo }),
    staleTime: 30_000,
  });
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
    staleTime: 60_000,
  });
  const agentNames = new Map(
    (agents.data?.agents ?? []).map((agent) => [agent.id, agent.name]),
  );

  const roots: ThreadRootOut[] = threads.data?.threads ?? [];

  // On the board page (nodeId undefined) each root can be anchored to a
  // different node, so resolve qualified names client-side. Skipped in the
  // side-panel case, where every thread is already anchored to the node
  // being viewed and the label would be noise. Query key matches NodeDetail's
  // ("node-detail", id) so the cache is shared and the click-through is instant.
  const anchoredNodeIds =
    nodeId === undefined
      ? Array.from(
          new Set(
            roots
              .map(({ message }) => message.node_id)
              .filter((id): id is number => id !== null),
          ),
        )
      : [];
  const nodeQueries = useQueries({
    queries: anchoredNodeIds.map((id) => ({
      queryKey: ["node-detail", id],
      queryFn: () => fetchNode(id),
      staleTime: 30_000,
    })),
  });
  const anchorNames = new Map(
    anchoredNodeIds.map((id, index) => [
      id,
      nodeQueries[index]?.data?.node.qualified_name,
    ]),
  );

  if (threads.isPending) return <p className="muted">Loading…</p>;
  if (threads.isError) return <p className="muted">Failed to load discussion.</p>;
  if (roots.length === 0) {
    return (
      <p className="muted">
        {nodeId === undefined
          ? "No discussion yet. Agents post to the board via MCP."
          : "No discussion. Agents can anchor threads here via MCP."}
      </p>
    );
  }

  return (
    <ul className={styles.threads}>
      {roots.map(({ message, reply_count }) => (
        <li key={message.id}>
          {nodeId === undefined && message.node_id !== null && (
            <Link to={`/n/${message.node_id}`} className={styles.anchor}>
              {anchorNames.get(message.node_id) ?? `#${message.node_id}`}
            </Link>
          )}
          <div className={styles.rootRow}>
            <button
              type="button"
              className={styles.root}
              onClick={() =>
                setExpanded(expanded === message.id ? null : message.id)
              }
            >
              <Message
                message={message}
                agentName={
                  agentNames.get(message.agent_id) ?? `#${message.agent_id}`
                }
              />
              <span className={cx(styles.replies, "muted")}>
                {reply_count} repl{reply_count === 1 ? "y" : "ies"}
                {expanded === message.id ? " ▾" : " ▸"}
              </span>
            </button>
            <DeleteMessageButton
              messageId={message.id}
              confirmText={rootConfirmText(message.subject, reply_count)}
              title="Delete thread"
            />
          </div>
          {expanded === message.id && (
            <Thread rootId={message.id} agentNames={agentNames} />
          )}
        </li>
      ))}
    </ul>
  );
}
