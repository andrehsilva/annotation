import { ArrowSquareOut, NoteBlank } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, hostOf, relativeTime, vimeoId, youtubeId } from "../lib/format";
import type { BlockListItem, BlockType } from "../lib/types";
import type { ImagePreview } from "./ImageModal";
import { EmptyState, Spinner } from "./ui";

interface KindViewProps {
  blockType: BlockType;
  onOpenNote: (notebookId: number, noteId: number, blockId: number) => void;
  onOpenImage: (image: ImagePreview) => void;
  onError: (error: unknown) => void;
}

const HINTS: Record<BlockType, string> = {
  text: "Tudo que você escreveu correndo, de todos os cadernos. Clique para abrir a nota no bloco.",
  code: "Todos os snippets, de todos os cadernos. Clique para abrir a nota no bloco.",
  url: "Todos os links. Clique para abrir o site em outra aba, ou vá para a nota.",
  image: "Todas as imagens. Clique para abrir em modal, no tamanho real, ou vá para a nota.",
  video: "Todos os vídeos, tocando direto na lista. Use o botão para ir à nota.",
};

export function KindView({ blockType, onOpenNote, onOpenImage, onError }: KindViewProps) {
  const [items, setItems] = useState<BlockListItem[] | null>(null);
  const KindIcon = KIND_ICONS[blockType];

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    void api
      .listBlocks(blockType)
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch((error: unknown) => {
        if (!cancelled) onError(error);
      });
    return () => {
      cancelled = true;
    };
  }, [blockType, onError]);

  if (items === null) return <Spinner label={`Carregando ${KIND_LABELS[blockType]}...`} />;

  const grid = blockType === "image" || blockType === "video";
  const openNote = (item: BlockListItem) => onOpenNote(item.notebook_id, item.note_id, item.id);

  const footer = (item: BlockListItem) => (
    <div className="element-foot">
      <span className="element-source">
        {item.notebook_title} <span className="element-arrow">›</span>{" "}
        {item.note_title || "nota sem título"}
      </span>
      <span className="element-time">{relativeTime(item.updated_at)}</span>
      <button type="button" className="btn btn-ghost btn-compact" onClick={() => openNote(item)}>
        <NoteBlank size={13} /> Abrir nota
      </button>
    </div>
  );

  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">
          <KindIcon size={20} weight="bold" />
          {KIND_LABELS[blockType]}
          <span className="pill-count">{items.length}</span>
        </h1>
        <p className="view-lede">{HINTS[blockType]}</p>
      </header>

      {items.length === 0 ? (
        <EmptyState
          title={`Nada de ${KIND_LABELS[blockType]} ainda`}
          hint="Crie um bloco desse tipo dentro de uma nota: digite / em um bloco vazio e escolha o tipo."
        />
      ) : (
        <section className={grid ? "element-grid" : "element-list"}>
          {items.map((item) => {
            if (blockType === "text" || blockType === "code") {
              return (
                <button
                  type="button"
                  className={`element-card is-${blockType}`}
                  key={item.id}
                  onClick={() => openNote(item)}
                >
                  {blockType === "code" ? (
                    <>
                      <span className="element-lang">{item.language || "código"}</span>
                      <pre className="element-code">{item.text || "— bloco vazio —"}</pre>
                    </>
                  ) : (
                    <p className="element-text">{item.text || "— bloco vazio —"}</p>
                  )}
                  {footer(item)}
                </button>
              );
            }

            if (blockType === "url") {
              return (
                <article className="element-card" key={item.id}>
                  {item.url ? (
                    <a className="element-body" href={item.url} target="_blank" rel="noreferrer">
                      <span className="link-host">{hostOf(item.url)}</span>
                      <span className="element-title">{item.caption || item.url}</span>
                      <span className="element-url">{item.url}</span>
                      <span className="element-open">
                        <ArrowSquareOut size={12} /> abre em outra aba
                      </span>
                    </a>
                  ) : (
                    <p className="element-text is-muted">— link vazio —</p>
                  )}
                  {footer(item)}
                </article>
              );
            }

            const video = item.url;
            const youtube = blockType === "video" && video ? youtubeId(video) : null;
            const vimeo = blockType === "video" && video && !youtube ? vimeoId(video) : null;

            return (
              <article className="element-card" key={item.id}>
                {!video ? (
                  <p className="element-text is-muted">— {KIND_LABELS[blockType]} vazia —</p>
                ) : blockType === "image" ? (
                  <button
                    type="button"
                    className="element-body is-openable"
                    onClick={() =>
                      onOpenImage({ src: video, label: item.caption || item.note_title })
                    }
                    title="Abrir no tamanho real"
                  >
                    <img className="element-media" src={video} alt={item.caption || item.notebook_title} />
                  </button>
                ) : (
                  <div className="element-body">
                    {youtube ? (
                      <iframe
                        className="element-media"
                        src={`https://www.youtube.com/embed/${youtube}`}
                        title={item.caption || "vídeo"}
                        allowFullScreen
                      />
                    ) : vimeo ? (
                      <iframe
                        className="element-media"
                        src={`https://player.vimeo.com/video/${vimeo}`}
                        title={item.caption || "vídeo"}
                        allowFullScreen
                      />
                    ) : (
                      <video className="element-media" src={video} controls />
                    )}
                  </div>
                )}
                {item.caption && <p className="element-caption">{item.caption}</p>}
                {footer(item)}
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
