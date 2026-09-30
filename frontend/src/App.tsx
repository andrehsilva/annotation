import { useCallback, useEffect, useRef, useState } from "react";

import { AdminView } from "./components/AdminView";
import { CommandPalette } from "./components/CommandPalette";
import { ConfirmDialog } from "./components/ConfirmDialog";
import type { ConfirmRequest } from "./components/ConfirmDialog";
import { KindView } from "./components/KindView";
import { ImageModal } from "./components/ImageModal";
import type { ImagePreview } from "./components/ImageModal";
import { LoginView } from "./components/LoginView";
import { NoteEditor } from "./components/NoteEditor";
import { NotesView } from "./components/NotesView";
import { PasswordPanel } from "./components/PasswordPanel";
import { PdfModal } from "./components/PdfModal";
import type { PdfPreview } from "./components/PdfModal";
import { RelationsView } from "./components/RelationsView";
import { ShortcutsModal } from "./components/ShortcutsModal";
import { Sidebar } from "./components/Sidebar";
import { TagsView } from "./components/TagsView";
import { ToastStack } from "./components/ToastStack";
import type { Toast, ToastKind } from "./components/ToastStack";
import { TopBar } from "./components/TopBar";
import { WelcomeView } from "./components/WelcomeView";
import { Spinner } from "./components/ui";
import { ApiError, api } from "./lib/api";
import { noteMatches } from "./lib/format";
import { useTheme } from "./lib/theme";
import type {
  BlockType,
  EventFeed,
  Note,
  NoteSummary,
  SearchHit,
  Stats,
  Tag,
  TagUsage,
  User,
} from "./lib/types";

export type View =
  | { kind: "notes" }
  | { kind: "note"; id: number }
  | { kind: "kind"; blockType: BlockType }
  | { kind: "tags" }
  | { kind: "relations" }
  | { kind: "welcome" }
  | { kind: "admin" };

const TOAST_MS: Record<ToastKind, number> = { info: 4000, success: 4000, error: 7000 };

export default function App() {
  const { theme, setTheme } = useTheme();
  const [user, setUser] = useState<User | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [tags, setTags] = useState<TagUsage[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  /** A nota aberta no editor; a lista vive em `notes`. */
  const [note, setNote] = useState<Note | null>(null);
  const [anchorBlock, setAnchorBlock] = useState<number | null>(null);
  const [view, setView] = useState<View>({ kind: "tags" });
  const [ready, setReady] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [feed, setFeed] = useState<EventFeed | null>(null);
  const [bellOpen, setBellOpen] = useState(false);
  const [image, setImage] = useState<ImagePreview | null>(null);
  const [pdf, setPdf] = useState<PdfPreview | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => localStorage.getItem("notai-sidebar") !== "closed",
  );
  const toastSeq = useRef(0);
  /** O painel abre sozinho no máximo uma vez por login (e só se houver o que mostrar). */
  const bellAutoOpened = useRef(false);

  useEffect(() => {
    localStorage.setItem("notai-sidebar", sidebarOpen ? "open" : "closed");
  }, [sidebarOpen]);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, kind: ToastKind = "info") => {
      const id = (toastSeq.current += 1);
      setToasts((current) => [...current, { id, kind, message }]);
      window.setTimeout(() => dismissToast(id), TOAST_MS[kind]);
    },
    [dismissToast],
  );

  const askConfirm = useCallback((request: ConfirmRequest) => setConfirmRequest(request), []);

  /** Drops everything that belongs to the signed-in user: logout, and a dead cookie mid-session. */
  const resetWorkspace = useCallback(() => {
    setFilter("");
    // Back to the startup view; the next login opens its own first note.
    setView({ kind: "tags" });
    setNotes([]);
    setTags([]);
    setStats(null);
    setNote(null);
    setAnchorBlock(null);
    setPasswordOpen(false);
    // O próximo login busca o feed dele e pode abrir o painel uma vez.
    setFeed(null);
    setBellOpen(false);
    bellAutoOpened.current = false;
    // Numa máquina compartilhada nada do usuário anterior pode sobrar por cima da tela de entrada.
    setToasts([]);
    setImage(null);
    setPdf(null);
    setSearchOpen(false);
    setShortcutsOpen(false);
    setReady(false);
  }, []);

  const report = useCallback(
    (error: unknown) => {
      console.error(error);
      if (error instanceof ApiError && error.status === 401) {
        // The cookie died under us: back to the login screen instead of a toast per request.
        resetWorkspace();
        setUser(null);
        return;
      }
      notify(
        error instanceof ApiError ? error.message : "Falha ao falar com a API local",
        "error",
      );
    },
    [notify, resetWorkspace],
  );

  const refreshWorkspace = useCallback(async () => {
    const [list, tagList, workspaceStats] = await Promise.all([
      api.listNotes(),
      api.listTags(),
      api.stats(),
    ]);
    setNotes(list);
    setTags(tagList);
    setStats(workspaceStats);
    return list;
  }, []);

  /** O feed do sino não é polled: uma busca por carga de workspace, e outra a cada abertura. */
  const loadEvents = useCallback(async (): Promise<EventFeed | null> => {
    try {
      const next = await api.events(5);
      setFeed(next);
      return next;
    } catch (error) {
      report(error);
      return null;
    }
  }, [report]);

  const changeBell = useCallback(
    (next: boolean) => {
      setBellOpen(next);
      if (next) void loadEvents();
    },
    [loadEvents],
  );

  /** Fechar o painel é o "vi tudo": o contador cai para zero assim que a API confirma. */
  const markEventsRead = useCallback(() => {
    void api
      .markEventsRead()
      .then(() => setFeed((current) => (current ? { ...current, unread: 0 } : current)))
      .catch(report);
  }, [report]);

  /** One session at a time: nothing of the old user survives the login screen. */
  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (error) {
      report(error);
    }
    resetWorkspace();
    setUser(null);
  }, [report, resetWorkspace]);

  /** Abrir uma nota é o único "navegar" que existe: a nota é a unidade do app. */
  const openNote = useCallback(async (id: number, blockId: number | null = null) => {
    setAnchorBlock(blockId);
    setNote(await api.getNote(id));
    setView({ kind: "note", id });
  }, []);

  /**
   * O botão do fim da introdução: grava a marca na conta e leva o usuário para a primeira nota.
   * Se a API falhar, o aviso sai no toast e a tela não prende ninguém — o próximo login a reabre.
   */
  const dismissWelcome = useCallback(async () => {
    try {
      setUser(await api.dismissWelcome());
    } catch (error) {
      report(error);
    }
    const first = notes[0];
    if (first) await openNote(first.id);
    else setView({ kind: "notes" });
  }, [notes, openNote, report]);

  /** The cookie is the session: ask it who we are before loading anything of theirs. */
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const current = await api.me();
        if (!cancelled) setUser(current);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) setUser(null);
        else report(error);
      } finally {
        if (!cancelled) setCheckingSession(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [report]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    void (async () => {
      try {
        const list = await refreshWorkspace();
        if (cancelled) return;
        const first = list[0];
        // Primeiro login: a introdução abre na frente, com a nota esperando atrás dela.
        if (user.welcome_seen_at === null) setView({ kind: "welcome" });
        else if (first) await openNote(first.id);
        else setView({ kind: "notes" });
      } catch (error) {
        if (!cancelled) report(error);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    void loadEvents().then((next) => {
      if (cancelled || !next) return;
      // Só abre sozinho quando há interação para mostrar, e só na primeira vez do login.
      if (!bellAutoOpened.current && next.items.length > 0) {
        bellAutoOpened.current = true;
        setBellOpen(true);
      }
    });
    return () => {
      cancelled = true;
    };
    // `user.id` e não `user`: marcar a introdução troca o objeto sem que o login tenha mudado,
    // e o fluxo de entrada não pode rodar de novo por causa disso.
  }, [user?.id, openNote, refreshWorkspace, report, loadEvents]);

  /** Block edits change counters everywhere, so refresh the chrome after each mutation. */
  const syncAfterEdit = useCallback(async () => {
    const currentView = view;
    try {
      await refreshWorkspace();
      if (currentView.kind === "note") setNote(await api.getNote(currentView.id));
    } catch (error) {
      report(error);
    }
  }, [refreshWorkspace, report, view]);

  const createNote = useCallback(
    async (name = "") => {
      try {
        const created = await api.createNote(name);
        await refreshWorkspace();
        await openNote(created.id);
        notify("Nota criada. Digite / para escolher o tipo do bloco.", "success");
      } catch (error) {
        report(error);
      }
    },
    [notify, openNote, refreshWorkspace, report],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const key = event.key.toLowerCase();
      if (key === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      // `Ctrl+/` (e o `Ctrl+Shift+7`, que é o mesmo `?` de alguns teclados) abre a lista de atalhos.
      if (key === "/" || event.code === "Slash") {
        event.preventDefault();
        setShortcutsOpen((open) => !open);
      }
      // `Ctrl+Alt+N` cria uma nota: `Ctrl+N` e `Ctrl+Shift+N` são do navegador (janela e anônima).
      if (event.altKey && key === "n") {
        event.preventDefault();
        void createNote();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [createNote]);

  const deleteNote = useCallback(
    (id: number) => {
      const target = notes.find((item) => item.id === id);
      askConfirm({
        title: "Apagar nota",
        message: `“${target?.title || "Nota sem título"}” será apagada junto com os blocos, as tags e os vínculos dela. Não dá para desfazer.`,
        confirmLabel: "Apagar nota",
        danger: true,
        action: async () => {
          try {
            await api.deleteNote(id);
            const list = await refreshWorkspace();
            const next = list.find((item) => item.id !== id);
            if (next) await openNote(next.id);
            else {
              setNote(null);
              setView({ kind: "notes" });
            }
            notify("Nota apagada", "success");
          } catch (error) {
            report(error);
          }
        },
      });
    },
    [askConfirm, notes, notify, openNote, refreshWorkspace, report],
  );

  const renameNote = useCallback(
    async (id: number, title: string) => {
      try {
        setNote(await api.updateNote(id, { title }));
        await refreshWorkspace();
      } catch (error) {
        report(error);
      }
    },
    [refreshWorkspace, report],
  );

  const toggleNoteTag = useCallback(
    async (noteId: number, tagId: number, attached: boolean) => {
      try {
        setNote(
          attached
            ? await api.detachNoteTag(noteId, tagId)
            : await api.attachNoteTag(noteId, tagId),
        );
        await refreshWorkspace();
      } catch (error) {
        report(error);
      }
    },
    [refreshWorkspace, report],
  );

  const createTag = useCallback(
    async (name: string): Promise<Tag | null> => {
      try {
        const tag = await api.createTag(name);
        await refreshWorkspace();
        notify(`Tag "${tag.name}" criada`, "success");
        return tag;
      } catch (error) {
        report(error);
        return null;
      }
    },
    [notify, refreshWorkspace, report],
  );

  const deleteTag = useCallback(
    (tagId: number) => {
      const target = tags.find((item) => item.id === tagId);
      askConfirm({
        title: "Apagar tag",
        message: `"${target?.name ?? tagId}" sai de ${target?.notes_count ?? 0} nota(s). Não dá para desfazer.`,
        confirmLabel: "Apagar tag",
        danger: true,
        action: async () => {
          try {
            await api.deleteTag(tagId);
            await refreshWorkspace();
            notify("Tag apagada", "success");
          } catch (error) {
            report(error);
          }
        },
      });
    },
    [askConfirm, notify, refreshWorkspace, report, tags],
  );

  const openTag = useCallback(
    (name: string) => {
      const matches = notes.filter((entry) => noteMatches(entry, name)).length;
      setFilter(name);
      setSidebarOpen(true); // the filter lives in the side list, so it has to be on screen
      setView({ kind: "notes" });
      notify(
        matches === 0
          ? `Nenhuma nota com a tag "${name}"`
          : `${matches} nota${matches === 1 ? "" : "s"} com a tag "${name}"`,
        matches === 0 ? "info" : "success",
      );
    },
    [notes, notify],
  );

  const navigateHit = useCallback(
    async (hit: SearchHit) => {
      setSearchOpen(false);
      try {
        if (hit.kind === "tag") openTag(hit.title);
        else if (hit.note_id) await openNote(hit.note_id, hit.kind === "block" ? hit.id : null);
      } catch (error) {
        report(error);
      }
    },
    [openNote, openTag, report],
  );

  if (checkingSession) {
    return (
      <div className="app">
        <main className="main">
          <div className="view">
            <Spinner label="Verificando a sessão" />
          </div>
        </main>
      </div>
    );
  }

  if (!user) return <LoginView onLoggedIn={(loggedIn) => setUser(loggedIn)} />;

  const main = (() => {
    if (!ready) return <Spinner label="Falando com a API em /api" />;
    if (view.kind === "admin") {
      return (
        <AdminView
          user={user}
          onError={report}
          onNotify={notify}
          onAskConfirm={askConfirm}
        />
      );
    }
    if (view.kind === "welcome") {
      return <WelcomeView user={user} onDismiss={() => void dismissWelcome()} />;
    }
    if (view.kind === "note" && note) {
      return (
        <NoteEditor
          note={note}
          tags={tags}
          anchorBlockId={anchorBlock}
          onBack={() => setView({ kind: "notes" })}
          onOpenNote={(noteId, blockId) => void openNote(noteId, blockId)}
          onWorkspaceChange={syncAfterEdit}
          onCreateTag={createTag}
          onToggleTag={(tagId, attached) => void toggleNoteTag(note.id, tagId, attached)}
          onRenameNote={(title) => void renameNote(note.id, title)}
          onDeleteNote={() => deleteNote(note.id)}
          onOpenImage={setImage}
          onOpenPdf={setPdf}
          onNotify={notify}
          onError={report}
        />
      );
    }
    if (view.kind === "kind") {
      return (
        <KindView
          blockType={view.blockType}
          onOpenNote={(noteId, blockId) => void openNote(noteId, blockId)}
          onOpenImage={setImage}
          onOpenPdf={setPdf}
          onError={report}
        />
      );
    }
    if (view.kind === "tags") {
      return (
        <TagsView tags={tags} onOpenTag={openTag} onDeleteTag={deleteTag} />
      );
    }
    if (view.kind === "relations") {
      return (
        <RelationsView
          onOpenNote={(noteId) => void openNote(noteId)}
          onChanged={() => void refreshWorkspace()}
          onError={report}
          onNotify={notify}
          onAskConfirm={askConfirm}
        />
      );
    }
    return (
      <NotesView
        notes={notes.filter((entry) => noteMatches(entry, filter))}
        onOpenNote={(id) => void openNote(id)}
        onCreateNote={() => void createNote()}
      />
    );
  })();

  return (
    <div className="app">
      <TopBar
        view={view}
        stats={stats}
        theme={theme}
        user={user}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        onNavigate={setView}
        onHome={() => setView({ kind: "notes" })}
        onOpenSearch={() => setSearchOpen(true)}
        onToggleSidebar={() => setSidebarOpen((open) => !open)}
        onOpenAdmin={() => setView({ kind: "admin" })}
        onOpenWelcome={() => setView({ kind: "welcome" })}
        onLogout={() => void logout()}
        onChangePassword={() => setPasswordOpen(true)}
        feed={feed}
        bellOpen={bellOpen}
        onBellOpenChange={changeBell}
        onAllRead={markEventsRead}
        onNewNote={() => void createNote()}

        sidebarOpen={sidebarOpen}
      />
      <div className={sidebarOpen ? "app-body" : "app-body is-sidebar-hidden"}>
        {sidebarOpen && (
          <Sidebar
            notes={notes}
            stats={stats}
            view={view}
            filter={filter}
            onFilter={setFilter}
            onSelectNote={(id) => void openNote(id)}
            onCreateNote={() => void createNote()}
            onClose={() => setSidebarOpen(false)}
          />
        )}
        <main className="main" id="conteudo" tabIndex={-1}>{main}</main>
      </div>
      {searchOpen && (
        <CommandPalette onClose={() => setSearchOpen(false)} onNavigate={(hit) => void navigateHit(hit)} />
      )}
      {shortcutsOpen && <ShortcutsModal onClose={() => setShortcutsOpen(false)} />}
      {passwordOpen && (
        <PasswordPanel onClose={() => setPasswordOpen(false)} onNotify={notify} />
      )}
      {image && <ImageModal image={image} onClose={() => setImage(null)} />}
      {pdf && <PdfModal pdf={pdf} onClose={() => setPdf(null)} />}
      {confirmRequest && (
        <ConfirmDialog
          title={confirmRequest.title}
          message={confirmRequest.message}
          confirmLabel={confirmRequest.confirmLabel}
          danger={confirmRequest.danger}
          onCancel={() => setConfirmRequest(null)}
          onConfirm={() => {
            const { action } = confirmRequest;
            setConfirmRequest(null);
            void action();
          }}
        />
      )}
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
