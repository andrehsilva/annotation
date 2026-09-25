import { LinkSimple, Plus, Trash } from "@phosphor-icons/react";

import type { NoteRelated } from "../lib/types";

interface NoteLinksProps {
  related: NoteRelated;
  onOpenNote: (noteId: number, notebookId: number) => void;
  onRelate: () => void;
  onRemoveRelation: (relationId: number) => void;
}

/** Footer of the editor: what this note declares, what it cites, and where it is cited. */
export function NoteLinks({ related, onOpenNote, onRelate, onRemoveRelation }: NoteLinksProps) {
  const { relations, mentions, backlinks } = related;

  return (
    <section className="note-links">
      <div className="note-links-group">
        <h2 className="panel-title">
          <LinkSimple size={13} weight="bold" /> Relacionadas
          {relations.length > 0 && <span className="panel-count">{relations.length}</span>}
          <button type="button" className="btn btn-ghost btn-compact" onClick={onRelate}>
            <Plus size={13} weight="bold" /> relacionar com…
          </button>
        </h2>
        {relations.length === 0 ? (
          <p className="panel-hint">
            Nenhuma relação ainda. Relacione esta nota com outra que discuta o mesmo assunto.
          </p>
        ) : (
          <ul className="relation-list">
            {relations.map((relation) => (
              <li className="relation-row" key={relation.id}>
                <span className="relation-arrow">{relation.outgoing ? "→" : "←"}</span>
                <button
                  type="button"
                  className="link"
                  onClick={() => onOpenNote(relation.other.id, relation.other.notebook_id)}
                >
                  {relation.other.title || "Nota sem título"}
                </button>
                <span className="relation-label">{relation.label || relation.other.notebook_title}</span>
                <button
                  type="button"
                  className="icon-btn is-tiny"
                  onClick={() => onRemoveRelation(relation.id)}
                  aria-label="Remover relação"
                >
                  <Trash size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {mentions.length > 0 && (
        <div className="note-links-group">
          <h2 className="panel-title">
            Menciona<span className="panel-count">{mentions.length}</span>
          </h2>
          <div className="tag-row">
            {mentions.map((mention) => (
              <button
                type="button"
                key={mention.id}
                className="link-chip"
                onClick={() => onOpenNote(mention.id, mention.notebook_id)}
              >
                {mention.title}
              </button>
            ))}
          </div>
        </div>
      )}

      {backlinks.length > 0 && (
        <div className="note-links-group">
          <h2 className="panel-title">
            Mencionado em<span className="panel-count">{backlinks.length}</span>
          </h2>
          <ul className="relation-list">
            {backlinks.map((backlink) => (
              <li className="relation-row" key={backlink.block_id}>
                <button
                  type="button"
                  className="link"
                  onClick={() => onOpenNote(backlink.note.id, backlink.note.notebook_id)}
                >
                  {backlink.note.title || "Nota sem título"}
                </button>
                <span className="relation-label is-quote">{backlink.excerpt}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
