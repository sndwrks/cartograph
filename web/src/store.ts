// Client/UI state only — server data lives in TanStack Query.

import { create } from "zustand";

import type { Confidence } from "./api/types";

export type ViewState =
  | { mode: "overview" }
  | { mode: "community"; id: number }
  | { mode: "ego"; nodeId: number };

export interface FocusRequest {
  id: number;
  nonce: number; // re-focus works even for the same node
}

interface AppState {
  repo: string | null;
  view: ViewState;
  selectedNodeId: number | null;
  hopDepth: number;
  minConfidence: Confidence | null;
  focusRequest: FocusRequest | null;
  // Whether the ⌘K palette is open. Lives here rather than being sniffed out of
  // the DOM: SidePanel used to probe `document.querySelector(".palette")` to
  // decide whether Esc was the palette's to handle, which breaks silently once
  // CSS Modules hash that class name.
  paletteOpen: boolean;
  setRepo: (repo: string | null) => void;
  setView: (view: ViewState) => void;
  setSelectedNodeId: (id: number | null) => void;
  setPaletteOpen: (open: boolean) => void;
  setHopDepth: (depth: number) => void;
  setMinConfidence: (confidence: Confidence | null) => void;
  requestFocus: (id: number) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // The repo NAME (what every fetcher's `repo=` wants); null until RepoScope
  // resolves the URL's /repo/<uuid> against the /repos list and writes it.
  repo: null,
  view: { mode: "overview" },
  selectedNodeId: null,
  hopDepth: 1,
  minConfidence: null,
  focusRequest: null,
  paletteOpen: false,
  // Idempotent: RepoScope calls this from an effect on every resolve, and a
  // no-op write must not clear the selection — only a real repo change
  // invalidates a selected node id.
  setRepo: (repo) =>
    set((state) => (state.repo === repo ? {} : { repo, selectedNodeId: null })),
  setView: (view) => set({ view }),
  setSelectedNodeId: (id) => set({ selectedNodeId: id }),
  setPaletteOpen: (open) => set({ paletteOpen: open }),
  setHopDepth: (depth) => set({ hopDepth: depth }),
  setMinConfidence: (confidence) => set({ minConfidence: confidence }),
  requestFocus: (id) =>
    set((state) => ({
      focusRequest: { id, nonce: (state.focusRequest?.nonce ?? 0) + 1 },
    })),
}));
