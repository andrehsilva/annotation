import { GraphIcon, X } from "@phosphor-icons/react";
import { useEffect } from "react";

import type { Notebook } from "../lib/types";

interface RelationsModalProps {
  notebook: Notebook;
  onOpenNotebook: (id: number) => void;
  onClose: () => void;
}

/**
 * Which notebooks this one reaches through its notes.
 *
 * The link is derived — a declared relation or a `[[…]]` mention between notes — so there is
 * nothing to fill in here: relate the notes themselves, in the note footer.
 */
export function RelationsModal({ notebook, onOpenNotebook, onClose }: RelationsModalProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Afinidade do caderno">
        <div className="sheet-head">
          <p className="confirm-title">
            <GraphIcon size={16} weight="bold" /> Afinidade de “{notebook.title}”
          </p>
          <button type="button" className="icon-btn is-tiny" onClick={onClose} aria-label="Fechar">
            <X size={14} weight="bold" />
          </button>
        </div>

        <p className="panel-hint">
          Conta as notas deste caderno que se ligam a notas de fora — relações declaradas e menções.
          Para criar uma, abra a nota e use o rodapé.
        </p>

        {notebook.affinity.length === 0 ? (
          <p className="panel-hint">Nenhuma ligação ainda.</p>
        ) : (
          <ul className="relation-list">
            {notebook.affinity.map((entry) => (
              <li className="relation-row" key={entry.notebook_id}>
                <span className="relation-arrow">↔</span>
                <button
                  type="button"
                  className="link"
                  onClick={() => {
                    onClose();
                    onOpenNotebook(entry.notebook_id);
                  }}
                >
                  {entry.title}
                </button>
                <span className="relation-label">
                  {entry.links_count} {entry.links_count === 1 ? "nota ligada" : "notas ligadas"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
