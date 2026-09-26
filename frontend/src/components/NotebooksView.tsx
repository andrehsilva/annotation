import { Notebook as NotebookIcon, Plus } from "@phosphor-icons/react";

import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER, relativeTime } from "../lib/format";
import type { NotebookSummary } from "../lib/types";
import { EmptyState } from "./ui";

/**
 * Todos os cadernos, na mesma ordem da lista lateral. É a lista que o contador **Cadernos** do
 * cabeçalho promete — antes ele abria o primeiro caderno, e o número do contador não batia com
 * nada do que aparecia.
 */
export function NotebooksView({
  notebooks,
  onOpenNotebook,
  onCreateNotebook,
}: {
  notebooks: NotebookSummary[];
  onOpenNotebook: (id: number) => void;
  onCreateNotebook: () => void;
}) {
  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">
          <NotebookIcon size={20} weight="bold" />
          Cadernos
          <span className="pill-count">{notebooks.length}</span>
        </h1>
        <p className="view-lede">
          Tudo o que cada caderno guarda. Clique para abrir — a lista lateral continua sendo o
          caminho curto.
        </p>
      </header>

      {notebooks.length === 0 ? (
        <EmptyState
          title="Nenhum caderno ainda"
          hint="O caderno é a pasta das notas: crie o primeiro e a primeira nota vem junto."
          action={
            <button type="button" className="btn btn-primary" onClick={onCreateNotebook}>
              <Plus size={15} weight="bold" /> Novo caderno
            </button>
          }
        />
      ) : (
        <section className="note-list">
          {notebooks.map((notebook) => (
            <article className="note-card" key={notebook.id}>
              <button
                type="button"
                className="note-card-main"
                onClick={() => onOpenNotebook(notebook.id)}
              >
                <span className="note-card-title">{notebook.title}</span>
                <span className="note-card-excerpt">
                  {notebook.description || "— sem descrição —"}
                </span>
                <span className="note-card-foot">
                  <span className="note-card-notebook">
                    {notebook.notes_count} {notebook.notes_count === 1 ? "nota" : "notas"}
                  </span>
                  <span className="nb-counts">
                    {KIND_ORDER.filter((kind) => notebook.counts[kind] > 0).map((kind) => {
                      const KindIcon = KIND_ICONS[kind];
                      return (
                        <span className="count-chip" key={kind} title={KIND_LABELS[kind]}>
                          <KindIcon size={12} weight="bold" />
                          {notebook.counts[kind]}
                        </span>
                      );
                    })}
                    {notebook.tags.map((tag) => (
                      <span className="tag-chip" key={tag.id}>
                        {tag.name}
                      </span>
                    ))}
                  </span>
                  <span className="note-card-date">{relativeTime(notebook.updated_at)}</span>
                </span>
              </button>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
