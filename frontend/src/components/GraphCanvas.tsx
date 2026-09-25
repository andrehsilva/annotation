import type { NoteSummary, RelationEdge } from "../lib/types";

const WIDTH = 1000;
const HEIGHT = 560;
const CENTER = { x: WIDTH / 2, y: HEIGHT / 2 };
const RADIUS = 190;
/** How far a mention edge bows away from the straight line between two notes. */
const MENTION_BEND = 34;

const COLORS = ["#6ba5f8", "#e0a458", "#7bc47f", "#c98bd8", "#e2837d", "#5fc9c1", "#b8a1e8"];

interface GraphCanvasProps {
  notes: NoteSummary[];
  edges: RelationEdge[];
  activeId: number | null;
  onSelect: (noteId: number, notebookId: number) => void;
}

/** Notes that take part in some link, laid out in a fixed circle: no physics, stable picture. */
export function GraphCanvas({ notes, edges, activeId, onSelect }: GraphCanvasProps) {
  const linked = new Set<number>();
  for (const edge of edges) {
    linked.add(edge.source_id);
    linked.add(edge.target_id);
  }
  const nodes = notes.filter((note) => linked.has(note.id));
  if (nodes.length === 0) {
    return (
      <p className="panel-hint">
        Nenhuma nota ligada ainda: crie uma relação ou cite uma nota com `[[`.
      </p>
    );
  }

  const notebookIds = [...new Set(nodes.map((note) => note.notebook_id))].sort((a, b) => a - b);
  const colorOf = (notebookId: number) => COLORS[notebookIds.indexOf(notebookId) % COLORS.length];
  const placed = new Map(
    nodes.map((note, index) => {
      const angle = (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
      return [
        note.id,
        { note, x: CENTER.x + RADIUS * Math.cos(angle), y: CENTER.y + RADIUS * Math.sin(angle) },
      ];
    }),
  );

  return (
    <div className="graph-shell">
      <svg
        className="graph-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="Grafo de notas"
      >
        {edges.map((edge) => {
          const from = placed.get(edge.source_id);
          const to = placed.get(edge.target_id);
          if (!from || !to) return null;
          if (edge.kind === "relation") {
            return (
              <line
                key={edge.key}
                className="graph-edge"
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
              />
            );
          }
          // A mention bows out, so it never hides under a declared relation on the same pair.
          const dx = to.x - from.x;
          const dy = to.y - from.y;
          const length = Math.hypot(dx, dy) || 1;
          const controlX = (from.x + to.x) / 2 + (-dy / length) * MENTION_BEND;
          const controlY = (from.y + to.y) / 2 + (dx / length) * MENTION_BEND;
          return (
            <path
              key={edge.key}
              className="graph-edge is-mention"
              d={`M ${from.x} ${from.y} Q ${controlX} ${controlY} ${to.x} ${to.y}`}
            />
          );
        })}
        {[...placed.values()].map(({ note, x, y }) => (
          <g
            key={note.id}
            className={note.id === activeId ? "graph-node is-active" : "graph-node"}
            transform={`translate(${x} ${y})`}
            onClick={() => onSelect(note.id, note.notebook_id)}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSelect(note.id, note.notebook_id);
            }}
          >
            <circle r={11} style={{ fill: colorOf(note.notebook_id) }} />
            <text className="graph-node-title" textAnchor="middle" y={28}>
              {note.title.length > 26 ? `${note.title.slice(0, 26)}…` : note.title}
            </text>
          </g>
        ))}
      </svg>

      <p className="panel-hint graph-legend">
        {notebookIds.map((notebookId) => {
          const note = nodes.find((item) => item.notebook_id === notebookId);
          return (
            <span className="graph-legend-item" key={notebookId}>
              <span className="graph-swatch" style={{ background: colorOf(notebookId) }} />
              {note?.notebook_title}
            </span>
          );
        })}
        <span className="graph-legend-item">— relação</span>
        <span className="graph-legend-item">┄ menção</span>
      </p>
    </div>
  );
}
