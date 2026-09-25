import { Note, NoteBlank, Plus, SidebarSimple, Tag as TagIcon } from "@phosphor-icons/react";

import type { View } from "../App";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_ORDER, KIND_LABELS, notebookMatches } from "../lib/format";
import type { NotebookSummary, Stats, TagUsage } from "../lib/types";

interface SidebarProps {
  notebooks: NotebookSummary[];
  tags: TagUsage[];
  stats: Stats | null;
  view: View;
  filter: string;
  onFilter: (value: string) => void;
  onSelectNotebook: (id: number) => void;
  onCreateNotebook: () => void;
  onOpenTag: (name: string) => void;
  onClose: () => void;
}

export function Sidebar({
  notebooks,
  tags,
  stats,
  view,
  filter,
  onFilter,
  onSelectNotebook,
  onCreateNotebook,
  onOpenTag,
  onClose,
}: SidebarProps) {
  const visible = notebooks.filter((notebook) => notebookMatches(notebook, filter));

  const activeId = view.kind === "notebook" || view.kind === "note" ? (view.kind === "notebook" ? view.id : view.notebookId) : null;

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <span className="sidebar-title">Cadernos</span>
        <span className="sidebar-head-actions">
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onCreateNotebook}
            title="Novo caderno"
            aria-label="Novo caderno"
          >
            <Plus size={16} weight="bold" />
          </button>
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onClose}
            title="Esconder a lista de cadernos"
            aria-label="Esconder a lista de cadernos"
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
          aria-label="Filtrar cadernos"
        />
      </div>

      <div className="nb-list">
        {visible.length === 0 && (
          <p className="sidebar-hint">
            {notebooks.length === 0 ? "Nenhum caderno ainda." : "Nada bate com o filtro."}
          </p>
        )}
        {visible.map((notebook) => (
          <button
            type="button"
            key={notebook.id}
            className={notebook.id === activeId ? "nb-item is-active" : "nb-item"}
            onClick={() => onSelectNotebook(notebook.id)}
          >
            <span className="nb-item-head">
              <span className="nb-item-title">{notebook.title}</span>
              <span className="nb-item-notes" title={`${notebook.notes_count} notas`}>
                <NoteBlank size={13} />
                {notebook.notes_count}
              </span>
            </span>
            <span className="nb-counts">
              {KIND_ORDER.map((kind) => {
                const KindIcon = KIND_ICONS[kind];
                const total = notebook.counts[kind];
                return (
                  <span
                    key={kind}
                    className={total > 0 ? "count-chip" : "count-chip is-zero"}
                    title={`${total} ${KIND_LABELS[kind]}`}
                  >
                    <KindIcon size={12} weight="bold" />
                    {total}
                  </span>
                );
              })}
              <span
                className="count-chip is-zero"
                title={`${notebook.relations_count} caderno(s) ligado(s) pelas notas`}
              >
                <Note size={12} weight="bold" />
                {notebook.relations_count}
              </span>
            </span>
            {notebook.tags.length > 0 && (
              <span className="nb-item-tags">
                {notebook.tags.slice(0, 3).map((tag) => (
                  <span className="tag-chip" key={tag.id}>
                    {tag.name}
                  </span>
                ))}
                {notebook.tags.length > 3 && (
                  <span className="tag-chip is-muted">+{notebook.tags.length - 3}</span>
                )}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="sidebar-section">
        <span className="sidebar-title">
          <TagIcon size={13} weight="bold" /> Tags
        </span>
      </div>
      <div className="tag-cloud">
        {tags.length === 0 && <p className="sidebar-hint">Ctrl+Espaço dentro de uma nota cria tags.</p>}
        {tags.map((tag) => (
          <button
            type="button"
            key={tag.id}
            className={tag.name === filter ? "tag-chip is-active" : "tag-chip"}
            onClick={() => onOpenTag(tag.name)}
            title={`${tag.notebooks_count} cadernos · ${tag.notes_count} notas`}
          >
            {tag.name}
            <span className="tag-count">{tag.notebooks_count}</span>
          </button>
        ))}
      </div>

      <div className="sidebar-foot">
        {stats ? (
          <>
            <span>{stats.notebooks} cadernos</span>
            <span>{stats.notes} notas</span>
            <span>{stats.blocks} blocos</span>
          </>
        ) : (
          <span>conectando...</span>
        )}
      </div>
    </aside>
  );
}
