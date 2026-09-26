import { CloudArrowUp, GraphIcon, MagnifyingGlass, Moon, NoteBlank, Notebook, Plus, SidebarSimple, Sun, Tag, User as UserIcon, Users } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import type { View } from "../App";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER } from "../lib/format";
import { ActivityBell } from "./ActivityBell";
import { Key } from "./ui";
import type { EventFeed, Stats, User } from "../lib/types";

interface TopBarProps {
  view: View;
  stats: Stats | null;
  theme: "dark" | "light";
  user: User;
  driveConnected: boolean;
  feed: EventFeed | null;
  bellOpen: boolean;
  onToggleTheme: () => void;
  onNavigate: (view: View) => void;
  onHome: () => void;
  onOpenSearch: () => void;
  onToggleSidebar: () => void;
  onOpenDrive: () => void;
  onOpenAdmin: () => void;
  onLogout: () => void;
  onChangePassword: () => void;
  onBellOpenChange: (open: boolean) => void;
  onAllRead: () => void;
  onNewNotebook: () => void;
  onNewNote: () => void;

  sidebarOpen: boolean;
}

export function TopBar({
  view,
  stats,
  theme,
  user,
  driveConnected,
  feed,
  bellOpen,
  onToggleTheme,
  onNavigate,
  onHome,
  onOpenSearch,
  onToggleSidebar,
  onOpenDrive,
  onOpenAdmin,
  onLogout,
  onChangePassword,
  onBellOpenChange,
  onAllRead,
  onNewNotebook,
  onNewNote,

  sidebarOpen,
}: TopBarProps) {
  const isNotebookSection = view.kind === "notebook" || view.kind === "note";
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  /** Icon + count, like the block counters after the pipe: the name lives in the tooltip. */
  const sections: {
    key: string;
    label: string;
    icon: Icon;
    count: number | undefined;
    active: boolean;
    onSelect: () => void;
  }[] = [
    {
      key: "notebooks",
      label: "Cadernos",
      icon: Notebook,
      count: stats?.notebooks,
      active: isNotebookSection,
      onSelect: onHome,
    },
    {
      key: "notes",
      label: "Notas",
      icon: NoteBlank,
      count: stats?.notes,
      active: view.kind === "notes",
      onSelect: () => onNavigate({ kind: "notes" }),
    },
    {
      key: "tags",
      label: "Tags",
      icon: Tag,
      count: stats?.tags,
      active: view.kind === "tags",
      onSelect: () => onNavigate({ kind: "tags" }),
    },
    {
      key: "relations",
      label: "Relações",
      icon: GraphIcon,
      count: stats?.relations,
      active: view.kind === "relations",
      onSelect: () => onNavigate({ kind: "relations" }),
    },
  ];

  return (
    <header className="topbar">
      <button
        type="button"
        className="topbar-toggle"
        onClick={onToggleSidebar}
        title={sidebarOpen ? "Esconder a lista de cadernos" : "Mostrar a lista de cadernos"}
        aria-label={sidebarOpen ? "Esconder a lista de cadernos" : "Mostrar a lista de cadernos"}
        aria-pressed={sidebarOpen}
      >
        <SidebarSimple size={17} weight="bold" />
      </button>
      <div className="topbar-brand">
        <span className="logo-mark" aria-hidden="true">
          {">_"}
        </span>
        <span className="wordmark">AnotAI</span>
      </div>

      <nav className="topnav">
        {sections.map((section) => {
          const SectionIcon = section.icon;
          return (
            <button
              key={section.key}
              type="button"
              className={section.active ? "topnav-chip is-active" : "topnav-chip"}
              onClick={section.onSelect}
              title={section.label}
              aria-label={section.label}
            >
              <SectionIcon size={15} weight="bold" />
              {section.count !== undefined && (
                <span className="topnav-count">{section.count}</span>
              )}
            </button>
          );
        })}
        <span className="topnav-pipe" aria-hidden="true">
          |
        </span>
        {stats &&
          KIND_ORDER.map((kind) => {
            const KindIcon = KIND_ICONS[kind];
            const total = stats.counts[kind];
            const isActive = view.kind === "kind" && view.blockType === kind;
            const classes = ["topnav-chip"];
            if (isActive) classes.push("is-active");
            if (total === 0) classes.push("is-zero");
            return (
              <button
                type="button"
                key={kind}
                className={classes.join(" ")}
                onClick={() => onNavigate({ kind: "kind", blockType: kind })}
                title={`${total} ${KIND_LABELS[kind]} em todos os cadernos`}
                aria-label={`Ver ${total} ${KIND_LABELS[kind]}`}
              >
                <KindIcon size={15} weight="bold" />
                <span className="topnav-count">{total}</span>
              </button>
            );
          })}
      </nav>

      <div className="topbar-create">
        <button
          type="button"
          className="topnav-chip create-chip"
          onClick={onNewNotebook}
          title="Novo caderno"
          aria-label="Novo caderno"
        >
          <Plus size={14} weight="bold" />
          <Notebook size={15} weight="bold" />
          <span className="create-label">Caderno</span>
        </button>
        <button
          type="button"
          className="topnav-chip create-chip"
          onClick={onNewNote}
          title="Nova nota"
          aria-label="Nova nota"
        >
          <Plus size={14} weight="bold" />
          <NoteBlank size={15} weight="bold" />
          <span className="create-label">Nota</span>
        </button>
      </div>

      <div className="topbar-actions">
        <div className="user-menu" ref={menuRef}>
          <button
            type="button"
            className={menuOpen ? "topnav-chip user-chip is-active" : "topnav-chip user-chip"}
            onClick={() => setMenuOpen((open) => !open)}
            title={user.email}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <UserIcon size={15} weight="bold" />
            <span className="user-chip-name">{user.display_name || user.email}</span>
          </button>
          {menuOpen && (
            <div className="user-popover" role="menu">
              <p className="user-popover-head">{user.email}</p>
              <button
                type="button"
                role="menuitem"
                className="user-popover-item"
                onClick={() => {
                  setMenuOpen(false);
                  onChangePassword();
                }}
              >
                Trocar senha
              </button>
              <button
                type="button"
                role="menuitem"
                className="user-popover-item"
                onClick={() => {
                  setMenuOpen(false);
                  onLogout();
                }}
              >
                Sair
              </button>
            </div>
          )}
        </div>
        <ActivityBell
          feed={feed}
          open={bellOpen}
          onOpenChange={onBellOpenChange}
          onAllRead={onAllRead}
        />
        {user.role === "admin" && (
          <button
            type="button"
            className={view.kind === "admin" ? "topnav-chip is-active" : "topnav-chip"}
            onClick={onOpenAdmin}
            title="Usuários"
            aria-label="Usuários"
            aria-pressed={view.kind === "admin"}
          >
            <Users size={15} weight="bold" />
          </button>
        )}
        <button
          type="button"
          className="icon-btn is-cloud"
          onClick={onOpenDrive}
          title="Backup no Google Drive"
          aria-label="Backup no Google Drive"
          aria-pressed={driveConnected}
        >
          <CloudArrowUp size={17} />
          {driveConnected && <span className="cloud-dot" aria-hidden="true" />}
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={onToggleTheme}
          title={theme === "dark" ? "Tema claro" : "Tema escuro"}
          aria-label={theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}
        >
          {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
        </button>
        <button type="button" className="search-pill" onClick={onOpenSearch}>
          <MagnifyingGlass size={15} />
          <span className="search-placeholder">Buscar</span>
          <span className="search-keys">
            <Key>Ctrl</Key>
            <Key>K</Key>
          </span>
        </button>
      </div>
    </header>
  );
}
