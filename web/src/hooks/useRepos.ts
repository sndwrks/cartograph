import { useQuery } from "@tanstack/react-query";

import { fetchRepos } from "../api/client";

/**
 * Registered repository names from the API, [] until loaded.
 *
 * Registration is rare, so the list is cached hard; a new repo shows up on
 * the next full page load rather than mid-session.
 */
export function useRepos(): string[] {
  const query = useQuery({
    queryKey: ["repos"],
    queryFn: fetchRepos,
    staleTime: Infinity,
  });
  return query.data?.repos ?? [];
}
