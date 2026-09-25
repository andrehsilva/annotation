import { UserPlus } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../lib/api";
import { formatDate, relativeTime } from "../lib/format";
import type { AdminUser, Role, User } from "../lib/types";
import type { ConfirmRequest } from "./ConfirmDialog";
import type { ToastKind } from "./ToastStack";

interface AdminViewProps {
  /** The admin looking at the screen: their own row has no way out of the app. */
  user: User;
  onError: (error: unknown) => void;
  onNotify: (message: string, kind?: ToastKind) => void;
  onAskConfirm: (request: ConfirmRequest) => void;
}

const MIN_PASSWORD = 8;

const ROLE_LABELS: Record<Role, string> = { admin: "administrador", user: "usuário" };

/** Table cell for a byte count: one unit step, one decimal once it is not a round number. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["kB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || Number.isInteger(value) ? 0 : 1)} ${units[unit]}`;
}

/** The admin screen: every account, what it holds, and the four ways to act on it. */
export function AdminView({ user, onError, onNotify, onAskConfirm }: AdminViewProps) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setUsers(await api.adminListUsers());
    } catch (error) {
      onError(error);
    }
  }, [onError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setFormError(`A senha precisa de pelo menos ${MIN_PASSWORD} caracteres`);
      return;
    }
    setCreating(true);
    setFormError(null);
    try {
      const created = await api.adminCreateUser({
        email: email.trim(),
        display_name: displayName.trim(),
        password,
        role,
      });
      setEmail("");
      setDisplayName("");
      setPassword("");
      setRole("user");
      await reload();
      onNotify(`Usuário ${created.email} criado`, "success");
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Falha ao falar com a API local");
    } finally {
      setCreating(false);
    }
  };

  /** Every row action reloads the list, because the counters change with it. */
  const run = (id: number, action: () => Promise<void>) => {
    setBusyId(id);
    void action()
      .then(reload)
      .catch(onError)
      .finally(() => setBusyId(null));
  };

  const toggleActive = (entry: AdminUser) =>
    run(entry.id, async () => {
      await api.adminUpdateUser(entry.id, { is_active: !entry.is_active });
      onNotify(
        entry.is_active ? `${entry.email} desativado` : `${entry.email} ativado`,
        "success",
      );
    });

  const remove = (entry: AdminUser) =>
    onAskConfirm({
      title: "Excluir usuário",
      message: `"${entry.email}" leva junto os cadernos, as notas e os arquivos enviados. Não dá para desfazer.`,
      confirmLabel: "Excluir usuário",
      danger: true,
      action: async () => {
        try {
          await api.adminDeleteUser(entry.id);
          await reload();
          onNotify(`Usuário ${entry.email} excluído`, "success");
        } catch (error) {
          onError(error);
        }
      },
    });

  const reset = (event: FormEvent, entry: AdminUser) => {
    event.preventDefault();
    if (resetPassword.length < MIN_PASSWORD) {
      setResetError(`A senha precisa de pelo menos ${MIN_PASSWORD} caracteres`);
      return;
    }
    const chosen = resetPassword;
    setResetFor(null);
    setResetPassword("");
    setResetError(null);
    run(entry.id, async () => {
      await api.adminResetPassword(entry.id, chosen);
      onNotify(`Senha de ${entry.email} redefinida`, "success");
    });
  };

  return (
    <div className="view">
      <header className="view-head">
        <div className="view-head-main">
          <h1 className="view-title">Usuários</h1>
          <p className="view-lede">
            Cada conta vê apenas os próprios cadernos. Na sua própria linha as ações ficam fora: o
            backend recusa desativar ou apagar a própria conta, e a sua senha se troca pelo menu do
            usuário.
          </p>
        </div>
      </header>

      <section className="panel">
        <p className="panel-title">
          <UserPlus size={14} weight="bold" /> Novo usuário
        </p>
        <form className="admin-create" onSubmit={(event) => void create(event)}>
          <label className="form-field">
            <span className="form-label">E-mail</span>
            <input
              className="input"
              type="email"
              value={email}
              required
              disabled={creating}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="form-label">Nome</span>
            <input
              className="input"
              value={displayName}
              placeholder="Como aparece no app"
              disabled={creating}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="form-label">Senha</span>
            <input
              className="input"
              type="password"
              value={password}
              required
              autoComplete="new-password"
              disabled={creating}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="form-label">Papel</span>
            <select
              className="input"
              value={role}
              disabled={creating}
              onChange={(event) => setRole(event.target.value as Role)}
            >
              <option value="user">usuário</option>
              <option value="admin">administrador</option>
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={creating}>
            {creating ? "Criando..." : "Criar usuário"}
          </button>
        </form>
        {formError && (
          <p className="form-error" role="alert">
            {formError}
          </p>
        )}
        <p className="panel-hint">
          A senha nasce com pelo menos {MIN_PASSWORD} caracteres e o usuário pode trocá-la sozinho
          depois.
        </p>
      </section>

      <section className="panel admin-table-shell">
        {users === null ? (
          <p className="panel-hint">Carregando usuários...</p>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Nome</th>
                <th>E-mail</th>
                <th>Papel</th>
                <th>Cadernos</th>
                <th>Notas</th>
                <th>Blocos</th>
                <th>Mídia</th>
                <th>Último acesso</th>
                <th>Estado</th>
                <th aria-label="Ações" />
              </tr>
            </thead>
            <tbody>
              {users.map((entry) => {
                const isSelf = entry.id === user.id;
                const rowBusy = busyId === entry.id;
                return (
                  <tr key={entry.id} className={entry.is_active ? "admin-row" : "admin-row is-off"}>
                    <td className="admin-name">{entry.display_name || "—"}</td>
                    <td className="admin-email">{entry.email}</td>
                    <td>{ROLE_LABELS[entry.role]}</td>
                    <td>{entry.notebooks}</td>
                    <td>{entry.notes}</td>
                    <td>{entry.blocks}</td>
                    <td>{formatBytes(entry.media_bytes)}</td>
                    <td
                      title={entry.last_login_at ? formatDate(entry.last_login_at) : "Nunca entrou"}
                    >
                      {entry.last_login_at ? relativeTime(entry.last_login_at) : "nunca"}
                    </td>
                    <td>
                      <span className={entry.is_active ? "admin-state" : "admin-state is-off"}>
                        {entry.is_active ? "ativo" : "desativado"}
                      </span>
                    </td>
                    <td className="admin-actions">
                      {isSelf ? (
                        // Own account: the backend refuses to drop or disable it, and resetting its
                        // password here would kill this very session — the user menu covers it.
                        <span className="panel-hint">sua conta</span>
                      ) : resetFor === entry.id ? (
                        <form className="admin-reset" onSubmit={(event) => reset(event, entry)}>
                          <input
                            className="input admin-reset-input"
                            type="password"
                            placeholder="Nova senha"
                            value={resetPassword}
                            autoFocus
                            disabled={rowBusy}
                            onChange={(event) => {
                              setResetPassword(event.target.value);
                              setResetError(null);
                            }}
                          />
                          <button
                            type="submit"
                            className="btn btn-compact"
                            disabled={rowBusy || resetPassword.length < MIN_PASSWORD}
                          >
                            Salvar
                          </button>
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={rowBusy}
                            onClick={() => {
                              setResetFor(null);
                              setResetPassword("");
                              setResetError(null);
                            }}
                          >
                            Cancelar
                          </button>
                          {resetError && <span className="form-error">{resetError}</span>}
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={busyId !== null}
                            onClick={() => {
                              setResetFor(entry.id);
                              setResetPassword("");
                              setResetError(null);
                            }}
                          >
                            Redefinir senha
                          </button>
                          <button
                            type="button"
                            className="btn btn-compact"
                            disabled={busyId !== null}
                            onClick={() => toggleActive(entry)}
                          >
                            {entry.is_active ? "Desativar" : "Ativar"}
                          </button>
                          <button
                            type="button"
                            className="btn btn-compact btn-danger"
                            disabled={busyId !== null}
                            onClick={() => remove(entry)}
                          >
                            Excluir
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
    </div>
  );
}
