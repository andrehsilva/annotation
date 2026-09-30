import { useState } from "react";

import type { User } from "../lib/types";
import { AdminGroups } from "./AdminGroups";
import { AdminUsers } from "./AdminUsers";
import type { ConfirmRequest } from "./ConfirmDialog";
import type { ToastKind } from "./ToastStack";

interface AdminViewProps {
  /** The admin looking at the screen: their own row has no way out of the app. */
  user: User;
  onError: (error: unknown) => void;
  onNotify: (message: string, kind?: ToastKind) => void;
  onAskConfirm: (request: ConfirmRequest) => void;
}

/**
 * A área do admin, em duas abas: **Usuários** (as contas) e **Grupos** (o público do
 * compartilhamento). As duas coisas são decisão do admin, e nenhuma delas aparece para quem não é.
 */
export function AdminView(props: AdminViewProps) {
  const [tab, setTab] = useState<"users" | "groups">("users");

  return (
    <div className="view">
      <header className="view-head">
        <div className="view-head-main">
          <h1 className="view-title">Admin</h1>
          <p className="view-lede">
            {tab === "users"
              ? "Cada conta vê as próprias notas — e as que forem compartilhadas com os grupos dela. Na sua própria linha as ações ficam fora: o backend recusa desativar ou apagar a própria conta, e a sua senha se troca pelo menu do usuário."
              : "O grupo é o público do compartilhamento: o dono da nota escolhe um grupo, não pessoas, e quem está nele alcança a nota — inclusive quem entrar depois."}
          </p>
        </div>
        <nav className="seg-tabs" aria-label="Seções do admin">
          <button
            type="button"
            className={tab === "users" ? "seg-tab is-active" : "seg-tab"}
            aria-pressed={tab === "users"}
            onClick={() => setTab("users")}
          >
            Usuários
          </button>
          <button
            type="button"
            className={tab === "groups" ? "seg-tab is-active" : "seg-tab"}
            aria-pressed={tab === "groups"}
            onClick={() => setTab("groups")}
          >
            Grupos
          </button>
        </nav>
      </header>

      {tab === "users" ? (
        <AdminUsers
          user={props.user}
          onError={props.onError}
          onNotify={props.onNotify}
          onAskConfirm={props.onAskConfirm}
        />
      ) : (
        <AdminGroups
          onError={props.onError}
          onNotify={props.onNotify}
          onAskConfirm={props.onAskConfirm}
        />
      )}
    </div>
  );
}
