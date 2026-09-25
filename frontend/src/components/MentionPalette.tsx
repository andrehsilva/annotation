import { MagnifyingGlass, NoteBlank } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { NoteSummary } from "../lib/types";

interface MentionPaletteProps {
  notes: NoteSummary[];
  title: string;
  /** Shown as the meta line; the label input only appears when the caller wants one. */
  withLabel?: boolean;
  /** `[[` pickers hang under their block; the footer one sits in the flow of the page. */
  inline?: boolean;
  emptyHint: string;
  onPick: (note: NoteSummary, label: string) => void;
  onClose: () => void;
}

/** Opened by `[[` inside a text block (or by the relate button): type a title, Enter links it. */
export function MentionPalette({
  notes,
  title,
  withLabel = false,
  inline = false,
  emptyHint,
  onPick,
  onClose,
}: MentionPaletteProps) {
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const needle = query.trim().toLowerCase();
  const matches = useMemo(
    () => notes.filter((note) => note.title.toLowerCase().includes(needle)),
    [notes, needle],
  );
  const index = Math.min(cursor, Math.max(matches.length - 1, 0));

  const apply = (position: number) => {
    const picked = matches[position];
    if (!picked) return;
    onPick(picked, label.trim());
  };

  return (
    <div className={inline ? "palette is-inline" : "palette"} role="dialog" aria-label={title}>
      <div className="palette-head">
        <span className="palette-title">{title}</span>
        <span className="palette-hint">Enter escolhe · Esc fecha</span>
      </div>
      <input
        ref={inputRef}
        className="palette-input"
        value={query}
        placeholder="título da nota..."
        onChange={(event) => {
          setQuery(event.target.value);
          setCursor(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            apply(index);
          } else if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            setCursor((current) => Math.min(current + 1, matches.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setCursor((current) => Math.max(current - 1, 0));
          }
        }}
      />
      {withLabel && (
        <input
          className="palette-input"
          value={label}
          placeholder="rótulo da relação (opcional)"
          onChange={(event) => setLabel(event.target.value)}
        />
      )}
      <ul className="palette-list">
        {matches.map((note, position) => (
          <li key={note.id}>
            <button
              type="button"
              className={position === index ? "palette-item is-active" : "palette-item"}
              onMouseEnter={() => setCursor(position)}
              onClick={() => apply(position)}
            >
              <span className="palette-mention">
                <NoteBlank size={13} weight="bold" />
                {note.title}
              </span>
              <span className="palette-meta">{note.notebook_title}</span>
            </button>
          </li>
        ))}
        {matches.length === 0 && (
          <li className="palette-empty">
            <MagnifyingGlass size={12} /> {emptyHint}
          </li>
        )}
      </ul>
    </div>
  );
}
