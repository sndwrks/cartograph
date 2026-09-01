import { useQuery } from "@tanstack/react-query";

import { fetchRepos } from "../api/client";
import type { RepoOut } from "../api/types";

export interface ReposState {
  repos: RepoOut[];
  isPending: boolean;
  isError: boolean;
  error: unknown;
}

/**
 * Registered repositories from the API.
 *
 * `isPending` is exposed alongside the list because `[]` alone cannot tell
 * "still loading" from "nothing registered" — and the two route redirects
 * (`/` → first repo, unknown uuid → not found) must not fire on the former.
 *
 * Registration is rare, so the list is cached hard; RepoNotFound offers an
 * explicit reload for the mid-session case.
 */
export function useRepos(): ReposState {
  const query = useQuery({
    queryKey: ["repos"],
    queryFn: fetchRepos,
    staleTime: Infinity,
  });
  return {
    repos: query.data?.repos ?? [],
    isPending: query.isPending,
    isError: query.isError,
    error: query.error,
  };
}
