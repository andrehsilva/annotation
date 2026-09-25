import { Code, FileText, MagnifyingGlass, Notebook, Tag } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { SearchHit } from "../lib/types";
import { Key } from "./ui";

const HIT_ICONS: Record<SearchHit["kind"], Icon> = {
  notebook: Notebook,
  note: FileText,
  block: Code,
  tag: Tag,
};

const HIT_LABELS: Record<SearchHit["kind"], string> = {
  notebook: "caderno",
  note: "nota",
  block: "bloco",
  tag: "tag",
};

interface CommandPaletteProps {
  onClose: () => void;
  onNavigate: (hit: SearchHit) => void;
}

export function CommandPalette({ onClose, onNavigate }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setHits([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void api
        .search(trimmed)
        .then((results) => {
          if (!cancelled) {
            setHits(results.hits);
            setCursor(0);
          }
        })
        .catch((error: unknown) => console.error(error));
    }, 160);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const index = Math.min(cursor, Math.max(hits.length - 1, 0));

  return (
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-label="Busca">
        <div className="modal-head">
          <MagnifyingGlass size={16} />
          <input
            ref={inputRef}
            className="modal-input"
            value={query}
            placeholder="Buscar cadernos, notas, blocos e tags..."
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") onClose();
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setCursor((current) => Math.min(current + 1, hits.length - 1));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setCursor((current) => Math.max(current - 1, 0));
              }
              if (event.key === "Enter") {
                event.preventDefault();
                const hit = hits[index];
                if (hit) onNavigate(hit);
              }
            }}
          />
          <span className="modal-keys">
            <Key>Esc</Key>
          </span>
        </div>
        <ul className="modal-list">
          {hits.map((hit, position) => {
            const HitIcon = HIT_ICONS[hit.kind];
            return (
              <li key={`${hit.kind}-${hit.id}`}>
                <button
                  type="button"
                  className={position === index ? "hit is-active" : "hit"}
                  onMouseEnter={() => setCursor(position)}
                  onClick={() => onNavigate(hit)}
                >
                  <span className="hit-icon">
                    <HitIcon size={15} weight="bold" />
                  </span>
                  <span className="hit-main">
                    <span className="hit-title">{hit.title}</span>
                    {hit.snippet && <span className="hit-snippet">{hit.snippet}</span>}
                  </span>
                  <span className="hit-kind">{HIT_LABELS[hit.kind]}</span>
                </button>
              </li>
            );
          })}
          {query.trim() && hits.length === 0 && (
            <li className="palette-empty">Nada encontrado para “{query.trim()}”.</li>
          )}
          {!query.trim() && (
            <li className="palette-empty">
              Digite para buscar. Enter abre o primeiro resultado.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
