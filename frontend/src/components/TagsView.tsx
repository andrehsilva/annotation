import { Trash } from "@phosphor-icons/react";

import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER } from "../lib/format";
import type { Stats, TagUsage } from "../lib/types";
import { EmptyState } from "./ui";

interface TagsViewProps {
  tags: TagUsage[];
  stats: Stats | null;
  onOpenTag: (name: string) => void;
  onDeleteTag: (tagId: number) => void;
}

export function TagsView({ tags, stats, onOpenTag, onDeleteTag }: TagsViewProps) {
  return (
    <div className="view">
      <header className="view-head">
        <div className="view-head-main">
          <h1 className="view-title">Tags</h1>
          <p className="view-lede">
            Tags atravessam cadernos e notas. Clique numa tag para filtrar a lista de cadernos (ela
            abre se estiver escondida); use Ctrl+Espaço dentro de uma nota para criar e aplicar sem
            sair do teclado.
          </p>
        </div>
        <div className="view-head-side">
          {stats && (
            <div className="nb-counts is-large">
              {KIND_ORDER.map((kind) => {
                const KindIcon = KIND_ICONS[kind];
                return (
                  <span className="count-chip" key={kind} title={`${stats.counts[kind]} ${KIND_LABELS[kind]}`}>
                    <KindIcon size={13} weight="bold" />
                    {stats.counts[kind]}
                    <em>{KIND_LABELS[kind]}</em>
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </header>

      <section className="panel">
        {tags.length === 0 ? (
          <EmptyState
            title="Nenhuma tag"
            hint="Abra uma nota e pressione Ctrl+Espaço para criar a primeira."
          />
        ) : (
          <ul className="tag-table">
            {tags.map((tag) => (
              <li className="tag-row-item" key={tag.id}>
                <button type="button" className="link" onClick={() => onOpenTag(tag.name)}>
                  {tag.name}
                </button>
                <span className="tag-meta">{tag.notebooks_count} cadernos</span>
                <span className="tag-meta">{tag.notes_count} notas</span>
                <button
                  type="button"
                  className="icon-btn is-tiny"
                  onClick={() => onDeleteTag(tag.id)}
                  aria-label={`Apagar tag ${tag.name}`}
                >
                  <Trash size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
