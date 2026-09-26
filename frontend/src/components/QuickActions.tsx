import { ArrowLeft, Notebook, NoteBlank, Plus } from "@phosphor-icons/react";

import type { View } from "../App";

/**
 * Ações rápidas: um cluster flutuante que acompanha o que você está fazendo, em vez de encher a
 * barra de cima. Listando cadernos, só oferece criar caderno; dentro de um caderno, criar nota;
 * dentro de uma nota, também voltar para o caderno — que é a saída quando a página rolou e o
 * cabeçalho saiu de vista.
 */
export function QuickActions({
  view,
  onBack,
  onNewNotebook,
  onNewNote,
}: {
  view: View;
  onBack: () => void;
  onNewNotebook: () => void;
  onNewNote: () => void;
}) {
  const inNote = view.kind === "note";
  const inNotebook = view.kind === "notebook" || inNote;

  return (
    <div className="quick-actions">
      <div className="quick-pill" role="group" aria-label="Ações rápidas">
      {inNote && (
        <button
          type="button"
          className="icon-btn"
          onClick={onBack}
          title="Voltar para os cadernos"
          aria-label="Voltar para os cadernos"
        >
          <ArrowLeft size={17} weight="bold" />
        </button>
      )}
      {inNotebook && (
        <button
          type="button"
          className="icon-btn is-primary"
          onClick={onNewNote}
          title="Nova nota neste caderno"
          aria-label="Nova nota neste caderno"
        >
          <NoteBlank size={17} weight="bold" />
          <Plus size={11} weight="bold" className="quick-plus" />
        </button>
      )}
      <button
        type="button"
        className="icon-btn is-primary"
        onClick={onNewNotebook}
        title="Novo caderno"
        aria-label="Novo caderno"
      >
        <Notebook size={17} weight="bold" />
        <Plus size={11} weight="bold" className="quick-plus" />
        </button>
      </div>
    </div>
  );
}
