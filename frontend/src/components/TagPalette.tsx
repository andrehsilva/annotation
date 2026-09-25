import { Plus } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Tag, TagUsage } from "../lib/types";

interface TagPaletteProps {
  all: TagUsage[];
  attachedIds: number[];
  onPick: (tag: Tag, attached: boolean) => void;
  onCreate: (name: string) => Promise<Tag | null>;
  onClose: () => void;
}

/** Ctrl+Space surface: type a name, Enter applies it (creating the tag when it is new). */
export function TagPalette({ all, attachedIds, onPick, onCreate, onClose }: TagPaletteProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const needle = query.trim().toLowerCase();
  const matches = useMemo(
    () => all.filter((tag) => tag.name.toLowerCase().includes(needle)),
    [all, needle],
  );
  const exact = all.some((tag) => tag.name.toLowerCase() === needle);
  const options = [
    ...matches.map((tag) => ({ kind: "tag" as const, tag })),
    ...(needle && !exact ? [{ kind: "create" as const, tag: null }] : []),
  ];
  const index = Math.min(cursor, Math.max(options.length - 1, 0));

  const apply = async (position: number) => {
    const option = options[position];
    if (!option) return;
    if (option.kind === "tag") {
      onPick(option.tag, attachedIds.includes(option.tag.id));
    } else {
      const created = await onCreate(query.trim());
      if (created) onPick(created, false);
    }
    setQuery("");
    setCursor(0);
    inputRef.current?.focus();
  };

  return (
    <div className="palette" role="dialog" aria-label="Tags">
      <div className="palette-head">
        <span className="palette-title">Tags</span>
        <span className="palette-hint">Enter aplica · Esc fecha</span>
      </div>
      <input
        ref={inputRef}
        className="palette-input"
        value={query}
        placeholder="nome da tag..."
        onChange={(event) => {
          setQuery(event.target.value);
          setCursor(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void apply(index);
          } else if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            setCursor((current) => Math.min(current + 1, options.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setCursor((current) => Math.max(current - 1, 0));
          }
        }}
      />
      <ul className="palette-list">
        {options.map((option, position) => (
          <li key={option.kind === "tag" ? option.tag.id : "create"}>
            <button
              type="button"
              className={position === index ? "palette-item is-active" : "palette-item"}
              onMouseEnter={() => setCursor(position)}
              onClick={() => void apply(position)}
            >
              {option.kind === "tag" ? (
                <>
                  <span className="tag-chip is-attached">{option.tag.name}</span>
                  <span className="palette-meta">
                    {option.tag.notes_count} notas · {attachedIds.includes(option.tag.id) ? "remover" : "aplicar"}
                  </span>
                </>
              ) : (
                <>
                  <span className="palette-create">
                    <Plus size={13} weight="bold" /> criar “{query.trim()}”
                  </span>
                  <span className="palette-meta">nova tag</span>
                </>
              )}
            </button>
          </li>
        ))}
        {options.length === 0 && <li className="palette-empty">Digite para criar a primeira tag.</li>}
      </ul>
    </div>
  );
}
