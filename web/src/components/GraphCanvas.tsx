// The one force-graph instance every view drives with data + style props:
// sizing, layout spacing, fit-once-then-reveal on data change, tooltips, dash
// rendering, labels at zoom thresholds, click handling.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { forceCollide } from "d3-force-3d";

import { useAppStore } from "../store";
import { BACKGROUND_COLOR, LABEL_COLOR } from "../theme";

export interface CanvasNode {
  id: number | string;
  label: string;
  color: string;
  radius: number;
  tooltip?: string;
  haloColor?: string; // subtle community halo (ego view)
  ring?: boolean; // highlight ring (center node)
  phantom?: boolean; // stub-edge marker styling
  x?: number;
  y?: number;
}

export interface CanvasLink {
  source: number | string;
  target: number | string;
  color: string;
  width: number;
  dash: number[];
}

interface GraphCanvasProps {
  nodes: CanvasNode[];
  links: CanvasLink[];
  onNodeClick?: (node: CanvasNode) => void;
  selectedId?: number | string | null; // ringed without disturbing the layout
  labelThreshold?: number; // always label below this node count
}

// A d3-force with the chainable bits we configure. The library's own typings
// erase these down to a bare tick function.
interface TunableForce {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  strength: (value: any) => TunableForce;
  distanceMax: (value: number) => TunableForce;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  distance: (value: any) => TunableForce;
}

interface ForceGraphHandle {
  zoomToFit: (ms?: number, px?: number) => void;
  zoom: (level?: number, ms?: number) => number;
  centerAt: (x?: number, y?: number, ms?: number) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  d3Force: (name: string, force?: any) => TunableForce | undefined;
}

const LABEL_ZOOM = 1.5;
const LABEL_FONT_PX = 11;
const LABEL_MAX_CHARS = 22;
const LABEL_GAP = 6; // clear space between a circle and the text under it
const MAX_LABEL_SPACING = 40; // cap so one long name can't blow the layout apart
const LINK_SLACK = 24; // link length beyond the two collision radii
const FIT_PADDING = 80; // the fit bbox ignores labels, so pad for the text
// A handful of nodes fits at an absurd zoom. Cap it by how large the biggest
// circle is allowed to render rather than by a flat zoom level, so small graphs
// still fill the canvas and dense ones aren't blown up.
const MAX_NODE_SCREEN_RADIUS = 36;
const WARMUP_TICKS = 400; // upper bound; d3AlphaMin ends it around 130
const ALPHA_MIN = 0.05; // lets the engine self-stop instead of running 15s

const EMPTY_GRAPH = { nodes: [] as CanvasNode[], links: [] as CanvasLink[] };

const measureCtx = document.createElement("canvas").getContext("2d");
const displayCache = new Map<string, string>();
const widthCache = new Map<string, number>();

/** Long qualified names would otherwise dominate the collision radii. */
function displayLabel(label: string): string {
  const cached = displayCache.get(label);
  if (cached !== undefined) return cached;
  const text =
    label.length > LABEL_MAX_CHARS
      ? `${label.slice(0, LABEL_MAX_CHARS - 1)}…`
      : label;
  displayCache.set(label, text);
  return text;
}

function labelWidth(text: string): number {
  const cached = widthCache.get(text);
  if (cached !== undefined) return cached;
  let width = text.length * 5.5; // fallback if there is no 2d context
  if (measureCtx) {
    measureCtx.font = `${LABEL_FONT_PX}px sans-serif`;
    width = measureCtx.measureText(text).width;
  }
  widthCache.set(text, width);
  return width;
}

/** Collision radius wide enough that a node's label clears its neighbors. */
function nodeSpacing(node: CanvasNode): number {
  const halfLabel = labelWidth(displayLabel(node.label)) / 2 + 2;
  return Math.max(
    node.radius + LABEL_GAP,
    Math.min(halfLabel, MAX_LABEL_SPACING),
  );
}

/** Link endpoints are ids until the simulation resolves them to node objects. */
function endpointSpacing(endpoint: unknown): number {
  return typeof endpoint === "object" && endpoint !== null
    ? nodeSpacing(endpoint as CanvasNode)
    : LABEL_GAP * 2;
}

export default function GraphCanvas({
  nodes,
  links,
  onNodeClick,
  selectedId = null,
  labelThreshold = 150,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<ForceGraphHandle>(null);
  const focusRequest = useAppStore((state) => state.focusRequest);
  const [size, setSize] = useState({ width: 0, height: 0 });
  // forces have to be installed before any data reaches the simulation, so the
  // instance mounts empty for one commit and picks up the real graph after
  const [armed, setArmed] = useState(false);
  const [ready, setReady] = useState(false);
  const armedRef = useRef(false);
  const fittedRef = useRef<object | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      setSize({ width: rect.width, height: rect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // fresh object identities per data change so the simulation re-heats
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((node) => ({ ...node })),
      links: links.map((link) => ({ ...link })),
    }),
    [nodes, links],
  );
  const renderedData = armed ? graphData : EMPTY_GRAPH;

  // Stock defaults (charge -30, link distance 30, no collision) pack nodes
  // closer than their own radii. Every force here is a pure function of a node,
  // so this runs once, on the ref callback so it lands before any data does,
  // and survives later data swaps.
  const attachGraph = useCallback((graph: ForceGraphHandle | null) => {
    graphRef.current = graph;
    if (!graph || armedRef.current) return;
    armedRef.current = true;
    graph.d3Force("collide", forceCollide<CanvasNode>(nodeSpacing).iterations(2));
    graph
      .d3Force("charge")
      ?.strength((node: CanvasNode) => -30 - nodeSpacing(node) * 3)
      .distanceMax(1500);
    graph
      .d3Force("link")
      ?.distance(
        (link: CanvasLink) =>
          endpointSpacing(link.source) +
          endpointSpacing(link.target) +
          LINK_SLACK,
      );
    setArmed(true);
  }, []);

  useEffect(() => {
    fittedRef.current = null;
    setReady(false);
  }, [renderedData]);

  // The layout is already settled by warmupTicks when this first fires, so one
  // instant fit lands on the final framing — no zoom animation to watch.
  const handleEngineStop = useCallback(() => {
    const graph = graphRef.current;
    if (!graph || renderedData.nodes.length === 0) return;
    if (fittedRef.current === renderedData) return; // a drag settled; keep the view
    fittedRef.current = renderedData;
    const maxRadius = Math.max(
      ...renderedData.nodes.map((node) => node.radius),
      1,
    );
    const maxZoom = MAX_NODE_SCREEN_RADIUS / maxRadius;
    graph.zoomToFit(0, FIT_PADDING);
    if (graph.zoom() > maxZoom) graph.zoom(maxZoom, 0);
    setReady(true);
  }, [renderedData]);

  // panel-driven pan+zoom to a node currently on this canvas
  useEffect(() => {
    if (!focusRequest) return;
    const graph = graphRef.current;
    const node = graphData.nodes.find(
      (candidate) => candidate.id === focusRequest.id,
    );
    if (!graph || !node || node.x === undefined || node.y === undefined) return;
    graph.centerAt(node.x, node.y, 500);
    if (graph.zoom() < 1.5) graph.zoom(1.5, 500);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest]);

  return (
    <div ref={containerRef} className="graph-canvas">
      {size.width > 0 && size.height > 0 && (
        <div className="graph-canvas-fade" data-ready={ready ? "true" : "false"}>
          <ForceGraph2D
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            ref={attachGraph as any}
            width={size.width}
            height={size.height}
            graphData={renderedData}
            backgroundColor="rgba(0,0,0,0)"
            warmupTicks={WARMUP_TICKS}
            d3AlphaMin={ALPHA_MIN}
            onEngineStop={handleEngineStop}
            nodeVal={(node) => ((node as CanvasNode).radius ** 2) / 16}
            nodeLabel={(node) => (node as CanvasNode).tooltip ?? ""}
            nodeCanvasObject={(node, ctx, globalScale) => {
              const datum = node as CanvasNode;
              const x = datum.x ?? 0;
              const y = datum.y ?? 0;
              if (datum.haloColor) {
                ctx.beginPath();
                ctx.arc(x, y, datum.radius + 4, 0, 2 * Math.PI);
                ctx.fillStyle = datum.haloColor;
                ctx.fill();
              }
              ctx.beginPath();
              ctx.arc(x, y, datum.radius, 0, 2 * Math.PI);
              if (datum.phantom) {
                ctx.fillStyle = `${datum.color}22`;
                ctx.fill();
                ctx.setLineDash([2, 2]);
                ctx.lineWidth = 1 / globalScale;
                ctx.strokeStyle = datum.color;
                ctx.stroke();
                ctx.setLineDash([]);
              } else {
                ctx.fillStyle = datum.color;
                ctx.fill();
              }
              if (datum.ring || datum.id === selectedId) {
                ctx.beginPath();
                ctx.arc(x, y, datum.radius + 2.5, 0, 2 * Math.PI);
                ctx.lineWidth = 2 / globalScale;
                ctx.strokeStyle = "#ffffff";
                ctx.stroke();
              }
              const showLabel =
                datum.phantom ||
                nodes.length < labelThreshold ||
                globalScale > LABEL_ZOOM;
              if (showLabel) {
                const fontSize = Math.min(
                  Math.max(LABEL_FONT_PX / globalScale, 2.5),
                  12,
                );
                const text = displayLabel(datum.label);
                const labelY = y + datum.radius + 2;
                ctx.font = `${fontSize}px sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                // knock the text out of whatever it happens to overlap
                ctx.lineWidth = 3 / globalScale;
                ctx.lineJoin = "round";
                ctx.strokeStyle = BACKGROUND_COLOR;
                ctx.strokeText(text, x, labelY);
                ctx.fillStyle = datum.phantom
                  ? `${LABEL_COLOR}99`
                  : LABEL_COLOR;
                ctx.fillText(text, x, labelY);
              }
            }}
            nodePointerAreaPaint={(node, color, ctx) => {
              const datum = node as CanvasNode;
              ctx.beginPath();
              ctx.arc(
                datum.x ?? 0,
                datum.y ?? 0,
                datum.radius + 3,
                0,
                2 * Math.PI,
              );
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkColor={(link) => (link as CanvasLink).color}
            linkWidth={(link) => (link as CanvasLink).width}
            linkLineDash={(link) => {
              const dash = (link as CanvasLink).dash;
              return dash.length > 0 ? dash : null;
            }}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={0.9}
            onNodeClick={(node) => onNodeClick?.(node as CanvasNode)}
          />
        </div>
      )}
    </div>
  );
}
