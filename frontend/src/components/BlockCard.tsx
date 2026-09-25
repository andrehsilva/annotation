import {
  DotsSixVertical,
  Paperclip,
  Trash,
  UploadSimple,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, hostOf, vimeoId, youtubeId } from "../lib/format";
import type { Block } from "../lib/types";
import type { ImagePreview } from "./ImageModal";

const LANGUAGES = [
  "bash",
  "c",
  "csharp",
  "css",
  "dockerfile",
  "go",
  "html",
  "java",
  "javascript",
  "json",
  "kotlin",
  "lua",
  "php",
  "powershell",
  "python",
  "ruby",
  "rust",
  "sql",
  "swift",
  "toml",
  "typescript",
  "xml",
  "yaml",
];

export interface MentionToken {
  /** Text typed after the trigger, used to filter the picker. */
  query: string;
  /** Where the `[[` starts and the caret sits, so the picker can replace the token. */
  start: number;
  end: number;
}

interface BlockCardProps {
  block: Block;
  index: number;
  active: boolean;
  dragging: boolean;
  highlighted: boolean;
  onActivate: () => void;
  onPatch: (patch: Partial<Block>) => void;
  onDelete: () => void;
  onRegisterRef: (element: HTMLElement | null) => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDropOn: () => void;
  onUploadError: (error: unknown) => void;
  onKindClick: () => void;
  /** `[[` or `@` at the caret opens the note picker; null means the token is gone. */
  onMention: (token: MentionToken | null) => void;
  onOpenImage: (image: ImagePreview) => void;
}

export function BlockCard({
  block,
  index,
  active,
  dragging,
  highlighted,
  onActivate,
  onPatch,
  onDelete,
  onRegisterRef,
  onDragStart,
  onDragEnd,
  onDropOn,
  onUploadError,
  onKindClick,
  onMention,
  onOpenImage,
}: BlockCardProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const KindIcon = KIND_ICONS[block.type];

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [block.text, block.type]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const media = await api.upload(file);
      onPatch({ url: media.url, caption: block.caption || media.name });
    } catch (error) {
      onUploadError(error);
    } finally {
      setUploading(false);
    }
  };

  const video = block.type === "video" ? block.url.trim() : "";
  const youtube = video ? youtubeId(video) : null;
  const vimeo = video && !youtube ? vimeoId(video) : null;

  /** `[[` or `@` right after a space (or the start) starts a mention; anything else is plain text. */
  const TRIGGER = /(?:^|\s)(\[\[|@)([^\[\]\n]*)$/;

  const onTextChange = (value: string, caret: number) => {
    onPatch({ text: value });
    const match = TRIGGER.exec(value.slice(0, caret));
    onMention(
      match
        ? { query: match[2], start: caret - match[2].length - match[1].length, end: caret }
        : null,
    );
  };

  return (
    <article
      className={`block${active ? " is-active" : ""}${dragging ? " is-dragging" : ""}${highlighted ? " is-target" : ""}`}
      onMouseDown={onActivate}
      onFocusCapture={onActivate}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDropOn();
      }}
    >
      <div className="block-rail">
        <span className="block-rail-top">
          <span
            className="drag-handle"
            draggable
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            title="Arrastar para reordenar"
          >
            <DotsSixVertical size={14} weight="bold" />
          </span>
          <span className="block-index">{String(index + 1).padStart(2, "0")}</span>
        </span>
        <button
          type="button"
          className={`block-kind is-${block.type}`}
          onClick={onKindClick}
          title="Trocar o tipo (ou digite / em um bloco vazio)"
        >
          <KindIcon size={13} weight="bold" />
          {KIND_LABELS[block.type]}
        </button>
      </div>

      <div className="block-body">
        {block.type === "text" && (
          <textarea
            ref={(element) => {
              textareaRef.current = element;
              onRegisterRef(element);
            }}
            className="block-textarea"
            value={block.text}
            placeholder="Escreva o texto corrido. / troca o tipo do bloco, # cria tag, [[ cita uma nota."
            onChange={(event) =>
              onTextChange(event.target.value, event.target.selectionStart ?? Infinity)
            }
            rows={1}
          />
        )}

        {block.type === "code" && (
          <div className="code-shell">
            <div className="code-toolbar">
              <input
                className="lang-input"
                list="notai-languages"
                value={block.language}
                placeholder="linguagem"
                onChange={(event) => onPatch({ language: event.target.value })}
              />
              <datalist id="notai-languages">
                {LANGUAGES.map((language) => (
                  <option key={language} value={language} />
                ))}
              </datalist>
            </div>
            <textarea
              ref={(element) => {
                textareaRef.current = element;
                onRegisterRef(element);
              }}
              className="code-textarea"
              value={block.text}
              spellCheck={false}
              wrap="off"
              placeholder="// cole o snippet aqui"
              onChange={(event) => onPatch({ text: event.target.value })}
              rows={3}
            />
          </div>
        )}

        {block.type === "url" &&
          (active ? (
            <div className="url-block">
              <input
                ref={(element) => onRegisterRef(element)}
                className="input"
                value={block.url}
                placeholder="https://..."
                onChange={(event) => onPatch({ url: event.target.value })}
              />
              <input
                className="input"
                value={block.caption}
                placeholder="rótulo do link"
                onChange={(event) => onPatch({ caption: event.target.value })}
              />
            </div>
          ) : block.url.trim() ? (
            <a className="link-card" href={block.url} target="_blank" rel="noreferrer">
              <span className="link-host">{hostOf(block.url)}</span>
              <span className="link-title">{block.caption || block.url}</span>
            </a>
          ) : (
            <p className="panel-hint">
              <Paperclip size={13} /> Bloco de link vazio: clique para colar a url.
            </p>
          ))}

        {(block.type === "image" || block.type === "video") && (
          <div className="media-block">
            <div className="media-inputs">
              <input
                ref={(element) => onRegisterRef(element)}
                className="input"
                value={block.url}
                placeholder={block.type === "image" ? "cole a url da imagem" : "cole a url do vídeo"}
                onChange={(event) => onPatch({ url: event.target.value })}
              />
              <label className="btn btn-ghost btn-file">
                <UploadSimple size={15} />
                {uploading ? "enviando..." : "arquivo"}
                <input
                  type="file"
                  accept={block.type === "image" ? "image/*" : "video/*"}
                  onChange={(event) => void upload(event.target.files?.[0])}
                />
              </label>
            </div>
            <input
              className="input"
              value={block.caption}
              placeholder="legenda"
              onChange={(event) => onPatch({ caption: event.target.value })}
            />
            {block.type === "image" && block.url.trim() && (
              <figure className="media-frame">
                <button
                  type="button"
                  className="media-open"
                  onClick={() =>
                    onOpenImage({ src: block.url, label: block.caption || "imagem da nota" })
                  }
                  title="Abrir no tamanho real"
                >
                  <img src={block.url} alt={block.caption || "imagem da nota"} />
                </button>
                {block.caption && <figcaption>{block.caption}</figcaption>}
              </figure>
            )}
            {block.type === "video" && video && (
              <figure className="media-frame">
                {youtube ? (
                  <iframe
                    src={`https://www.youtube.com/embed/${youtube}`}
                    title={block.caption || "vídeo"}
                    allowFullScreen
                  />
                ) : vimeo ? (
                  <iframe src={`https://player.vimeo.com/video/${vimeo}`} title={block.caption || "vídeo"} allowFullScreen />
                ) : (
                  <video src={video} controls />
                )}
                {block.caption && <figcaption>{block.caption}</figcaption>}
              </figure>
            )}
            {!block.url.trim() && (
              <p className="panel-hint">
                <Paperclip size={13} /> Cole uma url ou envie um arquivo do disco.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="block-tools">
        <button
          type="button"
          className="icon-btn is-tiny"
          onClick={onDelete}
          aria-label="Apagar bloco"
          title="Apagar bloco"
        >
          <Trash size={13} />
        </button>
      </div>
    </article>
  );
}
