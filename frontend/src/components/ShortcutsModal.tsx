import { X } from "@phosphor-icons/react";
import { useEffect } from "react";

import { Key } from "./ui";

/** Cada linha é um atalho e o que ele faz; o grupo é o contexto em que ele vale. */
const GROUPS: { title: string; rows: { keys: string[]; what: string; where?: string }[] }[] = [
  {
    title: "Em qualquer lugar",
    rows: [
      { keys: ["Ctrl", "K"], what: "Buscar em notas, blocos e tags" },
      { keys: ["Ctrl", "Alt", "N"], what: "Nova nota" },
      { keys: ["Ctrl", "/"], what: "Esta lista de atalhos" },
      { keys: ["Esc"], what: "Fechar paletas, menus e modais" },
    ],
  },
  {
    title: "Na nota",
    rows: [
      { keys: ["Enter"], what: "Novo bloco (dentro de código, quebra linha)" },
      { keys: ["Shift", "Enter"], what: "Quebra de linha no mesmo bloco" },
      { keys: ["Ctrl", "Shift", "L"], what: "Escolher o tipo do bloco novo" },
      { keys: ["Arrastar", "⠿"], what: "Reordenar os blocos" },
      { keys: ["Backspace"], what: "Bloco vazio: apaga e volta o foco" },
    ],
  },
  {
    title: "Em bloco vazio",
    rows: [
      { keys: ["/"], what: "Menu de tipo: 1–6 ou setas + Enter" },
      { keys: ["#"], what: "Tags: filtra, aplica, remove ou cria" },
      { keys: ["[["], what: "Citar outra nota (vira vínculo)" },
      { keys: ["@"], what: "Mesmo seletor de notas" },
      { keys: ["Alt", "Enter"], what: "Bloco de código, mesmo dentro de código" },
    ],
  },
];

/**
 * A lista de atalhos, aberta por `Ctrl` + `/`.
 *
 * O gatilho é o mesmo dos outros apps de dev (GitHub, Slack) e não colide com navegador nenhum — ao
 * contrário de `Ctrl` + `Espaço`, que é o alternador de IME, e de `Alt` + `Espaço`, que abre o menu
 * da janela no Windows.
 */
export function ShortcutsModal({ onClose }: { onClose: () => void }) {
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
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Atalhos">
        <div className="sheet-head">
          <p className="confirm-title">Atalhos</p>
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onClose}
            title="Fechar (Esc)"
            aria-label="Fechar os atalhos"
          >
            <X size={14} weight="bold" />
          </button>
        </div>

        {GROUPS.map((group) => (
          <div className="shortcut-group" key={group.title}>
            <p className="panel-title">{group.title}</p>
            <ul className="shortcut-list">
              {group.rows.map((row) => (
                <li className="shortcut-row" key={row.what}>
                  <span className="shortcut-keys">
                    {row.keys.map((key) => (
                      <Key key={key}>{key}</Key>
                    ))}
                  </span>
                  <span className="shortcut-what">{row.what}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}

        <p className="panel-hint">
          Os gatilhos digitados (`/`, `#`, `[[`) só valem com o bloco vazio, para não atrapalhar quem
          está escrevendo — é a mesma regra do editor, e vale para qualquer teclado.
        </p>
      </div>
    </div>
  );
}
