import { ArrowUpRight, ArrowsDownUp, ArrowLeft, GithubLogo, Trash, UsersThree } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER, isBlank, isForeignBlock, relativeTime } from "../lib/format";
import type { Block, BlockType, Note, NoteRelated, NoteSummary, Tag, TagUsage } from "../lib/types";
import { BlockCard } from "./BlockCard";
import type { MentionToken } from "./BlockCard";
import type { ImagePreview } from "./ImageModal";
import type { PdfPreview } from "./PdfModal";
import { KindMenu } from "./KindMenu";
import { MentionPalette } from "./MentionPalette";
import { NoteLinks } from "./NoteLinks";
import { ShareBadge } from "./ShareBadge";
import { ShareModal } from "./ShareModal";
import { TagPalette } from "./TagPalette";
import { TagRow } from "./TagRow";
import type { Toast, ToastKind } from "./ToastStack";
import { Key } from "./ui";

const SAVE_DELAY = 700;
const PICKER_LIMIT = 300;
const ORDER_KEY = "notai-note-order";

/** O conteúdo de um bloco: é o que uma escrita manda — e o que o rascunho leva junto ao nascer. */
const contentOf = (
  block: Block,
): Pick<Block, "type" | "text" | "language" | "url" | "caption"> => ({
  type: block.type,
  text: block.text,
  language: block.language,
  url: block.url,
  caption: block.caption,
});

/** O que o aviso oferece: o rótulo do botão e o que ele faz. */
type ToastAction = NonNullable<Toast["action"]>;

interface NoteEditorProps {
  note: Note;
  tags: TagUsage[];
  anchorBlockId: number | null;
  onBack: () => void;
  onOpenNote: (noteId: number, blockId: number | null) => void;
  onWorkspaceChange: () => void | Promise<void>;
  onCreateTag: (name: string) => Promise<Tag | null>;
  onToggleTag: (tagId: number, attached: boolean) => void | Promise<void>;
  onRenameNote: (title: string) => void | Promise<void>;
  onDeleteNote: () => void;
  onNotify: (message: string, kind?: ToastKind, action?: ToastAction) => void;
  onOpenImage: (image: ImagePreview) => void;
  onOpenPdf: (pdf: PdfPreview) => void;
  onError: (error: unknown) => void;
}

export function NoteEditor({
  note,
  tags,
  anchorBlockId,
  onBack,
  onOpenNote,
  onWorkspaceChange,
  onCreateTag,
  onToggleTag,
  onRenameNote,
  onDeleteNote,
  onNotify,
  onOpenImage,
  onOpenPdf,
  onError,
}: NoteEditorProps) {
  const [blocks, setBlocks] = useState<Block[]>(note.blocks);
  const [activeId, setActiveId] = useState<number>(note.blocks.at(-1)?.id ?? 0);
  const [paletteFor, setPaletteFor] = useState<number | null>(null);
  const [kindMenuFor, setKindMenuFor] = useState<number | null>(null);
  const [title, setTitle] = useState(note.title);
  const [shareOpen, setShareOpen] = useState(false);
  /** O bloco ativo em ref: a limpeza roda em callback e não pode apagar o que está em edição. */
  const activeRef = useRef<number>(activeId);
  /** A nota na tela: escritas assíncronas não podem tocar no caderno que já saiu. */
  const noteIdRef = useRef(note.id);
  noteIdRef.current = note.id;
  /** Fila das escritas que mexem na lista de blocos — ver `enqueue`. */
  const writeChain = useRef<Promise<void>>(Promise.resolve());
  /** Rascunho já gravado → id da linha no banco. O id local não muda, então a linha não é remontada. */
  const realIds = useRef(new Map<number, number>());
  /** Gravações de rascunho em voo, por id local: dois saves do mesmo bloco não criam duas linhas. */
  const creates = useRef(new Map<number, Promise<void>>());
  /** Contador dos ids locais de rascunho — negativos, nunca colidem com um id do banco. */
  const draftSeq = useRef(0);
  const [gistUrl, setGistUrl] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  // A nota pode ser de outra conta (chegou por grupo): só o dono apaga, e quem só lê não escreve —
  // a tela não oferece o que a API nega.
  const isOwner = note.role === "owner";
  const totalBlocks = Object.values(note.counts).reduce((total, count) => total + count, 0);
  const canEdit = note.role !== "viewer";
  // A API separa as duas coisas: `editor` escreve blocos e aplica tags, mas renomear (PATCH) e
  // apagar a nota são do dono — a tela não oferece o que a rota nega.
  const canRename = isOwner;
  const isShared = note.shared || note.shared_groups.length > 0;
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [focusId, setFocusId] = useState<number | null>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const [related, setRelated] = useState<NoteRelated | null>(null);
  const [mentionFor, setMentionFor] = useState<(MentionToken & { blockId: number }) | null>(null);
  const [relateOpen, setRelateOpen] = useState(false);
  const [noteRefs, setNoteRefs] = useState<NoteSummary[]>([]);
  /** Display order only: the note keeps its positions, and the choice sticks in the browser. */
  const [newestFirst, setNewestFirst] = useState(() => localStorage.getItem(ORDER_KEY) === "newest");

  const blocksRef = useRef<Block[]>(note.blocks);
  const draggingRef = useRef<number | null>(null);
  const closedMention = useRef<{ blockId: number; start: number } | null>(null);
  const elements = useRef(new Map<number, HTMLElement>());
  const timers = useRef(new Map<number, number>());
  const changeRef = useRef(onWorkspaceChange);
  changeRef.current = onWorkspaceChange;
  const errorRef = useRef(onError);
  errorRef.current = onError;
  const notifyRef = useRef(onNotify);
  notifyRef.current = onNotify;

  const loadRelated = useCallback(async () => {
    try {
      setRelated(await api.noteRelated(note.id));
    } catch (error) {
      errorRef.current(error);
    }
  }, [note.id]);
  const relatedRef = useRef(loadRelated);
  relatedRef.current = loadRelated;

  useEffect(() => {
    void loadRelated();
  }, [loadRelated]);

  useEffect(() => {
    localStorage.setItem(ORDER_KEY, newestFirst ? "newest" : "oldest");
  }, [newestFirst]);

  /** Blocks in the order they are drawn: the note's own order, or newest on top. */
  const shown = newestFirst ? [...blocks].reverse() : blocks;
  const positionOf = new Map(blocks.map((block, index) => [block.id, index]));

  // O gist da nota, se ela já foi publicada: o botão vira "abrir" e o link fica à mão.
  useEffect(() => {
    let cancelled = false;
    void api
      .githubStatus()
      .then((status) => {
        if (cancelled) return;
        setGistUrl(status.published.find((entry) => entry.note_id === note.id)?.url ?? null);
      })
      .catch(() => undefined); // sem token, ou API fora: o botão de publicar continua ali
    return () => {
      cancelled = true;
    };
  }, [note.id]);

  // Reset only when another note (or another anchor) is opened; refetches must not clobber typing.
  useEffect(() => {
    activeRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    const anchored =
      anchorBlockId !== null && note.blocks.some((block) => block.id === anchorBlockId)
        ? anchorBlockId
        : null;
    // Nota sem bloco nenhum abre com um rascunho: o editor sempre tem onde escrever, e o rascunho
    // não é uma linha em branco no banco — ele só nasce quando alguém escreve nele.
    const loaded = note.blocks.length === 0 && canEdit ? [draft("text")] : note.blocks;
    const target = anchored ?? loaded.at(-1)?.id ?? 0;
    setBlocks(loaded);
    blocksRef.current = loaded;
    setTitle(note.title);
    setActiveId(target);
    setFocusId(target || null);
    setHighlightId(anchored);
    // O que já estava vazio no banco (dado antigo) sai ao abrir a nota.
    if (note.blocks.some((block) => isBlank(block) && !isForeignBlock(block)))
      void pruneBlocks(loaded, note.id, true);
    if (anchored !== null) {
      const timer = window.setTimeout(() => setHighlightId(null), 2200);
      return () => window.clearTimeout(timer);
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note.id, anchorBlockId]);

  useEffect(() => {
    if (focusId === null) return;
    const element = elements.current.get(focusId);
    element?.focus();
    if (element instanceof HTMLTextAreaElement) {
      element.setSelectionRange(element.value.length, element.value.length);
    }
    setFocusId(null);
  }, [focusId, blocks]);

  /** O id da linha no banco: o do bloco, ou o que o rascunho ganhou ao ser gravado. */
  const realIdOf = (block: Pick<Block, "id">): number | null =>
    block.id > 0 ? block.id : realIds.current.get(block.id) ?? null;

  /**
   * O bloco novo da tela: id local negativo e **nenhuma linha no banco**.
   *
   * O caderno não guarda bloco em branco, então o bloco nasce aqui e só vira linha quando alguém
   * escreve nele (`flush`). Recarregar a página com um bloco vazio abandonado não traz nada de volta.
   */
  const draft = (kind: BlockType): Block => {
    draftSeq.current -= 1;
    const now = new Date().toISOString();
    return {
      id: draftSeq.current,
      note_id: noteIdRef.current,
      position: 0,
      type: kind,
      text: "",
      language: "",
      url: "",
      caption: "",
      author: "",
      created_at: now,
      updated_at: now,
    };
  };

  /** Onde escrever quando a tela ficou sem bloco nenhum: um rascunho de texto, já focado. */
  const seedDraft = (): Block[] => {
    const fresh = draft("text");
    setActiveId(fresh.id);
    setFocusId(fresh.id);
    return [fresh];
  };

  /**
   * Escritas que mexem na lista de blocos — limpeza, criação e arrasto — entram nesta fila: uma por
   * vez, a seguinte já enxerga o resultado da anterior. Em paralelo, duas limpezas decidiam "fica
   * um" sobre a mesma lista e podiam apagar todos os blocos.
   */
  const enqueue = useCallback(<T,>(job: () => Promise<T>): Promise<T> => {
    const run = writeChain.current.then(job);
    writeChain.current = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }, []);

  /** A ordem do banco é a da tela; o rascunho que ainda não virou linha fica fora da lista. */
  const reorder = useCallback(
    () =>
      enqueue(async () => {
        const ids = blocksRef.current
          .map((block) => realIdOf(block))
          .filter((id): id is number => id !== null);
        if (ids.length > 0) await api.reorderBlocks(noteIdRef.current, ids);
      }),
    [enqueue],
  );

  /**
   * Grava o rascunho: a linha nasce já com o que foi escrito nele, e o id local continua o mesmo —
   * a linha não é remontada no meio da digitação e o cursor fica onde está.
   */
  const persist = useCallback(
    (block: Block): Promise<void> => {
      const running = creates.current.get(block.id);
      if (running) return running;
      const job = (async () => {
        const latest = blocksRef.current.find((item) => item.id === block.id) ?? block;
        const created = await api.createBlock(noteIdRef.current, contentOf(latest));
        realIds.current.set(block.id, created.id);
        await reorder();
        await changeRef.current();
        await relatedRef.current(); // a menção escrita agora já vale
      })().finally(() => creates.current.delete(block.id));
      creates.current.set(block.id, job);
      return job;
    },
    [enqueue, reorder],
  );

  const flush = useCallback(
    async (id: number) => {
      const timer = timers.current.get(id);
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timers.current.delete(id);
      }
      const block = blocksRef.current.find((item) => item.id === id);
      if (!block) return;
      try {
        const real = realIdOf(block);
        if (real === null) {
          // Rascunho em branco é só a linha em branco da tela: não vira linha no banco.
          if (!isBlank(block)) await persist(block);
          return;
        }
        await api.updateBlock(real, contentOf(block));
        await changeRef.current();
        await relatedRef.current(); // a saved `[[…]]` changes what this note cites
      } catch (error) {
        errorRef.current(error);
      }
    },
    [persist],
  );

  /** Esquece o save pendente de um bloco: a linha está saindo, o PATCH chegaria tarde. */
  const cancelPending = (id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  };

  /**
   * Bloco em branco não fica no caderno.
   *
   * O bloco novo já nasce rascunho, então aqui só cai o que **virou linha e ficou sem conteúdo** —
   * o que foi apagado depois de salvo e o que já estava em branco de antes. Ao abrir a nota a lista
   * vem do banco; ao sair, a lista da tela é lida na hora. Bloco de outra conta fica de fora: quem
   * apaga o dele é quem escreveu, e o vazio dele não é meu para mexer.
   */
  const doPrune = useCallback(
    async (list: Block[], noteId: number, touchLocal: boolean): Promise<void> => {
      const doomed = list
        .map((block) => ({ block, id: realIdOf(block) }))
        .filter(
          (entry): entry is { block: Block; id: number } =>
            entry.id !== null && isBlank(entry.block) && !isForeignBlock(entry.block),
        );
      if (doomed.length === 0) return;
      doomed.forEach((entry) => cancelPending(entry.block.id));
      try {
        await Promise.all(doomed.map((entry) => api.deleteBlock(entry.id)));
      } catch (error) {
        errorRef.current(error);
        return;
      }
      doomed.forEach((entry) => realIds.current.delete(entry.block.id));
      // A lista da tela só é mexida se a nota da limpeza ainda é a que está aberta: a limpeza da nota
      // que saiu roda depois de a próxima já ter entrado no lugar dela.
      if (!touchLocal || noteIdRef.current !== noteId) {
        await changeRef.current();
        return;
      }
      const gone = new Set(doomed.map((entry) => entry.block.id));
      const next = blocksRef.current.filter((block) => !gone.has(block.id));
      if (next.length === 0) {
        applyLocal(seedDraft());
      } else {
        applyLocal(next);
        const last = next.at(-1);
        if (last && !next.some((block) => block.id === activeRef.current)) setActiveId(last.id);
      }
      await changeRef.current();
    },
    [enqueue],
  );

  const pruneBlocks = useCallback(
    (list: Block[], noteId: number, touchLocal: boolean): Promise<void> =>
      enqueue(() => doPrune(list, noteId, touchLocal)),
    [enqueue, doPrune],
  );

  const applyLocal = (next: Block[]) => {
    blocksRef.current = next;
    setBlocks(next);
  };

  const patch = (id: number, changes: Partial<Block>) => {
    applyLocal(blocksRef.current.map((block) => (block.id === id ? { ...block, ...changes } : block)));
    const timer = timers.current.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timers.current.set(id, window.setTimeout(() => void flush(id), SAVE_DELAY));
  };

  /** Bloco novo entra na tela como rascunho: quem grava é o primeiro conteúdo escrito nele. */
  const insertAfter = (block: Block, kind: BlockType) => {
    const next = [...blocksRef.current];
    const at = next.findIndex((item) => item.id === block.id) + 1;
    const fresh = draft(kind);
    next.splice(at, 0, fresh);
    applyLocal(next);
    setActiveId(fresh.id);
    setFocusId(fresh.id);
  };

  const append = (kind: BlockType) => {
    const last = blocksRef.current.at(-1);
    if (last) {
      insertAfter(last, kind);
      return;
    }
    const fresh = draft(kind);
    applyLocal([fresh]);
    setActiveId(fresh.id);
    setFocusId(fresh.id);
  };

  // Sair da nota (ou da tela) leva junto o que ficou vazio no caderno antigo — inclusive o bloco
  // que estava em edição: ninguém vai escrever nele, e o banco não é lugar de bloco em branco. A
  // lista é lida aqui dentro, na hora da saída, porque é ela que ainda tem o caderno que está saindo.
  useEffect(() => {
    const noteId = note.id;
    return () => {
      void pruneBlocks(blocksRef.current, noteId, false);
    };
  }, [note.id, pruneBlocks]);

  // Outgoing saves must not be lost when the view changes.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      const ids = [...pending.keys()];
      pending.forEach((timer) => window.clearTimeout(timer));
      pending.clear();
      for (const id of ids) void flush(id);
    };
  }, [flush]);

  /**
   * Apaga o bloco — e oferece o desfazer no mesmo gesto, que é o que uma ação destrutiva pede:
   * o aviso guarda o que saiu e onde estava, e devolve no lugar de origem.
   */
  const remove = async (id: number) => {
    if (blocksRef.current.length <= 1) return;
    const list = blocksRef.current;
    const index = list.findIndex((block) => block.id === id);
    const block = list[index];
    const previous = list[index - 1] ?? list[index + 1];
    const order = list.map((item) => item.id);
    cancelPending(id);
    try {
      const flying = creates.current.get(block.id);
      if (flying) await flying; // a linha pode ter nascido no meio do gesto
      const real = realIdOf(block);
      if (real !== null) await api.deleteBlock(real);
      realIds.current.delete(block.id);
      applyLocal(list.filter((item) => item.id !== id));
      if (previous) {
        setActiveId(previous.id);
        setFocusId(previous.id);
      }
      await changeRef.current();
      notifyRef.current("Bloco apagado.", "info", { label: "Desfazer", run: () => void restore(block, order) });
    } catch (error) {
      errorRef.current(error);
    }
  };

  /** Recria o bloco apagado com o mesmo conteúdo, na mesma posição da nota. */
  const restore = async (block: Block, order: number[]) => {
    // O lugar é o de antes: basta entrar logo antes de quem vinha depois dele (ou no fim, se era
    // o último). Ancorar no vizinho sobrevivente aguenta bem melhor do que um índice guardado.
    const after = order[order.indexOf(block.id) + 1];
    const put = (restored: Block) => {
      const current = blocksRef.current;
      const heir = current.findIndex((item) => item.id === after);
      const next = [...current];
      next.splice(heir === -1 ? current.length : heir, 0, restored);
      applyLocal(next);
      setActiveId(restored.id);
      setFocusId(restored.id);
    };
    try {
      // Rascunho nunca virou linha: desfazer devolve ele mesmo, sem tocar no banco.
      if (realIdOf(block) === null) {
        put(block);
        return;
      }
      const created = await api.createBlock(noteIdRef.current, contentOf(block));
      put(created);
      await reorder();
      await changeRef.current();
    } catch (error) {
      errorRef.current(error);
    }
  };

  /** Opens the note picker with this user's notes; the palette filters them locally. */
  const openPicker = async () => {
    try {
      setNoteRefs(await api.listNotes("", PICKER_LIMIT));
    } catch (error) {
      errorRef.current(error);
    }
  };

  const handleMention = (blockId: number, token: MentionToken | null) => {
    if (token === null) {
      setMentionFor(null);
      return;
    }
    const closed = closedMention.current;
    if (closed && closed.blockId === blockId && closed.start === token.start) return;
    closedMention.current = null;
    setMentionFor({ ...token, blockId });
    if (noteRefs.length === 0) void openPicker();
  };

  const insertMention = (picked: NoteSummary) => {
    const token = mentionFor;
    if (!token) return;
    const block = blocksRef.current.find((item) => item.id === token.blockId);
    if (!block) return;
    setMentionFor(null);
    patch(token.blockId, {
      text: `${block.text.slice(0, token.start)}[[${picked.title}]]${block.text.slice(token.end)}`,
    });
    setFocusId(token.blockId);
  };

  const relate = async (picked: NoteSummary, label: string) => {
    setRelateOpen(false);
    try {
      setRelated(await api.createRelation(note.id, picked.id, label));
      await changeRef.current();
    } catch (error) {
      errorRef.current(error);
    }
  };

  const removeRelation = async (relationId: number) => {
    try {
      setRelated(await api.deleteRelation(note.id, relationId));
      await changeRef.current();
    } catch (error) {
      errorRef.current(error);
    }
  };

  const dropOn = async (targetId: number) => {
    const sourceId = draggingRef.current;
    draggingRef.current = null;
    setDraggingId(null);
    if (sourceId === null || sourceId === targetId) return;
    // The drag happens in what the user sees; the stored order is always the note's own.
    const displayed = newestFirst ? [...blocksRef.current].reverse() : [...blocksRef.current];
    const from = displayed.findIndex((block) => block.id === sourceId);
    const to = displayed.findIndex((block) => block.id === targetId);
    if (from < 0 || to < 0) return;
    const [moved] = displayed.splice(from, 1);
    displayed.splice(to, 0, moved);
    const ordered = newestFirst ? displayed.reverse() : displayed;
    applyLocal(ordered);
    try {
      await reorder();
    } catch (error) {
      errorRef.current(error);
    }
  };

  /** "/" on a blank block converts it; on a block with content it appends a new one of that kind. */
  const applyKind = (block: Block, kind: BlockType) => {
    setKindMenuFor(null);
    setActiveId(block.id);
    // Bloco de outra conta não se converte: o tipo dele é do autor, então o tipo escolhido vira um
    // bloco novo, meu, logo depois.
    if (isBlank(block) && !isForeignBlock(block)) {
      patch(block.id, { type: kind });
      setFocusId(block.id);
      return;
    }
    insertAfter(block, kind);
  };

  /**
   * Publica (ou atualiza) o gist desta nota. O GitHub só responde a quem tem token salvo — sem ele o
   * painel do GitHub explica o caminho, e o erro aparece no toast.
   */
  const publish = async () => {
    setPublishing(true);
    try {
      const result = await api.publishGist(note.id);
      setGistUrl(result.url);
      onNotify(
        result.updated ? "Gist atualizado no GitHub" : "Nota publicada como gist (secreto)",
        "success",
      );
    } catch (error) {
      onError(error);
    } finally {
      setPublishing(false);
    }
  };

  const continueWriting = () => {
    const last = blocksRef.current.at(-1);
    if (!last) {
      append("text");
      return;
    }
    setActiveId(last.id);
    setFocusId(last.id);
    if (isBlank(last)) return;
    append("text");
  };

  /** The "keep writing" strip rides along with the order: it sits where the next block lands. */
  const tail = (
    <div
      className="editor-tail"
      onClick={continueWriting}
      title="Continuar escrevendo aqui"
    >
      <span className="editor-tail-hint">
        Clique para continuar escrevendo, ou digite / para escolher o tipo
      </span>
    </div>
  );

  /** Icons + shortcuts close the note in the normal order; inverted, they open it. */
  const tools = (
    <div className="editor-tools">
      <div className="block-adder">
        {KIND_ORDER.map((kind) => {
          const KindIcon = KIND_ICONS[kind];
          return (
            <button
              key={kind}
              type="button"
              className="btn btn-kind"
              onClick={() => void append(kind)}
              title={`Novo bloco de ${KIND_LABELS[kind]}`}
              aria-label={`Novo bloco de ${KIND_LABELS[kind]}`}
            >
              <KindIcon size={15} weight="bold" />
            </button>
          );
        })}
      </div>

      <footer className="hintbar">
        <span className="hint">
          <Key>/</Key> tipo do bloco
        </span>
        <span className="hint">
          <Key>#</Key> tag
        </span>
        <span className="hint">
          <Key>[[</Key> cita uma nota
        </span>
        <span className="hint">
          <Key>Enter</Key> novo bloco
        </span>
        <span className="hint">
          <Key>Ctrl</Key>
          <Key>K</Key> busca
        </span>
        <span className="hint">
          <Key>Ctrl</Key>
          <Key>/</Key> atalhos
        </span>
      </footer>
    </div>
  );

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const active = blocksRef.current.find((block) => block.id === activeId) ?? blocksRef.current[0];
    if (!active) return;
    const target = event.target;
    // Overlays (tag palette, kind menu) own their own keys; header inputs are not block fields.
    if (target instanceof HTMLElement && target.closest(".palette, .kind-menu")) return;
    const insideBlock = target instanceof HTMLElement && target.closest(".block") !== null;
    const blankField =
      insideBlock &&
      (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) &&
      target.value === "";
    const noModifier = !event.ctrlKey && !event.metaKey && !event.altKey;

    if (event.key === "Escape") {
      if (kindMenuFor !== null) setKindMenuFor(null);
      else if (paletteFor !== null) setPaletteFor(null);
      return;
    }

    // O bloco de outra conta é leitura: nem menu de tipo, nem a lixeira do Backspace mexem nele.
    const mine = !isForeignBlock(active);

    // Ctrl+Shift+L: same menu, for cursor-in-the-middle-of-text cases.
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "l") {
      event.preventDefault();
      setPaletteFor(null);
      setActiveId(active.id);
      setKindMenuFor(active.id);
      return;
    }

    if (noModifier && blankField && mine && event.key === "/") {
      event.preventDefault();
      setPaletteFor(null);
      setActiveId(active.id);
      setKindMenuFor(active.id);
      return;
    }

    if (noModifier && blankField && mine && event.key === "#") {
      event.preventDefault();
      setKindMenuFor(null);
      setActiveId(active.id);
      setPaletteFor(active.id);
      return;
    }

    if (event.key === "Enter" && insideBlock) {
      const plainEnter = !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey;
      const altEnter = event.altKey && !event.shiftKey;
      if ((plainEnter && active.type !== "code") || altEnter) {
        event.preventDefault();
        // Bloco vazio não gera outro bloco vazio: escreva neste, ou troque o tipo com `/`. Bloco de
        // outra conta é a exceção — não dá para escrever nele, então o novo é o caminho para seguir.
        if (isBlank(active) && !isForeignBlock(active)) return;
        insertAfter(active, active.type);
        return;
      }
    }

    if (event.key === "Backspace" && insideBlock && mine && blocksRef.current.length > 1 && isBlank(active)) {
      event.preventDefault();
      void remove(active.id);
    }
  };

  return (
    <div className="view editor" onKeyDown={handleKeyDown}>
      <header className="editor-head">
        <div className="editor-head-bar">
          <button type="button" className="btn btn-ghost btn-back" onClick={onBack}>
            <ArrowLeft size={15} />
            Notas
          </button>
          <button
            type="button"
            className={newestFirst ? "icon-btn is-on" : "icon-btn"}
            onClick={() => setNewestFirst((current) => !current)}
            aria-pressed={newestFirst}
            title={
              newestFirst
                ? "Ordem normal: blocos mais antigos primeiro"
                : "Inverter: blocos mais novos primeiro"
            }
            aria-label={
              newestFirst
                ? "Voltar à ordem normal dos blocos"
                : "Inverter a ordem dos blocos, mais novos primeiro"
            }
          >
            <ArrowsDownUp size={16} weight="bold" />
          </button>
        </div>
        {/* Título e tags na mesma linha: a nota é uma coisa só, e as tags são parte do nome dela. */}
        <div className="note-head">
          <input
            className={canRename ? "note-title-input" : "note-title-input is-readonly"}
            value={title}
            placeholder="Título da nota"
            maxLength={200}
            readOnly={!canRename}
            title={canRename ? undefined : "Só o dono renomeia a nota"}
            onChange={(event) => setTitle(event.target.value)}
            onBlur={() => title !== note.title && void onRenameNote(title)}
          />
          <TagRow
            attached={note.tags}
            all={tags}
            onCreate={onCreateTag}
            onToggle={(tag, attached) => void onToggleTag(tag.id, attached)}
            readOnly={!canEdit}
          />
        </div>
        <p className="note-meta">
          {/*
            Nota compartilhada não tem botão: o **chip** é o botão. Sem compartilhamento (e sendo eu o
            dono), aí sim aparece **Compartilhar** — é o único caminho para abrir o painel.
          */}
          <ShareBadge note={note} onClick={() => setShareOpen(true)} />
          {isOwner && !isShared && (
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              onClick={() => setShareOpen(true)}
              title="Compartilhar a nota com um grupo"
            >
              <UsersThree size={15} />
              Compartilhar
            </button>
          )}
          <span>
            {totalBlocks} {totalBlocks === 1 ? "bloco" : "blocos"}
          </span>
          <span>atualizado {relativeTime(note.updated_at)}</span>
          <span className="note-meta-actions">
            {isOwner && (
              <button
                type="button"
                className="icon-btn"
                disabled={publishing}
                onClick={() => void publish()}
                title={gistUrl ? "Atualizar o gist desta nota" : "Publicar esta nota como gist"}
                aria-label={gistUrl ? "Atualizar o gist" : "Publicar como gist"}
              >
                <GithubLogo size={15} weight="bold" />
              </button>
            )}
            {gistUrl && (
              <a
                className="icon-btn"
                href={gistUrl}
                target="_blank"
                rel="noreferrer"
                title="Abrir o gist no GitHub"
                aria-label="Abrir o gist"
              >
                <ArrowUpRight size={15} weight="bold" />
              </a>
            )}
            {isOwner && (
              <button
                type="button"
                className="icon-btn is-danger"
                onClick={onDeleteNote}
                title="Apagar nota"
                aria-label="Apagar nota"
              >
                <Trash size={15} />
              </button>
            )}
          </span>
        </p>
      </header>

      {canEdit && newestFirst && tools}
      {canEdit && newestFirst && tail}

      <div className="block-list">
        {shown.map((block) => (
          <div className="block-wrap" key={block.id}>
            <BlockCard
              block={block}
              index={positionOf.get(block.id) ?? 0}
              active={block.id === activeId}
              dragging={block.id === draggingId}
              highlighted={block.id === highlightId}
              onActivate={() => setActiveId(block.id)}
              onDeactivate={() => setActiveId(0)}
              onPatch={(changes) => patch(block.id, changes)}
              onDelete={() => void remove(block.id)}
              onRegisterRef={(element) => {
                if (element) elements.current.set(block.id, element);
                else elements.current.delete(block.id);
              }}
              onDragStart={() => {
                draggingRef.current = block.id;
                setDraggingId(block.id);
              }}
              onDragEnd={() => {
                draggingRef.current = null;
                setDraggingId(null);
              }}
              onDropOn={() => void dropOn(block.id)}
              onUploadError={onError}
              onKindClick={() => {
                setPaletteFor(null);
                setActiveId(block.id);
                setKindMenuFor(block.id);
              }}
              onMention={(token) => handleMention(block.id, token)}
              onOpenImage={onOpenImage}
              onOpenPdf={onOpenPdf}
            />
            {kindMenuFor === block.id && (
              <KindMenu
                current={block.type}
                onPick={(kind) => applyKind(block, kind)}
                onClose={() => setKindMenuFor(null)}
              />
            )}
            {mentionFor?.blockId === block.id && (
              <MentionPalette
                notes={noteRefs.filter((ref) => ref.id !== note.id && ref.title.trim() !== "")}
                title="Citar nota"
                emptyHint="Nenhuma nota com esse título. Crie a nota e cite de novo."
                onPick={(picked) => insertMention(picked)}
                onClose={() => {
                  closedMention.current = { blockId: block.id, start: mentionFor.start };
                  setMentionFor(null);
                }}
              />
            )}
            {paletteFor === block.id && (
              <TagPalette
                all={tags}
                attachedIds={note.tags.map((tag) => tag.id)}
                onPick={(tag, attached) => void onToggleTag(tag.id, attached)}
                onCreate={onCreateTag}
                onClose={() => setPaletteFor(null)}
              />
            )}
          </div>
        ))}
      </div>

      {canEdit && !newestFirst && tail}
      {canEdit && !newestFirst && tools}

      {shareOpen && (
        <ShareModal
          note={note}
          onClose={() => setShareOpen(false)}
          onChanged={() => void onWorkspaceChange()}
          onError={onError}
          onNotify={onNotify}
        />
      )}

      {related && (
        <NoteLinks
          related={related}
          onOpenNote={(noteId) => onOpenNote(noteId, null)}
          onRelate={() => {
            setRelateOpen(true);
            void openPicker();
          }}
          onRemoveRelation={(relationId) => void removeRelation(relationId)}
        />
      )}

      {relateOpen && (
        <MentionPalette
          notes={noteRefs.filter(
            (ref) =>
              ref.id !== note.id &&
              ref.title.trim() !== "" &&
              !(related?.relations ?? []).some((relation) => relation.other.id === ref.id),
          )}
          title="Relacionar com"
          withLabel
          inline
          emptyHint="Nenhuma nota disponível com esse título."
          onPick={(picked, label) => void relate(picked, label)}
          onClose={() => setRelateOpen(false)}
        />
      )}
    </div>
  );
}
