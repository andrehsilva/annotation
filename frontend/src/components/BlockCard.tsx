import {
  ArrowSquareOut,
  Check,
  CopySimple,
  DotsSixVertical,
  Paperclip,
  PencilSimple,
  Trash,
  UploadSimple,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, hostOf, isForeignBlock, vimeoId, youtubeId } from "../lib/format";
import { highlightCode } from "../lib/highlight";
import { LANGUAGES, LANGUAGE_PRIORITY, guessLanguage, languageLabel } from "../lib/languages";
import type { Block } from "../lib/types";
import type { ImagePreview } from "./ImageModal";
import type { PdfPreview } from "./PdfModal";

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
  /** Sai do modo de edição do bloco (o código volta à visão realçada). */
  onDeactivate: () => void;
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
  onOpenPdf: (pdf: PdfPreview) => void;
}

export function BlockCard({
  block,
  index,
  active,
  dragging,
  highlighted,
  onActivate,
  onDeactivate,
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
  onOpenPdf,
}: BlockCardProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editingLink, setEditingLink] = useState(false);

  /** As linguagens na ordem do seletor: as prioridades primeiro, o resto em ordem alfabética. */
  const orderedLanguages = useMemo<string[]>(() => {
    const priority: string[] = [...LANGUAGE_PRIORITY];
    return [...priority, ...LANGUAGES.filter((language) => !priority.includes(language)).sort()];
  }, []);
  /** O realce só custa quando o bloco não está em edição — e o texto já sai escapado do hljs. */
  /**
   * A linguagem que a tela mostra: a escolhida no seletor ou, quando ninguém escolheu nada, o palpite
   * do conteúdo (o seletor diz "detectar" nesse caso). O palpite vale só para exibir — gravar é papel
   * de quem escolhe, para o markdown exportado não sair com uma linguagem que ninguém confirmou.
   */
  const shownLanguage = block.language || guessLanguage(block.text) || "";
  const highlightedHtml = useMemo(
    () => (block.type === "code" && !active ? highlightCode(block.text, shownLanguage) : null),
    [active, block.text, block.type, shownLanguage],
  );

  const lineCount = block.text ? block.text.replace(/\n$/, "").split("\n").length : 0;
  const lineNumbers = useMemo(
    () => Array.from({ length: Math.max(lineCount, 1) }, (_, index) => index + 1).join("\n"),
    [lineCount],
  );

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(block.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Sem permissão de área de transferência: o código está ali para selecionar e copiar.
    }
  };
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

  // Bloco de outra conta (nota compartilhada): leitura. O backend recusa mudá-lo ou apagá-lo, e a
  // tela não oferece o que a rota nega.
  const foreign = isForeignBlock(block);

  const video = block.type === "video" ? block.url.trim() : "";
  const youtube = video ? youtubeId(video) : null;
  const vimeo = video && !youtube ? vimeoId(video) : null;

  /**
   * Bloco de link vazio **é** o campo: quem cria um bloco de url quer colar a url, e o botão que
   * ficava no meio do caminho não abria nada (o campo só existia com url — o link não entrava).
   */
  const linkEditing = block.type === "url" && !foreign && (editingLink || !block.url.trim());

  /** O foco anda entre os dois campos: fecha quando sai do bloco inteiro, não ao trocar de campo. */
  const onLinkBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setEditingLink(false);
  };

  /** Esc sai da edição: o cartão volta a ser o link (num bloco vazio não há o que fechar). */
  const onLinkKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    setEditingLink(false);
    if (event.target instanceof HTMLElement) event.target.blur();
  };

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
          disabled={foreign}
          title={
            foreign
              ? `Bloco de ${block.author}: só quem escreveu troca o tipo`
              : "Trocar o tipo (ou digite / em um bloco vazio)"
          }
        >
          <KindIcon size={13} weight="bold" />
          {KIND_LABELS[block.type]}
        </button>
        {block.author && (
          <span className="block-author" title={`Escrito por ${block.author}`}>
            {block.author}
          </span>
        )}
      </div>

      <div className="block-body">
        {block.type === "text" && (
          <textarea
            ref={(element) => {
              textareaRef.current = element;
              onRegisterRef(element);
            }}
            className={foreign ? "block-textarea is-readonly" : "block-textarea"}
            value={block.text}
            readOnly={foreign}
            title={foreign ? `Escrito por ${block.author} — só quem escreveu edita` : undefined}
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
              <select
                className="lang-input"
                value={shownLanguage}
                disabled={foreign}
                aria-label="Linguagem do bloco"
                onChange={(event) => onPatch({ language: event.target.value })}
              >
                <option value="">detectar</option>
                {block.language && !orderedLanguages.includes(block.language) && (
                  <option value={block.language}>{languageLabel(block.language)}</option>
                )}
                {orderedLanguages.map((language) => (
                  <option key={language} value={language}>
                    {languageLabel(language)}
                  </option>
                ))}
              </select>
              {block.text.trim() && (
                <>
                  <span className="code-hint">
                    {lineCount} {lineCount === 1 ? "linha" : "linhas"}
                  </span>
                  <button
                    type="button"
                    className="icon-btn is-tiny"
                    onClick={() => void copyCode()}
                    title="Copiar o código"
                    aria-label="Copiar o código"
                  >
                    {copied ? <Check size={13} weight="bold" /> : <CopySimple size={13} weight="bold" />}
                  </button>
                </>
              )}
            </div>
            {active ? (
              <textarea
                ref={(element) => {
                  textareaRef.current = element;
                  onRegisterRef(element);
                }}
                className="code-textarea"
                value={block.text}
                readOnly={foreign}
                spellCheck={false}
                wrap="off"
                placeholder="// cole o snippet aqui"
                onChange={(event) => {
                  const next = event.target.value;
                  // Sem linguagem escolhida, o próprio conteúdo dá o palpite (o seletor corrige).
                  const guessed = block.language ? null : guessLanguage(next);
                  onPatch(guessed ? { text: next, language: guessed } : { text: next });
                }}
                onKeyDown={(event) => {
                  const area = event.currentTarget;
                  const { selectionStart, selectionEnd, value } = area;
                  const put = (text: string, caret: number) => {
                    onPatch({ text });
                    window.requestAnimationFrame(() => {
                      area.selectionStart = area.selectionEnd = caret;
                    });
                  };
                  // Esc e Ctrl+E saem da edição: o bloco volta à visão realçada.
                  if (event.key === "Escape" || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "e")) {
                    event.preventDefault();
                    area.blur();
                    onDeactivate();
                    return;
                  }
                  if (foreign) return;
                  // Tab indenta em vez de sair do bloco: dentro de um snippet isso é o esperado.
                  if (event.key === "Tab") {
                    event.preventDefault();
                    put(`${value.slice(0, selectionStart)}  ${value.slice(selectionEnd)}`, selectionStart + 2);
                    return;
                  }
                  // Enter mantém a indentação da linha e abre dois espaços depois de `:` e `{`.
                  if (event.key === "Enter") {
                    event.preventDefault();
                    const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
                    const line = value.slice(lineStart, selectionStart);
                    const indent = /^\s*/.exec(line)?.[0] ?? "";
                    const extra = /[:{([]\s*$/.test(line) ? "  " : "";
                    put(
                      `${value.slice(0, selectionStart)}\n${indent}${extra}${value.slice(selectionEnd)}`,
                      selectionStart + 1 + indent.length + extra.length,
                    );
                  }
                }}
                rows={3}
              />
            ) : (
              <div className="code-view" onMouseDown={onActivate} onFocusCapture={onActivate}>
                <pre className="code-gutter" aria-hidden="true">
                  {lineNumbers}
                </pre>
                <pre className={highlightedHtml ? "code-body hljs" : "code-body"} tabIndex={0}>
                  {highlightedHtml ? (
                    <code dangerouslySetInnerHTML={{ __html: highlightedHtml }} />
                  ) : (
                    <code>{block.text}</code>
                  )}
                </pre>
              </div>
            )}
          </div>
        )}

        {block.type === "url" && !linkEditing && block.url.trim() && (
          // Com url, o cartão **é** o link: clicar abre fora. Editar tem botão próprio — antes, o
          // clique ativava o bloco e trocava o cartão pelos campos, e o link nunca abria.
          <div className="url-block is-card">
            <a
              className="link-card"
              href={block.url}
              target="_blank"
              rel="noreferrer"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <span className="link-host">{hostOf(block.url)}</span>
              <span className="link-title">{block.caption || block.url}</span>
              <ArrowSquareOut size={12} />
            </a>
            {!foreign && (
              <button
                type="button"
                className="icon-btn is-tiny"
                onClick={() => setEditingLink(true)}
                title="Editar o link e o rótulo"
                aria-label="Editar o link"
              >
                <PencilSimple size={13} />
              </button>
            )}
          </div>
        )}

        {block.type === "url" && !linkEditing && !block.url.trim() && (
          <p className="panel-hint">
            <Paperclip size={13} /> Bloco de link vazio, de {block.author}.
          </p>
        )}

        {linkEditing && (
          // O foco anda entre os dois campos: só fecha quando sai do bloco inteiro (ou com Esc), e
          // nunca por a url ter ficado vazia no meio da edição — era por aí que o link se perdia.
          <div className="url-block" onBlur={onLinkBlur} onKeyDown={onLinkKeyDown}>
            <input
              ref={(element) => onRegisterRef(element)}
              className="input"
              value={block.url}
              placeholder="https://…"
              autoFocus={active}
              // Ao escrever a url o campo se fixa aberto: sem isto o cartão voltava no meio da
              // digitação (o bloco deixava de estar vazio) e a url parava na primeira letra.
              onChange={(event) => {
                setEditingLink(true);
                onPatch({ url: event.target.value });
              }}
            />
            <input
              className="input"
              value={block.caption}
              placeholder="rótulo do link"
              onChange={(event) => onPatch({ caption: event.target.value })}
            />
          </div>
        )}

        {(block.type === "image" || block.type === "video") && (
          <div className="media-block">
            <div className="media-inputs">
              <input
                ref={(element) => onRegisterRef(element)}
                className="input"
                value={block.url}
                readOnly={foreign}
                placeholder={block.type === "image" ? "cole a url da imagem" : "cole a url do vídeo"}
                onChange={(event) => onPatch({ url: event.target.value })}
              />
              {!foreign && (
                <label className="btn btn-ghost btn-file">
                  <UploadSimple size={15} />
                  {uploading ? "enviando…" : "arquivo"}
                  <input
                    type="file"
                    accept={block.type === "image" ? "image/*" : "video/*"}
                    onChange={(event) => void upload(event.target.files?.[0])}
                  />
                </label>
              )}
            </div>
            <input
              className="input"
              value={block.caption}
              readOnly={foreign}
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
                  <img
                    src={block.url}
                    alt={block.caption || "imagem da nota"}
                    loading="lazy"
                    decoding="async"
                  />
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

        {block.type === "pdf" && (
          <div className="media-block">
            <div className="media-inputs">
              <input
                ref={(element) => onRegisterRef(element)}
                className="input"
                value={block.url}
                readOnly={foreign}
                placeholder="cole a url do pdf"
                onChange={(event) => onPatch({ url: event.target.value })}
              />
              {!foreign && (
                <label className="btn btn-ghost btn-file">
                  <UploadSimple size={15} />
                  {uploading ? "enviando…" : "arquivo"}
                  <input
                    type="file"
                    accept="application/pdf"
                    onChange={(event) => void upload(event.target.files?.[0])}
                  />
                </label>
              )}
            </div>
            <input
              className="input"
              value={block.caption}
              readOnly={foreign}
              placeholder="legenda"
              onChange={(event) => onPatch({ caption: event.target.value })}
            />
            {block.url.trim() && (
              <figure className="media-frame">
                <button
                  type="button"
                  className="pdf-link"
                  onClick={() =>
                    onOpenPdf({ url: block.url, title: block.caption || "PDF" })
                  }
                  title="Ler o PDF aqui"
                >
                  <KindIcon size={32} weight="bold" />
                  <span>{block.caption || "PDF"}</span>
                </button>
                {block.caption && <figcaption>{block.caption}</figcaption>}
              </figure>
            )}
            {!block.url.trim() && (
              <p className="panel-hint">
                <Paperclip size={13} /> Cole uma url ou envie um arquivo PDF do disco.
              </p>
            )}
          </div>
        )}
      </div>

      {!foreign && (
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
      )}
    </article>
  );
}
