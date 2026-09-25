import { CloudArrowUp, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import type { ConfirmRequest } from "./ConfirmDialog";
import { api } from "../lib/api";
import { relativeTime } from "../lib/format";
import type { DriveStatus, SyncSummary } from "../lib/types";

type Busy = "upload" | "connect" | "sync" | "settings" | null;

interface DrivePanelProps {
  status: DriveStatus;
  /** A finished action asks the app to reload the status; a summary also becomes a toast. */
  onChanged: (summary: SyncSummary | null) => void;
  onAskConfirm: (request: ConfirmRequest) => void;
  onClose: () => void;
  onError: (error: unknown) => void;
}

/** Export to Drive: the credentials dance, the sync button and the last run, in one sheet. */
export function DrivePanel({ status, onChanged, onAskConfirm, onClose, onError }: DrivePanelProps) {
  const [busy, setBusy] = useState<Busy>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  const run = (kind: Busy, action: () => Promise<void>) => {
    setBusy(kind);
    void action()
      .catch(onError)
      .finally(() => setBusy(null));
  };

  const uploadClient = (file: File) =>
    run("upload", async () => {
      await api.driveUploadClient(file);
      onChanged(null);
    });

  const connect = () =>
    run("connect", async () => {
      await api.driveConnect();
      onChanged(null);
    });

  const syncNow = () => run("sync", async () => onChanged(await api.driveSync()));

  const setAuto = (enabled: boolean) =>
    run("settings", async () => {
      await api.driveSetAutoSync(enabled);
      onChanged(null);
    });

  const disconnect = () =>
    onAskConfirm({
      title: "Desconectar do Google Drive",
      message:
        "O NotAI deixa de enviar as notas. Os arquivos já enviados continuam no seu Drive; ao reconectar, os vínculos são recriados.",
      confirmLabel: "Desconectar",
      danger: true,
      action: async () => {
        try {
          await api.driveDisconnect();
          onChanged(null);
        } catch (error) {
          onError(error);
        }
      },
    });

  const summary = status.last_summary;

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Backup no Google Drive">
        <div className="sheet-head">
          <p className="confirm-title">
            <CloudArrowUp size={16} weight="bold" /> Backup no Google Drive
          </p>
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onClose}
            disabled={busy !== null}
            aria-label="Fechar"
          >
            <X size={14} weight="bold" />
          </button>
        </div>

        {status.connected ? (
          <>
            <p className="panel-hint">
              {status.last_sync_at
                ? `Último envio ${relativeTime(status.last_sync_at)}`
                : "Conectado, nada enviado ainda."}
            </p>
            {summary && (
              <p className="panel-hint">
                {summary.notes_sent} notas enviadas · {summary.notes_unchanged} sem mudança ·{" "}
                {summary.media_sent} mídias
                {summary.skipped_media > 0
                  ? ` · ${summary.skipped_media} mídias locais fora do .md`
                  : ""}
              </p>
            )}
            {status.pending && <p className="panel-hint">Envio automático agendado.</p>}
            {status.last_error && <p className="panel-hint is-error">{status.last_error}</p>}
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-primary"
                onClick={syncNow}
                disabled={busy !== null}
              >
                {busy === "sync" ? "Enviando..." : "Sincronizar agora"}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={disconnect}
                disabled={busy !== null}
              >
                Desconectar
              </button>
            </div>
            <label className="drive-toggle">
              <input
                type="checkbox"
                checked={status.auto_sync}
                disabled={busy !== null}
                onChange={(event) => setAuto(event.target.checked)}
              />
              Enviar automaticamente ao editar
            </label>
          </>
        ) : status.has_client_file ? (
          <>
            <p className="panel-hint">
              O NotAI cria a pasta <b>NotAI</b> no seu Drive, uma subpasta por caderno e um arquivo
              .md por nota. Nada é lido nem apagado no Drive.
            </p>
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-primary"
                onClick={connect}
                disabled={busy !== null}
              >
                <CloudArrowUp size={15} weight="bold" /> Conectar com o Google
              </button>
            </div>
            {busy === "connect" && (
              <p className="panel-hint">
                Autorize na janela do navegador que abriu. A página volta sozinha.
              </p>
            )}
          </>
        ) : (
          <>
            <p className="panel-hint">
              O envio é de mão única: o NotAI escreve no seu Drive e nunca lê nem apaga nada lá.
              Para começar, crie as credenciais no Google Cloud:
            </p>
            <ol className="drive-steps">
              <li>
                Abra o{" "}
                <a
                  className="link"
                  href="https://console.cloud.google.com/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Google Cloud Console
                </a>{" "}
                e crie um projeto (ex.: NotAI).
              </li>
              <li>
                Em “APIs e serviços” → Biblioteca, ative a <b>Google Drive API</b>.
              </li>
              <li>
                Em “Tela de permissão OAuth”, escolha o tipo <b>Externo</b>, use <b>NotAI</b> como
                nome e adicione o seu e-mail em “Usuários de teste”.
              </li>
              <li>
                Em “Credenciais” → Criar credenciais → ID do cliente OAuth, escolha{" "}
                <b>Aplicativo para computador</b> e baixe o JSON.
              </li>
              <li>Envie o JSON baixado aqui embaixo e clique em conectar.</li>
            </ol>
            <div className="btn-row">
              <label className={busy ? "btn btn-file is-disabled" : "btn btn-file"}>
                {busy === "upload" ? "Enviando..." : "Enviar o JSON do cliente OAuth"}
                <input
                  type="file"
                  accept="application/json,.json"
                  disabled={busy !== null}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) uploadClient(file);
                  }}
                />
              </label>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
