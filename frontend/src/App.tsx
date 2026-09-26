import { useCallback, useEffect, useRef, useState } from "react";

import { AdminView } from "./components/AdminView";
import { CommandPalette } from "./components/CommandPalette";
import { ConfirmDialog } from "./components/ConfirmDialog";
import type { ConfirmRequest } from "./components/ConfirmDialog";
import { DrivePanel } from "./components/DrivePanel";
import { KindView } from "./components/KindView";
import { ImageModal } from "./components/ImageModal";
import type { ImagePreview } from "./components/ImageModal";
import { LoginView } from "./components/LoginView";
import { NoteEditor } from "./components/NoteEditor";
import { NotesView } from "./components/NotesView";
import { NotebookView } from "./components/NotebookView";
import { PasswordPanel } from "./components/PasswordPanel";
import { RelationsView } from "./components/RelationsView";
import { Sidebar } from "./components/Sidebar";
import { TagsView } from "./components/TagsView";
import { ToastStack } from "./components/ToastStack";
import type { Toast, ToastKind } from "./components/ToastStack";
import { TopBar } from "./components/TopBar";
import { Spinner } from "./components/ui";
import { ApiError, api } from "./lib/api";
import { notebookMatches } from "./lib/format";
import { useTheme } from "./lib/theme";
import type {
  BlockType,
  DriveStatus,
  EventFeed,
  Note,
  Notebook,
  NotebookSummary,
  SearchHit,
  Stats,
  Tag,
  TagUsage,
  User,
} from "./lib/types";

export type View =
  | { kind: "notebook"; id: number }
  | { kind: "note"; notebookId: number; id: number }
  | { kind: "kind"; blockType: BlockType }
  | { kind: "notes" }
  | { kind: "tags" }
  | { kind: "relations" }
  | { kind: "admin" };

const TOAST_MS: Record<ToastKind, number> = { info: 4000, success: 4000, error: 7000 };

export default function App() {
  const { theme, setTheme } = useTheme();
  const [user, setUser] = useState<User | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [tags, setTags] = useState<TagUsage[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [anchorBlock, setAnchorBlock] = useState<number | null>(null);
  const [view, setView] = useState<View>({ kind: "tags" });
  const [ready, setReady] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [driveOpen, setDriveOpen] = useState(false);
  const [driveStatus, setDriveStatus] = useState<DriveStatus | null>(null);
  const [feed, setFeed] = useState<EventFeed | null>(null);
  const [bellOpen, setBellOpen] = useState(false);
  const [image, setImage] = useState<ImagePreview | null>(null);
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
    // Back to the startup view; the next login opens its own first notebook.
    setView({ kind: "tags" });
    setNotebooks([]);
    setTags([]);
    setStats(null);
    setNotebook(null);
    setNote(null);
    setAnchorBlock(null);
    setDriveStatus(null);
    setPasswordOpen(false);
    // O próximo login busca o feed dele e pode abrir o painel uma vez.
    setFeed(null);
    setBellOpen(false);
    bellAutoOpened.current = false;
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
      api.listNotebooks(),
      api.listTags(),
      api.stats(),
    ]);
    setNotebooks(list);
    setTags(tagList);
    setStats(workspaceStats);
    return list;
  }, []);

  /** The Drive panel is not polled: it refreshes when it opens and after each action. */
  const refreshDriveStatus = useCallback(async () => {
    try {
      setDriveStatus(await api.driveStatus());
    } catch (error) {
      report(error);
    }
  }, [report]);

  const openDrive = useCallback(() => {
    setDriveOpen(true);
    void refreshDriveStatus();
  }, [refreshDriveStatus]);

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

  const openNotebook = useCallback(async (id: number) => {
    setNotebook(await api.getNotebook(id));
    setNote(null);
    setAnchorBlock(null);
    setView({ kind: "notebook", id });
  }, []);

  const openNote = useCallback(
    async (notebookId: number, id: number, blockId: number | null = null) => {
      setAnchorBlock(blockId);
      setNote(await api.getNote(id));
      setView({ kind: "note", notebookId, id });
    },
    [],
  );

  /** Jumping through a relation can land in another notebook, so load that notebook too. */
  const openRelatedNote = useCallback(
    async (noteId: number, notebookId: number) => {
      try {
        if (notebookId !== notebook?.id) setNotebook(await api.getNotebook(notebookId));
        await openNote(notebookId, noteId);
      } catch (error) {
        report(error);
      }
    },
    [notebook?.id, openNote, report],
  );

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
        if (first) await openNotebook(first.id);
      } catch (error) {
        if (!cancelled) report(error);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    void refreshDriveStatus();
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
  }, [user, openNotebook, refreshDriveStatus, refreshWorkspace, report, loadEvents]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  /** Block edits change counters everywhere, so refresh the chrome after each mutation. */
  const syncAfterEdit = useCallback(async () => {
    const currentView = view;
    try {
      await refreshWorkspace();
      if (currentView.kind === "notebook") setNotebook(await api.getNotebook(currentView.id));
      if (currentView.kind === "note") setNotebook(await api.getNotebook(currentView.notebookId));
    } catch (error) {
      report(error);
    }
  }, [refreshWorkspace, report, view]);

  const createNotebook = useCallback(async () => {
    try {
      const created = await api.createNotebook("Novo caderno");
      await refreshWorkspace();
      setNotebook(created);
      setNote(null);
      setView({ kind: "notebook", id: created.id });
      notify("Caderno criado. Renomeie no título.", "success");
      window.setTimeout(() => {
        document.querySelector<HTMLInputElement>(".nb-title-input")?.select();
      }, 30);
    } catch (error) {
      report(error);
    }
  }, [notify, refreshWorkspace, report]);

  const renameNotebook = useCallback(
    async (id: number, patch: { title?: string; description?: string }) => {
      try {
        setNotebook(await api.updateNotebook(id, patch));
        await refreshWorkspace();
      } catch (error) {
        report(error);
      }
    },
    [refreshWorkspace, report],
  );

  const deleteNotebook = useCallback(
    (id: number) => {
      const target = notebooks.find((item) => item.id === id);
      askConfirm({
        title: "Apagar caderno",
        message: `Tudo dentro de "${target?.title ?? id}" será apagado, incluindo ${target?.notes_count ?? 0} nota(s). Não dá para desfazer.`,
        confirmLabel: "Apagar caderno",
        danger: true,
        action: async () => {
          try {
            await api.deleteNotebook(id);
            const list = await refreshWorkspace();
            const next = list.find((item) => item.id !== id);
            if (next) await openNotebook(next.id);
            else setView({ kind: "tags" });
            notify("Caderno apagado", "success");
          } catch (error) {
            report(error);
          }
        },
      });
    },
    [askConfirm, notebooks, notify, openNotebook, refreshWorkspace, report],
  );

  const createNote = useCallback(
    async (notebookId: number, name = "") => {
      try {
        const created = await api.createNote(notebookId, name);
        await openNote(notebookId, created.id);
        await refreshWorkspace();
        notify("Nota criada. Digite / para escolher o tipo do bloco.", "success");
      } catch (error) {
        report(error);
      }
    },
    [notify, openNote, refreshWorkspace, report],
  );

  const deleteNote = useCallback(
    (notebookId: number, noteId: number) => {
      const target = notebooks.find((item) => item.id === notebookId);
      askConfirm({
        title: "Apagar nota",
        message: `Esta nota será apagada junto com seus blocos. O caderno fica com ${Math.max((target?.notes_count ?? 1) - 1, 0)} nota(s). Não dá para desfazer.`,
        confirmLabel: "Apagar nota",
        danger: true,
        action: async () => {
          try {
            await api.deleteNote(noteId);
            await openNotebook(notebookId);
            await refreshWorkspace();
            notify("Nota apagada", "success");
          } catch (error) {
            report(error);
          }
        },
      });
    },
    [askConfirm, notebooks, notify, openNotebook, refreshWorkspace, report],
  );

  const toggleNotebookTag = useCallback(
    async (notebookId: number, tagId: number, attached: boolean) => {
      try {
        setNotebook(
          attached
            ? await api.detachNotebookTag(notebookId, tagId)
            : await api.attachNotebookTag(notebookId, tagId),
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
        message: `"${target?.name ?? tagId}" sai de ${target?.notebooks_count ?? 0} caderno(s) e ${target?.notes_count ?? 0} nota(s). Não dá para desfazer.`,
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
      const matches = notebooks.filter((notebook) => notebookMatches(notebook, name)).length;
      setFilter(name);
      setSidebarOpen(true); // the filter lives in the side list, so it has to be on screen
      notify(
        matches === 0
          ? `Nenhum caderno com a tag "${name}"`
          : `${matches} caderno${matches === 1 ? "" : "s"} com a tag "${name}"`,
        matches === 0 ? "info" : "success",
      );
    },
    [notebooks, notify],
  );

  const navigateHit = useCallback(
    async (hit: SearchHit) => {
      setSearchOpen(false);
      try {
        if (hit.kind === "notebook" && hit.notebook_id) await openNotebook(hit.notebook_id);
        else if (hit.kind === "tag") openTag(hit.title);
        else if (hit.note_id && hit.notebook_id) await openNote(hit.notebook_id, hit.note_id);
      } catch (error) {
        report(error);
      }
    },
    [openNotebook, openNote, openTag, report],
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
    if (view.kind === "note" && note) {
      return (
        <NoteEditor
          note={note}
          tags={tags}
          notebookTitle={notebook?.title ?? ""}
          anchorBlockId={anchorBlock}
          onBack={() => void openNotebook(view.notebookId)}
          onOpenNote={(noteId, notebookId) => void openRelatedNote(noteId, notebookId)}
          onWorkspaceChange={syncAfterEdit}
          onCreateTag={createTag}
          onError={report}
          onToggleTag={async (tagId, attached) => {
            try {
              const updated = attached
                ? await api.detachNoteTag(note.id, tagId)
                : await api.attachNoteTag(note.id, tagId);
              setNote(updated);
              await refreshWorkspace();
            } catch (error) {
              report(error);
            }
          }}
          onRenameNote={async (title) => {
            try {
              await api.updateNote(note.id, { title });
              setNote((current) => (current ? { ...current, title } : current));
            } catch (error) {
              report(error);
            }
          }}
          onOpenImage={setImage}
        />
      );
    }
    if (view.kind === "notebook" && notebook) {
      return (
        <NotebookView
          notebook={notebook}
          tags={tags}
          onCreateTag={createTag}
          onOpenNote={(noteId) => void openNote(notebook.id, noteId)}
          onCreateNote={(text) => void createNote(notebook.id, text)}
          onDeleteNote={(noteId) => deleteNote(notebook.id, noteId)}
          onRename={(patch) => void renameNotebook(notebook.id, patch)}
          onDelete={() => deleteNotebook(notebook.id)}
          onToggleTag={(tagId, attached) => void toggleNotebookTag(notebook.id, tagId, attached)}
          onOpenNotebook={(id) => void openNotebook(id)}
        />
      );
    }
    if (view.kind === "kind") {
      return (
        <KindView
          blockType={view.blockType}
          onOpenNote={openNote}
          onOpenImage={setImage}
          onError={report}
        />
      );
    }
    if (view.kind === "tags") {
      return (
        <TagsView
          tags={tags}
          stats={stats}
          onOpenTag={openTag}
          onDeleteTag={deleteTag}
        />
      );
    }
    if (view.kind === "notes") {
      return (
        <NotesView
          onOpenNote={(noteId, notebookId) => void openRelatedNote(noteId, notebookId)}
          onError={report}
        />
      );
    }
    return (
      <RelationsView
        onOpenNote={(noteId, notebookId) => void openRelatedNote(noteId, notebookId)}
        onChanged={() => void refreshWorkspace()}
        onError={report}
        onNotify={notify}
        onAskConfirm={askConfirm}
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
        driveConnected={driveStatus?.connected ?? false}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        onNavigate={setView}
        onHome={() => {
          const first = notebooks[0];
          if (first) void openNotebook(first.id);
        }}
        onOpenSearch={() => setSearchOpen(true)}
        onToggleSidebar={() => setSidebarOpen((open) => !open)}
        onOpenDrive={openDrive}
        onOpenAdmin={() => setView({ kind: "admin" })}
        onLogout={() => void logout()}
        onChangePassword={() => setPasswordOpen(true)}
        feed={feed}
        bellOpen={bellOpen}
        onBellOpenChange={changeBell}
        onAllRead={markEventsRead}

        sidebarOpen={sidebarOpen}
      />
      <div className={sidebarOpen ? "app-body" : "app-body is-sidebar-hidden"}>
        {sidebarOpen && (
          <Sidebar
            notebooks={notebooks}
            tags={tags}
            stats={stats}
            view={view}
            filter={filter}
            onFilter={setFilter}
            onSelectNotebook={(id) => void openNotebook(id)}
            onCreateNotebook={() => void createNotebook()}
            onOpenTag={openTag}
            onClose={() => setSidebarOpen(false)}
          />
        )}
        <main className="main" id="conteudo" tabIndex={-1}>{main}</main>
      </div>
      {searchOpen && (
        <CommandPalette onClose={() => setSearchOpen(false)} onNavigate={(hit) => void navigateHit(hit)} />
      )}
      {driveOpen && driveStatus && (
        <DrivePanel
          status={driveStatus}
          onChanged={async (summary) => {
            await refreshDriveStatus();
            if (summary) {
              notify(
                `${summary.notes_sent} notas enviadas · ${summary.notes_unchanged} sem mudança`,
                "success",
              );
            }
          }}
          onAskConfirm={askConfirm}
          onClose={() => setDriveOpen(false)}
          onError={report}
        />
      )}
      {passwordOpen && (
        <PasswordPanel onClose={() => setPasswordOpen(false)} onNotify={notify} />
      )}
      {image && <ImageModal image={image} onClose={() => setImage(null)} />}
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
