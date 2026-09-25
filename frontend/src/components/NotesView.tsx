import { NoteBlank } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER, relativeTime } from "../lib/format";
import type { NoteSummary } from "../lib/types";
import { EmptyState, Spinner } from "./ui";

interface NotesViewProps {
  onOpenNote: (noteId: number, notebookId: number) => void;
  onError: (error: unknown) => void;
}

/** Every note of this user, newest edit first: the fast way back into a thought. */
export function NotesView({ onOpenNote, onError }: NotesViewProps) {
  const [notes, setNotes] = useState<NoteSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .listNotes()
      .then((list) => {
        if (!cancelled) setNotes(list);
      })
      .catch((error: unknown) => {
        if (!cancelled) onError(error);
      });
    return () => {
      cancelled = true;
    };
  }, [onError]);

  if (notes === null) return <Spinner label="Carregando notas..." />;

  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">
          <NoteBlank size={20} weight="bold" />
          Notas
          <span className="pill-count">{notes.length}</span>
        </h1>
        <p className="view-lede">
          Todas as notas dos seus cadernos, da mais recente para a mais antiga. Clique para abrir.
        </p>
      </header>

      {notes.length === 0 ? (
        <EmptyState
          title="Nenhuma nota ainda"
          hint="Escreva o nome da nota na barra de um caderno e dê Enter."
        />
      ) : (
        <section className="note-list">
          {notes.map((note) => (
            <article className="note-card" key={note.id}>
              <button
                type="button"
                className="note-card-main"
                onClick={() => onOpenNote(note.id, note.notebook_id)}
              >
                <span className="note-card-title">{note.title || "Nota sem título"}</span>
                <span className="note-card-excerpt">{note.excerpt || "— vazia —"}</span>
                <span className="note-card-foot">
                  <span className="note-card-notebook">{note.notebook_title}</span>
                  <span className="nb-counts">
                    {KIND_ORDER.filter((kind) => note.counts[kind] > 0).map((kind) => {
                      const KindIcon = KIND_ICONS[kind];
                      return (
                        <span className="count-chip" key={kind} title={KIND_LABELS[kind]}>
                          <KindIcon size={12} weight="bold" />
                          {note.counts[kind]}
                        </span>
                      );
                    })}
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
