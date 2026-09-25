import { useEffect, useState } from "react";

import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER } from "../lib/format";
import type { BlockType } from "../lib/types";

interface KindMenuProps {
  current: BlockType;
  onPick: (kind: BlockType) => void;
  onClose: () => void;
}

/** Opened by "/" on an empty block or by clicking the kind badge. Keyboard: 1-5, setas, Enter, Esc. */
export function KindMenu({ current, onPick, onClose }: KindMenuProps) {
  const [cursor, setCursor] = useState(() => Math.max(KIND_ORDER.indexOf(current), 0));

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        event.stopPropagation();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setCursor((value) => (value + step + KIND_ORDER.length) % KIND_ORDER.length);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        event.stopPropagation();
        onPick(KIND_ORDER[cursor]);
        return;
      }
      const digit = Number.parseInt(event.key, 10);
      if (!Number.isNaN(digit) && digit >= 1 && digit <= KIND_ORDER.length) {
        event.preventDefault();
        event.stopPropagation();
        onPick(KIND_ORDER[digit - 1]);
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [cursor, onClose, onPick]);

  return (
    <div className="kind-menu" role="dialog" aria-label="Tipo do bloco">
      <div className="palette-head">
        <span className="palette-title">Tipo do bloco</span>
        <span className="palette-hint">1-5 ou Enter · Esc fecha</span>
      </div>
      <ul className="palette-list">
        {KIND_ORDER.map((kind, position) => {
          const KindIcon = KIND_ICONS[kind];
          return (
            <li key={kind}>
              <button
                type="button"
                className={position === cursor ? "palette-item is-active" : "palette-item"}
                onMouseEnter={() => setCursor(position)}
                onClick={() => onPick(kind)}
              >
                <span className="palette-create">
                  <KindIcon size={14} weight="bold" />
                  {KIND_LABELS[kind]}
                </span>
                <span className="palette-meta">
                  {kind === current ? "atual" : `tecla ${position + 1}`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="palette-empty">
        Bloco vazio troca de tipo no lugar; com conteúdo, abre um bloco novo do tipo escolhido.
      </p>
    </div>
  );
}
