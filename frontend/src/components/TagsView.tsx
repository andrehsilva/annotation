import { X } from "@phosphor-icons/react";

import type { TagUsage } from "../lib/types";
import { EmptyState } from "./ui";

interface TagsViewProps {
  tags: TagUsage[];
  onOpenTag: (name: string) => void;
  onDeleteTag: (tagId: number) => void;
}

/**
 * As tags da conta, como chips: clicar filtra a lista de notas; o **×** apaga a tag.
 *
 * A tela não repete os contadores do cabeçalho (eles já estão no topo, em todas as telas) nem a
 * contagem por tag: o que importa aqui é a tag em si, no mesmo formato em que ela aparece na nota.
 */
export function TagsView({ tags, onOpenTag, onDeleteTag }: TagsViewProps) {
  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">Tags</h1>
        <p className="view-lede">
          Clique numa tag para filtrar a lista de notas (ela abre se estiver escondida); dentro de uma
          nota, <kbd className="keycap">#</kbd> cria e aplica sem sair do teclado.
        </p>
      </header>

      {tags.length === 0 ? (
        <EmptyState
          title="Nenhuma tag"
          hint="Dentro de uma nota, digite # num bloco vazio para criar a primeira."
        />
      ) : (
        <div className="tag-cloud is-page">
          {tags.map((tag) => (
            <span className="tag-chip is-attached" key={tag.id}>
              <button type="button" className="link" onClick={() => onOpenTag(tag.name)}>
                {tag.name}
              </button>
              <button
                type="button"
                className="tag-chip-remove"
                onClick={() => onDeleteTag(tag.id)}
                title={`Apagar a tag ${tag.name}`}
                aria-label={`Apagar tag ${tag.name}`}
              >
                <X size={11} weight="bold" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
