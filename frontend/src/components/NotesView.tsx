import { GraphIcon, NoteBlank, Plus } from "@phosphor-icons/react";

import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER, relativeTime } from "../lib/format";
import type { NoteSummary } from "../lib/types";
import { ShareBadge } from "./ShareBadge";
import { EmptyState } from "./ui";

/**
 * Todas as notas que a conta alcança — as dela e as compartilhadas com ela. É a lista principal do
 * app: sem caderno no meio, cada cartão é uma nota com o que ela guarda.
 */
export function NotesView({
  notes,
  onOpenNote,
  onCreateNote,
}: {
  notes: NoteSummary[];
  onOpenNote: (id: number) => void;
  onCreateNote: () => void;
}) {
  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">
          <NoteBlank size={20} weight="bold" />
          Notas
          <span className="pill-count">{notes.length}</span>
        </h1>
        <p className="view-lede">
          Cada nota guarda os seus blocos, as tags e os vínculos — e é ela que se compartilha. Clique
          para abrir; a lista lateral é o caminho curto.
        </p>
      </header>

      {notes.length === 0 ? (
        <EmptyState
          title="Nenhuma nota ainda"
          hint="A nota é a unidade: escreva o nome dela e o primeiro bloco vem junto."
          action={
            <button type="button" className="btn btn-primary" onClick={onCreateNote}>
              <Plus size={15} weight="bold" /> Nova nota
            </button>
          }
        />
      ) : (
        <section className="note-list">
          {notes.map((note) => (
            <article className="note-card" key={note.id}>
              <button type="button" className="note-card-main" onClick={() => onOpenNote(note.id)}>
                <span className="note-card-title">{note.title || "Nota sem título"}</span>
                <span className="note-card-excerpt">{note.excerpt || "— vazia —"}</span>
                <span className="note-card-foot">
                  <span className="note-card-badges">
                    <ShareBadge note={note} />
                    {note.relations_count > 0 && (
                      <span className="tag-chip" title={`${note.relations_count} vínculos`}>
                        <GraphIcon size={11} weight="bold" />
                        {note.relations_count}
                      </span>
                    )}
                  </span>
                  <span className="note-counts">
                    {KIND_ORDER.filter((kind) => note.counts[kind] > 0).map((kind) => {
                      const KindIcon = KIND_ICONS[kind];
                      return (
                        <span className="count-chip" key={kind} title={KIND_LABELS[kind]}>
                          <KindIcon size={12} weight="bold" />
                          {note.counts[kind]}
                        </span>
                      );
                    })}
                    {note.tags.map((tag) => (
                      <span className="tag-chip" key={tag.id}>
                        {tag.name}
                      </span>
                    ))}
                  </span>
                  <span className="note-card-date">{relativeTime(note.updated_at)}</span>
                </span>
              </button>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
