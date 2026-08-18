import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchAgents } from "../api/client";
import ThreadList from "../components/ThreadList";
import { useAppStore } from "../store";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui";
import viewFrameStyles from "./viewFrame.module.css";
import styles from "./BoardView.module.css";

// Radix Select.Item rejects an empty-string value (reserved to mean "no
// selection"), so the "all agents" option round-trips through this sentinel
// instead of "" — same precedent as EgoView's confidence filter.
const ANY_AGENT_VALUE = "any";

export default function BoardView() {
  const repo = useAppStore((state) => state.repo);
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
    staleTime: 60_000,
  });
  const [agentId, setAgentId] = useState<number | undefined>(undefined);

  return (
    <div className={styles.board}>
      <div className={styles.header}>
        <h1 className={styles.title}>Board</h1>
        <label className={styles.filter}>
          agent
          <Select
            value={agentId === undefined ? ANY_AGENT_VALUE : String(agentId)}
            onValueChange={(value) =>
              setAgentId(value === ANY_AGENT_VALUE ? undefined : Number(value))
            }
          >
            <SelectTrigger aria-label="agent">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY_AGENT_VALUE}>all agents</SelectItem>
              {(agents.data?.agents ?? []).map((agent) => (
                <SelectItem key={agent.id} value={String(agent.id)}>
                  {agent.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>
      <div className={styles.body}>
        {agents.isPending ? (
          <div className={viewFrameStyles.canvasMessage}>Loading…</div>
        ) : agents.isError ? (
          <div className={viewFrameStyles.canvasMessage}>
            Failed to load agents: {String(agents.error)}
          </div>
        ) : (
          <ThreadList agentId={agentId} repo={repo ?? undefined} />
        )}
      </div>
    </div>
  );
}
