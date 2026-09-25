import { X } from "@phosphor-icons/react";
import { useState } from "react";

import type { Tag, TagUsage } from "../lib/types";

interface TagRowProps {
  attached: Tag[];
  all: TagUsage[];
  onToggle: (tag: Tag, attached: boolean) => void;
  onCreate: (name: string) => Promise<Tag | null>;
}

/** Chips for the tags already applied, plus an inline "add" input with suggestions. */
export function TagRow({ attached, all, onToggle, onCreate }: TagRowProps) {
  const [draft, setDraft] = useState("");
  const attachedIds = new Set(attached.map((tag) => tag.id));
  const suggestions = all.filter((tag) => !attachedIds.has(tag.id));

  const commit = async () => {
    const name = draft.trim();
    if (!name) return;
    setDraft("");
    const existing = all.find((tag) => tag.name.toLowerCase() === name.toLowerCase());
    if (existing) {
      if (!attachedIds.has(existing.id)) onToggle(existing, false);
      return;
    }
    const created = await onCreate(name);
    if (created) onToggle(created, false);
  };

  return (
    <div className="tag-row">
      {attached.map((tag) => (
        <span className="tag-chip is-attached" key={tag.id}>
          {tag.name}
          <button
            type="button"
            className="tag-chip-remove"
            onClick={() => onToggle(tag, true)}
            aria-label={`Remover tag ${tag.name}`}
          >
            <X size={11} weight="bold" />
          </button>
        </span>
      ))}
      <input
        className="tag-input"
        list="notai-tags"
        value={draft}
        placeholder="+ tag"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void commit();
          }
          if (event.key === "Escape") setDraft("");
        }}
        onBlur={() => void commit()}
        aria-label="Adicionar tag"
      />
      <datalist id="notai-tags">
        {suggestions.map((tag) => (
          <option key={tag.id} value={tag.name} />
        ))}
      </datalist>
    </div>
  );
}
