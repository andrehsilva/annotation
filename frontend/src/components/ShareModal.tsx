import { UsersThree, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import { SHARE_ROLE_LABELS } from "../lib/format";
import type { Notebook, NotebookSharing } from "../lib/types";
import type { ToastKind } from "./ToastStack";

interface ShareModalProps {
  notebook: Notebook;
  onClose: () => void;
  onError: (error: unknown) => void;
  onNotify: (message: string, kind?: ToastKind) => void;
}

/**
 * O painel de compartilhar do caderno.
 *
 * Quem alcança vem de duas fontes: os grupos com que o dono compartilhou (o caso normal) e
 * eventuais membros diretos. Só o dono mexe nisso — para os outros a mesma lista é só leitura, o
 * que já responde "quem mais está vendo isto?".
 */
export function ShareModal({ notebook, onClose, onError, onNotify }: ShareModalProps) {
  const [sharing, setSharing] = useState<NotebookSharing | null>(null);
  const [busy, setBusy] = useState(false);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [role, setRole] = useState<"editor" | "viewer">("editor");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    void api
      .notebookSharing(notebook.id)
      .then((next) => {
        if (!cancelled) setSharing(next);
      })
      .catch((error: unknown) => {
        if (!cancelled) onError(error);
      });
    return () => {
      cancelled = true;
    };
  }, [notebook.id, onError]);

  const apply = useCallback(
    (action: () => Promise<NotebookSharing>, message: string) => {
      setBusy(true);
      void action()
        .then((next) => {
          setSharing(next);
          onNotify(message, "success");
        })
        .catch(onError)
        .finally(() => setBusy(false));
    },
    [onError, onNotify],
  );

  const shared = new Set(sharing?.groups.map((entry) => entry.group_id) ?? []);
  const choices = (sharing?.available ?? []).filter((group) => !shared.has(group.id));
  const picked = groupId ?? choices[0]?.id ?? null;

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Compartilhar o caderno">
        <div className="sheet-head">
          <p className="confirm-title">
            <UsersThree size={16} weight="bold" /> Compartilhar “{notebook.title}”
          </p>
          <button type="button" className="icon-btn is-tiny" onClick={onClose} aria-label="Fechar">
            <X size={14} weight="bold" />
          </button>
        </div>

        {sharing === null ? (
          <p className="panel-hint">Carregando quem alcança este caderno...</p>
        ) : (
          <>
            <p className="panel-hint">
              {sharing.can_share
                ? "O caderno é compartilhado com grupos: quem está no grupo alcança estas notas, e quem entrar depois também. Os grupos são montados pelo admin."
                : `Quem mais alcança este caderno. Só o dono${
                    notebook.owner_name ? ` (${notebook.owner_name})` : ""
                  } compartilha ou desfaz.`}
            </p>

            <ul className="member-list">
              {sharing.members.map((member) => (
                <li className="member-row" key={member.user_id}>
                  <span className="member-who">
                    <span className="member-name">
                      {member.display_name || member.email}
                      {member.owner && <span className="role-chip is-owner">dono</span>}
                    </span>
                    <span className="member-mail">{member.email}</span>
                  </span>
                  <span className="member-tags">
                    {member.groups.map((name) => (
                      <span className="tag-chip" key={name} title="Alcança por este grupo">
                        <UsersThree size={11} weight="bold" />
                        {name}
                      </span>
                    ))}
                    <span className="role-chip">{SHARE_ROLE_LABELS[member.role]}</span>
                  </span>
                </li>
              ))}
            </ul>

            {sharing.can_share && (
              <div className="share-box">
                <p className="panel-title">
                  <UsersThree size={14} weight="bold" /> Compartilhar com um grupo
                </p>
                {choices.length === 0 ? (
                  <p className="panel-hint">
                    {sharing.available.length === 0
                      ? "Nenhum grupo existe ainda — crie um na aba Grupos, em Admin."
                      : "Todos os grupos já alcançam este caderno."}
                  </p>
                ) : (
                  <div className="share-form">
                    <select
                      className="input"
                      value={picked ?? ""}
                      disabled={busy}
                      aria-label="Grupo"
                      onChange={(event) => setGroupId(Number(event.target.value))}
                    >
                      {choices.map((group) => (
                        <option value={group.id} key={group.id}>
                          {group.name} ({group.members}{" "}
                          {group.members === 1 ? "conta" : "contas"})
                        </option>
                      ))}
                    </select>
                    <select
                      className="input"
                      value={role}
                      disabled={busy}
                      aria-label="Papel"
                      onChange={(event) => setRole(event.target.value as "editor" | "viewer")}
                    >
                      <option value="editor">pode escrever</option>
                      <option value="viewer">só pode ler</option>
                    </select>
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={busy || picked === null}
                      onClick={() =>
                        picked !== null &&
                        apply(
                          () => api.shareNotebook(notebook.id, picked, role),
                          "Caderno compartilhado com o grupo",
                        )
                      }
                    >
                      Compartilhar
                    </button>
                  </div>
                )}

                {sharing.groups.length > 0 && (
                  <ul className="member-list">
                    {sharing.groups.map((entry) => (
                      <li className="member-row" key={entry.group_id}>
                        <span className="member-who">
                          <span className="member-name">
                            <UsersThree size={13} weight="bold" />
                            {entry.name}
                          </span>
                          <span className="member-mail">
                            {entry.members} {entry.members === 1 ? "conta" : "contas"} no grupo
                          </span>
                        </span>
                        <span className="member-tags">
                          <select
                            className="input share-role"
                            value={entry.role}
                            disabled={busy}
                            aria-label={`Papel do grupo ${entry.name}`}
                            onChange={(event) =>
                              apply(
                                () =>
                                  api.shareNotebook(
                                    notebook.id,
                                    entry.group_id,
                                    event.target.value as "editor" | "viewer",
                                  ),
                                `“${entry.name}” agora é ${
                                  event.target.value === "editor" ? "editor" : "leitor"
                                }`,
                              )
                            }
                          >
                            <option value="editor">pode escrever</option>
                            <option value="viewer">só pode ler</option>
                          </select>
                          <button
                            type="button"
                            className="btn btn-compact btn-danger"
                            disabled={busy}
                            onClick={() =>
                              apply(
                                () => api.unshareNotebook(notebook.id, entry.group_id),
                                `“${entry.name}” não alcança mais este caderno`,
                              )
                            }
                          >
                            Remover
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
