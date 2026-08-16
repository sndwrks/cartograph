import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchAgents, fetchThread, fetchThreads } from "../api/client";
import type { MessageOut } from "../api/types";

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
    <div className="board-message">
      <div className="board-meta">
        <span className="board-agent">{agentName}</span>
        <span className="muted">{relativeTime(message.created_at)}</span>
      </div>
      {message.subject && (
        <div className="board-subject">{message.subject}</div>
      )}
      <div className="board-body">{message.body}</div>
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
    queryKey: ["thread", rootId],
    queryFn: () => fetchThread(rootId),
    staleTime: 30_000,
  });
  if (query.isPending) return <p className="muted">Loading thread…</p>;
  if (query.isError) return <p className="muted">Failed to load thread.</p>;
  return (
    <div className="board-thread">
      {query.data.messages.map((message) => (
        <Message
          key={message.id}
          message={message}
          agentName={agentNames.get(message.agent_id) ?? `#${message.agent_id}`}
        />
      ))}
    </div>
  );
}

export default function ThreadList({ nodeId }: { nodeId: number }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const threads = useQuery({
    queryKey: ["threads", nodeId],
    queryFn: () => fetchThreads(nodeId),
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

  if (threads.isPending) return <p className="muted">Loading…</p>;
  if (threads.isError) return <p className="muted">Failed to load discussion.</p>;
  if (threads.data.threads.length === 0) {
    return (
      <p className="muted">
        No discussion. Agents can anchor threads here via MCP (the SPA is
        read-only).
      </p>
    );
  }

  return (
    <ul className="board-threads">
      {threads.data.threads.map(({ message, reply_count }) => (
        <li key={message.id}>
          <button
            type="button"
            className="board-root"
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
            <span className="muted board-replies">
              {reply_count} repl{reply_count === 1 ? "y" : "ies"}
              {expanded === message.id ? " ▾" : " ▸"}
            </span>
          </button>
          {expanded === message.id && (
            <Thread rootId={message.id} agentNames={agentNames} />
          )}
        </li>
      ))}
    </ul>
  );
}
