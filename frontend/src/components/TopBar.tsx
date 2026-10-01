import { Bell, DotsThree, GithubLogo, GraphIcon, MagnifyingGlass, Moon, NoteBlank, Plus, SidebarSimple, Sun, Tag, User as UserIcon, Users } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import type { View } from "../App";
import { KIND_ICONS } from "../lib/kinds";
import { KIND_LABELS, KIND_ORDER } from "../lib/format";
import { ActivityPanel } from "./ActivityBell";
import { Key } from "./ui";
import type { BlockType, EventFeed, Stats, User } from "../lib/types";

/** O `gap` do `.topnav`: entra na conta de quanto cada chip ocupa na régua. */
const NAV_GAP = 6;

interface TopBarProps {
  view: View;
  stats: Stats | null;
  theme: "dark" | "light";
  user: User;
  feed: EventFeed | null;
  bellOpen: boolean;
  onToggleTheme: () => void;
  onNavigate: (view: View) => void;
  onHome: () => void;
  onOpenSearch: () => void;
  onToggleSidebar: () => void;
  onOpenAdmin: () => void;
  onOpenGithub: () => void;
  onOpenWelcome: () => void;
  onLogout: () => void;
  onChangePassword: () => void;
  onBellOpenChange: (open: boolean) => void;
  onAllRead: () => void;
  onNewNote: () => void;

  sidebarOpen: boolean;
}

export function TopBar({
  view,
  stats,
  theme,
  user,
  feed,
  bellOpen,
  onToggleTheme,
  onNavigate,
  onHome,
  onOpenSearch,
  onToggleSidebar,
  onOpenAdmin,
  onOpenGithub,
  onOpenWelcome,
  onLogout,
  onChangePassword,
  onBellOpenChange,
  onAllRead,
  onNewNote,

  sidebarOpen,
}: TopBarProps) {
  const isNoteSection = view.kind === "notes" || view.kind === "note";
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  /** Onde ancorar a atividade: ela abre do menu do nome, mas o painel encosta no cabeçalho. */
  const [bellBox, setBellBox] = useState<{ top: number; right: number } | null>(null);
  const unread = feed?.unread ?? 0;

  const bellRef = useRef<HTMLDivElement | null>(null);

  /** O sino abre a página de atividade ancorada nele, como o menu de ⋯ (o popover é `fixed`). */
  const toggleActivity = () => {
    if (bellOpen) {
      onBellOpenChange(false);
      return;
    }
    const rect = bellRef.current?.getBoundingClientRect();
    setBellBox(rect ? { top: rect.bottom + 6, right: Math.max(8, window.innerWidth - rect.right) } : null);
    onBellOpenChange(true);
  };

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

  // Cabeçalho estreito: a régua invisível (as mesmas peças fora da tela) diz a largura de cada grupo, e
  // a conta decide o arranjo — tudo inline, só os contadores no menu "…", ou o menu com tudo.
  const [layout, setLayout] = useState<"full" | "counters" | "menu">("full");
  const [visibleKinds, setVisibleKinds] = useState(KIND_ORDER.length);
  const [moreOpen, setMoreOpen] = useState(false);
  /** Onde ancorar o menu: o popover é `fixed` porque o `.topnav` recorta o que passa dele. */
  const [moreBox, setMoreBox] = useState<{ top: number; right: number } | null>(null);
  const moreRef = useRef<HTMLDivElement | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  const rulerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const nav = navRef.current;
    const ruler = rulerRef.current;
    if (!nav || !ruler) return;
    const measure = () => {
      const [sectionsRuler, ...chips] = Array.from(ruler.children) as HTMLElement[];
      const moreChip = chips.pop();
      if (!sectionsRuler || !moreChip) return;
      const sectionsWidth = sectionsRuler.getBoundingClientRect().width + NAV_GAP;
      const moreWidth = moreChip.getBoundingClientRect().width + NAV_GAP;
      const room = nav.clientWidth;
      const widthOf = (chip: HTMLElement) => chip.getBoundingClientRect().width + NAV_GAP;
      const total = sectionsWidth + chips.reduce((sum, chip) => sum + widthOf(chip), 0);
      if (total <= room) {
        setLayout("full");
        setVisibleKinds(KIND_ORDER.length);
        return;
      }
      const counterRoom = room - sectionsWidth - moreWidth;
      let used = 0;
      let count = 0;
      for (const chip of chips) {
        if (used + widthOf(chip) > counterRoom) break;
        used += widthOf(chip);
        count += 1;
      }
      // Nem as seções cabem: o menu leva tudo (é o que sobra do cabeçalho com a janela estreita).
      setLayout(sectionsWidth + moreWidth > room ? "menu" : "counters");
      setVisibleKinds(count);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(nav);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [stats]);

  useEffect(() => {
    if (!moreOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) setMoreOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMoreOpen(false);
    };
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [moreOpen]);

  /** Um contador por tipo. O mesmo chip serve a linha visível e a régua que mede a largura. */
  const kindChip = (kind: BlockType, measurable = false) => {
    const KindIcon = KIND_ICONS[kind];
    const total = stats?.counts[kind] ?? 0;
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
        title={`${total} ${KIND_LABELS[kind]} em todas as notas`}
        aria-label={`Ver ${total} ${KIND_LABELS[kind]}`}
        aria-hidden={measurable || undefined}
        tabIndex={measurable ? -1 : undefined}
      >
        <KindIcon size={15} weight="bold" />
        <span className="topnav-count">{total}</span>
      </button>
    );
  };

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
      key: "notes",
      label: "Notas",
      icon: NoteBlank,
      count: stats?.notes,
      active: isNoteSection,
      onSelect: onHome,
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

  /** O chip de uma seção (Notas, Tags, Relações): igual na linha e na régua. */
  const sectionChip = (section: (typeof sections)[number], measurable = false) => {
    const SectionIcon = section.icon;
    return (
      <button
        type="button"
        key={section.key}
        className={section.active ? "topnav-chip is-active" : "topnav-chip"}
        onClick={section.onSelect}
        title={section.label}
        aria-label={section.label}
        aria-hidden={measurable || undefined}
        tabIndex={measurable ? -1 : undefined}
      >
        <SectionIcon size={15} weight="bold" />
        {section.count !== undefined && <span className="topnav-count">{section.count}</span>}
      </button>
    );
  };

  return (
    <header className="topbar">
      <button
        type="button"
        className="topbar-toggle"
        onClick={onToggleSidebar}
        title={sidebarOpen ? "Esconder a lista de notas" : "Mostrar a lista de notas"}
        aria-label={sidebarOpen ? "Esconder a lista de notas" : "Mostrar a lista de notas"}
        aria-pressed={sidebarOpen}
      >
        <SidebarSimple size={17} weight="bold" />
      </button>
      <div className={sidebarOpen ? "topbar-brand is-wide" : "topbar-brand"}>
        <span className="logo-mark" aria-hidden="true">
          {">_"}
        </span>
        <span className="wordmark">AnotAI</span>
      </div>

      <nav className="topnav" ref={navRef}>
        {/* Régua: as mesmas peças, fora de vista, para medir sem depender do que está na tela. */}
        <div className="topnav-ruler" ref={rulerRef} aria-hidden="true">
          <div className="topnav-sections">{sections.map((section) => sectionChip(section, true))}</div>
          {KIND_ORDER.map((kind) => kindChip(kind, true))}
          <span className="topnav-chip">
            <DotsThree size={16} weight="bold" />
          </span>
        </div>

        {stats && layout !== "menu" && (
          <div className="topnav-sections">
            {sections.map((section) => sectionChip(section))}
            <span className="topnav-pipe" aria-hidden="true">
              |
            </span>
          </div>
        )}

        {stats && layout !== "menu" && KIND_ORDER.slice(0, visibleKinds).map((kind) => kindChip(kind))}

        {stats && layout !== "full" && (
          <div className="topnav-more" ref={moreRef}>
            <button
              type="button"
              className={moreOpen ? "topnav-chip is-active" : "topnav-chip"}
              onClick={() => {
                const button = moreRef.current?.querySelector("button");
                if (!button) return;
                const rect = button.getBoundingClientRect();
                setMoreBox({ top: rect.bottom + 6, right: Math.max(8, window.innerWidth - rect.right) });
                setMoreOpen((open) => !open);
              }}
              title="Mais no cabeçalho"
              aria-label="Mais no cabeçalho"
              aria-haspopup="menu"
              aria-expanded={moreOpen}
            >
              <DotsThree size={16} weight="bold" />
            </button>
            {moreOpen && moreBox && (
              <div className="topnav-menu" role="menu" style={{ top: moreBox.top, right: moreBox.right }}>
                {layout === "menu" &&
                  sections.map((section) => {
                    const SectionIcon = section.icon;
                    return (
                      <button
                        type="button"
                        role="menuitem"
                        key={section.key}
                        className="topnav-menu-item"
                        onClick={() => {
                          setMoreOpen(false);
                          section.onSelect();
                        }}
                      >
                        <SectionIcon size={14} weight="bold" />
                        {section.label}
                        {section.count !== undefined && (
                          <span className="topnav-count">{section.count}</span>
                        )}
                      </button>
                    );
                  })}
                {layout === "menu" && <span className="topnav-menu-sep" aria-hidden="true" />}
                {KIND_ORDER.slice(layout === "menu" ? 0 : visibleKinds).map((kind) => {
                  const KindIcon = KIND_ICONS[kind];
                  const total = stats.counts[kind];
                  return (
                    <button
                      type="button"
                      role="menuitem"
                      key={kind}
                      className="topnav-menu-item"
                      onClick={() => {
                        setMoreOpen(false);
                        onNavigate({ kind: "kind", blockType: kind });
                      }}
                    >
                      <KindIcon size={14} weight="bold" />
                      {KIND_LABELS[kind]}
                      <span className="topnav-count">{total}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </nav>

      <div className="topbar-actions">
        <div className="topbar-create">
          <button
            type="button"
            className="btn btn-compact create-btn"
            onClick={onNewNote}
            title="Nova nota"
          >
            <Plus size={13} weight="bold" />
            <NoteBlank size={16} weight="bold" />
          </button>
        </div>
        <span className="topbar-divider" aria-hidden="true" />
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
              {user.role === "admin" && (
                <button
                  type="button"
                  role="menuitem"
                  className="user-popover-item"
                  onClick={() => {
                    setMenuOpen(false);
                    onOpenAdmin();
                  }}
                >
                  <Users size={14} weight="bold" />
                  Admin: usuários e grupos
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                className="user-popover-item"
                onClick={() => {
                  setMenuOpen(false);
                  onOpenGithub();
                }}
              >
                <GithubLogo size={14} weight="bold" />
                GitHub: publicar como gist
              </button>
              <span className="user-popover-sep" aria-hidden="true" />
              <button
                type="button"
                role="menuitem"
                className="user-popover-item"
                onClick={() => {
                  setMenuOpen(false);
                  onOpenWelcome();
                }}
              >
                Como usar
              </button>
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
        <div className="activity-menu" ref={bellRef}>
          <button
            type="button"
            className={bellOpen ? "topnav-chip is-active" : "topnav-chip"}
            onClick={toggleActivity}
            title="Atividade"
            aria-label="Atividade"
            aria-haspopup="menu"
            aria-expanded={bellOpen}
          >
            <Bell size={15} weight="bold" />
            {unread > 0 && <span className="activity-badge">{unread}</span>}
          </button>
        </div>
        <ActivityPanel
          feed={feed}
          open={bellOpen}
          anchor={bellBox}
          onOpenChange={onBellOpenChange}
          onAllRead={onAllRead}
        />
        <button
          type="button"
          className="icon-btn"
          onClick={onToggleTheme}
          title={theme === "dark" ? "Tema claro" : "Tema escuro"}
          aria-label={theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}
        >
          {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
        </button>
        <button
          type="button"
          className="search-pill"
          onClick={onOpenSearch}
          title="Buscar (Ctrl+K)"
          aria-label="Buscar"
        >
          <MagnifyingGlass size={15} />
          <span className="search-keys">
            <Key>Ctrl</Key>
            <Key>K</Key>
          </span>
        </button>
      </div>
    </header>
  );
}
