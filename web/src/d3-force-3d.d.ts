// d3-force-3d ships no types. force-graph builds its simulation from this exact
// module (force-graph.mjs: forceSimulation().force('link', ...)), so a force
// created here is the one the layout expects. Only forceCollide is declared —
// the rest of the simulation is reached through ForceGraph2D's d3Force().

declare module "d3-force-3d" {
  export interface CollideForce<T> {
    (alpha: number): void;
    radius(radius: (node: T) => number): CollideForce<T>;
    strength(strength: number): CollideForce<T>;
    iterations(iterations: number): CollideForce<T>;
  }
  export function forceCollide<T>(radius: (node: T) => number): CollideForce<T>;
}
