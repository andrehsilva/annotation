import { GraphIcon, Plus, SidebarSimple } from "@phosphor-icons/react";

import type { View } from "../App";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_ORDER, KIND_LABELS, noteMatches } from "../lib/format";
import type { NoteSummary, Stats } from "../lib/types";
import { ShareBadge } from "./ShareBadge";

interface SidebarProps {
  notes: NoteSummary[];
  stats: Stats | null;
  view: View;
  filter: string;
  onFilter: (value: string) => void;
  onSelectNote: (id: number) => void;
  onCreateNote: () => void;
  onClose: () => void;
}

/**
 * A lista lateral: **as notas**, não mais cadernos.
 *
 * A nota é a unidade do app, então é ela que a barra lista e filtra (título, trecho ou tag). Os
 * contadores por tipo continuam ali para mostrar o que cada nota guarda.
 */
export function Sidebar({
  notes,
  stats,
  view,
  filter,
  onFilter,
  onSelectNote,
  onCreateNote,
  onClose,
}: SidebarProps) {
  const visible = notes.filter((note) => noteMatches(note, filter));
  const activeId = view.kind === "note" ? view.id : null;

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <span className="sidebar-title">Notas</span>
        <span className="sidebar-head-actions">
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onCreateNote}
            title="Nova nota"
            aria-label="Nova nota"
          >
            <Plus size={16} weight="bold" />
          </button>
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onClose}
            title="Esconder a lista de notas"
            aria-label="Esconder a lista de notas"
          >
            <SidebarSimple size={16} weight="bold" />
          </button>
        </span>
      </div>

      <div className="sidebar-filter">
        <input
          className="input"
          value={filter}
          onChange={(event) => onFilter(event.target.value)}
          placeholder="Filtrar..."
          aria-label="Filtrar notas"
        />
      </div>

      <div className="side-note-list">
        {visible.length === 0 && (
          <p className="sidebar-hint">
            {notes.length === 0 ? "Nenhuma nota ainda." : "Nada bate com o filtro."}
          </p>
        )}
        {visible.map((note) => (
          <button
            type="button"
            key={note.id}
            className={note.id === activeId ? "side-note is-active" : "side-note"}
            onClick={() => onSelectNote(note.id)}
          >
            <span className="side-note-head">
              <span className="side-note-title">{note.title || "Nota sem título"}</span>
              <ShareBadge note={note} compact />
            </span>
            <span className="note-counts">
              {/* Só o que existe: tipo com zero não entra, e nota sem bloco nenhum não tem linha. */}
              {KIND_ORDER.filter((kind) => note.counts[kind] > 0).map((kind) => {
                const KindIcon = KIND_ICONS[kind];
                return (
                  <span
                    key={kind}
                    className="count-chip"
                    title={`${note.counts[kind]} ${KIND_LABELS[kind]}`}
                  >
                    <KindIcon size={12} weight="bold" />
                    {note.counts[kind]}
                  </span>
                );
              })}
              {note.relations_count > 0 && (
                <span className="count-chip" title={`${note.relations_count} vínculos`}>
                  <GraphIcon size={12} weight="bold" />
                  {note.relations_count}
                </span>
              )}
            </span>
          </button>
        ))}
      </div>

      <div className="sidebar-foot">
        <span>
          {stats
            ? `${stats.notes} nota${stats.notes === 1 ? "" : "s"} · ${stats.blocks} bloco${
                stats.blocks === 1 ? "" : "s"
              } · ${stats.tags} tag${stats.tags === 1 ? "" : "s"}`
            : ""}
        </span>
        {/* Crédito, em letra miúda: o app é caseiro e o dono é rastreável por aqui. */}
        <span className="sidebar-credit">
          criado por{" "}
          <a href="https://github.com/andrehsilva" target="_blank" rel="noreferrer">
            github.com/andrehsilva
          </a>{" "}
          ·{" "}
          <a href="https://sacadaweb.com.br" target="_blank" rel="noreferrer">
            sacadaweb.com.br
          </a>
        </span>
      </div>
    </aside>
  );
}
