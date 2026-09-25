import { GraphIcon, LinkSimple, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { NoteSummary, RelationEdge } from "../lib/types";
import type { ConfirmRequest } from "./ConfirmDialog";
import type { ToastKind } from "./ToastStack";
import { GraphCanvas } from "./GraphCanvas";
import { EmptyState } from "./ui";

const NOTE_LIMIT = 300;

interface RelationsViewProps {
  onOpenNote: (noteId: number, notebookId: number) => void;
  onChanged: () => void;
  onError: (error: unknown) => void;
  onNotify: (message: string, kind?: ToastKind) => void;
  onAskConfirm: (request: ConfirmRequest) => void;
}

/**
 * Read-only map of what links to what.
 *
 * Notes are the level where links are declared and where a `[[` citation lives, so this screen only
 * inspects and removes: authoring happens in the note footer.
 */
export function RelationsView({
  onOpenNote,
  onChanged,
  onError,
  onNotify,
  onAskConfirm,
}: RelationsViewProps) {
  const [edges, setEdges] = useState<RelationEdge[]>([]);
  const [notes, setNotes] = useState<NoteSummary[]>([]);

  const reload = useCallback(async () => {
    /** Uma fonte fora do ar não pode levar a outra junto: cada uma reporta e devolve vazio. */
    const [edgeList, noteList] = await Promise.all([
      api.listRelations().catch((error: unknown) => {
        onError(error);
        return [] as RelationEdge[];
      }),
      api.listNotes("", NOTE_LIMIT).catch((error: unknown) => {
        onError(error);
        return [] as NoteSummary[];
      }),
    ]);
    setEdges(edgeList);
    setNotes(noteList);
  }, [onError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const remove = (edge: RelationEdge) => {
    onAskConfirm({
      title: "Remover relação",
      message: `"${edge.source_title}" e "${edge.target_title}" deixam de estar ligadas.`,
      confirmLabel: "Remover",
      danger: true,
      action: async () => {
        try {
          await api.deleteRelation(edge.source_id, edge.id);
          await reload();
          onChanged();
          onNotify("Relação removida", "success");
        } catch (error) {
          onError(error);
        }
      },
    });
  };

  const declared = edges.filter((edge) => edge.kind === "relation").length;
  const cited = edges.length - declared;

  return (
    <div className="view">
      <header className="view-head">
        <div className="view-head-main">
          <h1 className="view-title">
            <GraphIcon size={20} weight="bold" />
            Relações entre notas
          </h1>
          <p className="view-lede">
            {declared} relação(ões) declarada(s) e {cited} menção(ões) entre as suas notas. Crie
            vínculos no rodapé da nota, com <b>relacionar com…</b> ou citando <b>[[título]]</b> dentro
            de um bloco de texto.
          </p>
        </div>
      </header>

      <section className="panel">
        {notes.length === 0 ? (
          <EmptyState title="Nenhuma nota" hint="Escreva notas para poder relacioná-las." />
        ) : (
          <GraphCanvas notes={notes} edges={edges} activeId={null} onSelect={onOpenNote} />
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Vínculos ({edges.length})</h2>
        {edges.length === 0 ? (
          <p className="panel-hint">Nenhum vínculo ainda.</p>
        ) : (
          <ul className="relation-list">
            {edges.map((edge) => (
              <li className="relation-row" key={edge.key}>
                <span className={edge.kind === "mention" ? "relation-tag is-mention" : "relation-tag"}>
                  {edge.kind === "mention" ? <LinkSimple size={11} weight="bold" /> : "↔"}
                </span>
                <button
                  type="button"
                  className="link"
                  onClick={() => onOpenNote(edge.source_id, edge.source_notebook_id)}
                >
                  {edge.source_title}
                </button>
                <span className="relation-arrow">→</span>
                <button
                  type="button"
                  className="link"
                  onClick={() => onOpenNote(edge.target_id, edge.target_notebook_id)}
                >
                  {edge.target_title}
                </button>
                <span className="relation-label">
                  {edge.kind === "mention" ? "menção" : edge.label || "relação"}
                </span>
                {edge.kind === "relation" && (
                  <button
                    type="button"
                    className="icon-btn is-tiny"
                    onClick={() => remove(edge)}
                    aria-label="Remover relação"
                  >
                    <Trash size={13} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
