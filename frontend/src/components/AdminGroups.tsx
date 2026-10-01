import { Pencil, Trash, UserPlus, UsersThree } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../lib/api";
import { formatDate, relativeTime } from "../lib/format";
import type { AdminUser, Group } from "../lib/types";
import type { ConfirmRequest } from "./ConfirmDialog";
import type { ToastKind } from "./ToastStack";

interface AdminGroupsProps {
  onError: (error: unknown) => void;
  onNotify: (message: string, kind?: ToastKind) => void;
  onAskConfirm: (request: ConfirmRequest) => void;
}

/**
 * A aba **Grupos** do admin: os grupos e quem está em cada um.
 *
 * O grupo é o público do compartilhamento — o dono da nota escolhe um grupo, não pessoas — então
 * quem compõe cada grupo é decisão daqui. A nota não é tocada ao apagar um grupo (quem perde o
 * acesso é quem estava nele), e a tela diz isso antes de apagar.
 */
export function AdminGroups({ onError, onNotify, onAskConfirm }: AdminGroupsProps) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [renameFor, setRenameFor] = useState<number | null>(null);
  const [renameName, setRenameName] = useState("");
  const [openMembers, setOpenMembers] = useState<number | null>(null);
  const [memberIds, setMemberIds] = useState<number[] | null>(null);

  const reload = useCallback(async () => {
    try {
      const [groupList, userList] = await Promise.all([api.adminGroups(), api.adminListUsers()]);
      setGroups(groupList);
      setUsers(userList);
    } catch (error) {
      onError(error);
    }
  }, [onError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setCreating(true);
    try {
      const created = await api.adminCreateGroup(name.trim());
      setName("");
      await reload();
      onNotify(`Grupo "${created.name}" criado`, "success");
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Não deu para criar o grupo");
    } finally {
      setCreating(false);
    }
  };

  /** Toda ação recarrega a lista: o número de pessoas muda com ela. */
  const run = (id: number, action: () => Promise<void>) => {
    setBusyId(id);
    void action()
      .then(reload)
      .catch(onError)
      .finally(() => setBusyId(null));
  };

  const rename = (event: FormEvent, group: Group) => {
    event.preventDefault();
    const next = renameName.trim();
    setRenameFor(null);
    if (!next || next === group.name) return;
    run(group.id, async () => {
      await api.adminRenameGroup(group.id, next);
      onNotify(`Grupo renomeado para "${next}"`, "success");
    });
  };

  const remove = (group: Group) =>
    onAskConfirm({
      title: "Apagar grupo",
      message: `"${group.name}" sai de todas as notas que o compartilham e ${group.members} conta(s) perdem o acesso a elas. As notas continuam com o dono. Não dá para desfazer.`,
      confirmLabel: "Apagar grupo",
      danger: true,
      action: async () => {
        await api.adminDeleteGroup(group.id);
        if (openMembers === group.id) setOpenMembers(null);
        await reload();
        onNotify("Grupo apagado", "success");
      },
    });

  /** Abre a lista de contas para pôr/tirar gente: os ids vêm da linha do próprio grupo. */
  const openFor = (group: Group) => {
    if (openMembers === group.id) {
      setOpenMembers(null);
      return;
    }
    setMemberIds(null);
    setOpenMembers(group.id);
    void api
      .adminGroup(group.id)
      .then((detail) => setMemberIds(detail.member_ids))
      .catch(onError);
  };

  const toggleMember = (groupId: number, userId: number, inside: boolean) => {
    setBusyId(groupId);
    const call = inside
      ? api.adminRemoveGroupMember(groupId, userId)
      : api.adminAddGroupMember(groupId, userId);
    void call
      .then(async () => {
        const detail = await api.adminGroup(groupId);
        setMemberIds(detail.member_ids);
        setGroups((current) =>
          current?.map((entry) =>
            entry.id === groupId ? { ...entry, members: detail.member_ids.length } : entry,
          ) ?? current,
        );
      })
      .catch(onError)
      .finally(() => setBusyId(null));
  };

  const openGroup = groups?.find((entry) => entry.id === openMembers) ?? null;

  return (
    <>
      <section className="panel">
        <p className="panel-title">
          <UserPlus size={14} weight="bold" /> Novo grupo
        </p>
        <form className="admin-create" onSubmit={(event) => void create(event)}>
          <label className="form-field">
            <span className="form-label">Nome</span>
            <input
              className="input"
              value={name}
              required
              maxLength={60}
              placeholder="Ex.: Time, Cliente X, Família"
              disabled={creating}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={creating || !name.trim()}>
            {creating ? "Criando…" : "Criar grupo"}
          </button>
        </form>
        {formError && (
          <p className="form-error" role="alert">
            {formError}
          </p>
        )}
        <p className="panel-hint">
          O grupo nasce vazio. Compartilhar uma nota é do dono, no cabeçalho da nota — aqui você
          decide quem está em cada grupo, e quem entrar depois já alcança o que o grupo alcança.
        </p>
      </section>

      <section className="panel admin-table-shell">
        {groups === null ? (
          <p className="panel-hint">Carregando grupos…</p>
        ) : groups.length === 0 ? (
          <p className="panel-hint">
            <UsersThree size={13} /> Nenhum grupo ainda. Crie o primeiro acima.
          </p>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Grupo</th>
                <th>Pessoas</th>
                <th>Criado em</th>
                <th aria-label="Ações" />
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const rowBusy = busyId === group.id;
                return (
                  <tr key={group.id} className="admin-row">
                    <td className="admin-name">{group.name}</td>
                    <td>
                      {group.members} {group.members === 1 ? "conta" : "contas"}
                    </td>
                    <td title={formatDate(group.created_at)}>{relativeTime(group.created_at)}</td>
                    <td className="admin-actions">
                      {renameFor === group.id ? (
                        <form className="admin-reset" onSubmit={(event) => rename(event, group)}>
                          <input
                            className="input admin-reset-input"
                            value={renameName}
                            maxLength={60}
                            autoFocus
                            disabled={rowBusy}
                            onChange={(event) => setRenameName(event.target.value)}
                          />
                          <button type="submit" className="btn btn-compact" disabled={rowBusy}>
                            Salvar
                          </button>
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={rowBusy}
                            onClick={() => setRenameFor(null)}
                          >
                            Cancelar
                          </button>
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={busyId !== null}
                            aria-pressed={openMembers === group.id}
                            onClick={() => openFor(group)}
                          >
                            <UsersThree size={14} />
                            {openMembers === group.id ? "Fechar" : "Membros"}
                          </button>
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={busyId !== null}
                            onClick={() => {
                              setRenameFor(group.id);
                              setRenameName(group.name);
                            }}
                          >
                            <Pencil size={14} /> Renomear
                          </button>
                          <button
                            type="button"
                            className="btn btn-compact btn-danger"
                            disabled={busyId !== null}
                            onClick={() => remove(group)}
                          >
                            <Trash size={14} /> Excluir
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {openGroup && (
        <section className="panel">
          <p className="panel-title">
            <UsersThree size={14} weight="bold" />{" "}
            <span>Quem está em “{openGroup.name}”</span>
          </p>
          {users === null || memberIds === null ? (
            <p className="panel-hint">Carregando contas…</p>
          ) : (
            <ul className="member-list">
              {users.map((entry) => {
                const inside = memberIds.includes(entry.id);
                return (
                  <li className="member-row" key={entry.id}>
                    <span className="member-who">
                      <span className="member-name">{entry.display_name || entry.email}</span>
                      <span className="member-mail">{entry.email}</span>
                    </span>
                    <button
                      type="button"
                      className={inside ? "btn btn-compact btn-danger" : "btn btn-compact"}
                      disabled={busyId === openGroup.id}
                      aria-pressed={inside}
                      onClick={() => toggleMember(openGroup.id, entry.id, inside)}
                      title={inside ? "Tirar do grupo" : "Pôr no grupo"}
                    >
                      {inside ? "Tirar do grupo" : "Pôr no grupo"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
