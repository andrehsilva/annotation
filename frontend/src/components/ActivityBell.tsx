import { Bell, Image, LinkSimple, NoteBlank, Notebook, Tag, TextAa, User } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";

import { relativeTime } from "../lib/format";
import type { ActivityEvent, EventFeed } from "../lib/types";

interface ActivityBellProps {
  feed: EventFeed | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAllRead: () => void;
}

/** O que a ação fez, no passado. */
const VERBS: Record<string, string> = {
  created: "criou",
  updated: "atualizou",
  deleted: "apagou",
  linked: "ligou",
  unlinked: "desligou",
  uploaded: "enviou",
  reset: "redefiniu a senha de",
};

/** O substantivo do alvo, com artigo, para a frase ficar inteira. */
const NOUNS: Record<string, string> = {
  notebook: "o caderno",
  note: "a nota",
  block: "o bloco em",
  tag: "a tag",
  relation: "",
  media: "o arquivo",
  user: "o usuário",
};

const ICONS: Record<string, Icon> = {
  notebook: Notebook,
  note: NoteBlank,
  block: TextAa,
  tag: Tag,
  relation: LinkSimple,
  media: Image,
  user: User,
};

/** "criou o caderno «Rust»"; o rótulo vazio vira "sem título". */
function describe(event: ActivityEvent): string {
  const target = event.target || "sem título";
  // Etiquetar tem duas partes (a tag e onde ela entrou), então a frase não usa o substantivo.
  if (event.action === "tagged") return `marcou "${target}" com a tag "${event.detail || "?"}"`;
  if (event.action === "untagged") return `tirou a tag "${event.detail || "?"}" de "${target}"`;
  const verb = VERBS[event.action] ?? event.action;
  const noun = NOUNS[event.entity] ?? "";
  // O único encontro que pede contração: o verbo termina em "de" e o substantivo começa em "o".
  const contraction = verb.endsWith(" de") && noun.startsWith("o ");
  const head = contraction ? `${verb.slice(0, -2)}do ${noun.slice(2)}` : `${verb} ${noun}`;
  return [head.trim(), `"${target}"`].filter(Boolean).join(" ");
}

/** O sino do topo: quantas interações ainda não foram vistas e a última página delas. */
export function ActivityBell({ feed, open, onOpenChange, onAllRead }: ActivityBellProps) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  /** O painel já esteve aberto: fechar depois disso conta como "vi tudo". */
  const wasOpen = useRef(false);
  const unread = feed?.unread ?? 0;
  const items = feed?.items ?? [];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) onOpenChange(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      return;
    }
    if (wasOpen.current) {
      wasOpen.current = false;
      onAllRead();
    }
  }, [open, onAllRead]);

  return (
    <div className="activity-menu" ref={boxRef}>
      <button
        type="button"
        className={open ? "topnav-chip is-active" : "topnav-chip"}
        onClick={() => onOpenChange(!open)}
        title="Atividade"
        aria-label="Atividade"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Bell size={15} weight="bold" />
        {unread > 0 && <span className="activity-badge">{unread}</span>}
      </button>
      {open && (
        <div className="activity-popover" role="menu" aria-label="Atividade">
          <p className="activity-head">Atividade</p>
          {items.length === 0 ? (
            <p className="activity-empty">Nada por aqui ainda.</p>
          ) : (
            <ul className="activity-list">
              {items.map((event) => {
                const EntityIcon = ICONS[event.entity] ?? Bell;
                return (
                  <li key={event.id} className="activity-item">
                    <EntityIcon className="activity-icon" size={14} weight="bold" />
                    <span className="activity-body">
                      <span className="activity-text">
                        {!event.mine && event.actor && (
                          <span className="activity-actor">{event.actor} · </span>
                        )}
                        {describe(event)}
                      </span>
                      <span className="activity-time">{relativeTime(event.created_at)}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="activity-foot">últimas 5 interações</p>
        </div>
      )}
    </div>
  );
}
