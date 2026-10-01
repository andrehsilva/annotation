import { Check, GithubLogo, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { GithubStatus } from "../lib/types";
import type { ToastKind } from "./ToastStack";

interface GithubPanelProps {
  onClose: () => void;
  onError: (error: unknown) => void;
  onNotify: (message: string, kind?: ToastKind) => void;
}

/**
 * O GitHub: colar o token pessoal (escopo `gist`) e ver o que já foi publicado.
 *
 * Sem OAuth de propósito — registrar um app e passar pela tela de consentimento custava mais do que
 * o recurso vale nesta escala. O token é **pessoal**: cada conta publica na própria conta do GitHub,
 * e ele fica numa linha de servidor que nunca volta para o navegador.
 */
export function GithubPanel({ onClose, onError, onNotify }: GithubPanelProps) {
  const [status, setStatus] = useState<GithubStatus | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

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
      .githubStatus()
      .then((next) => {
        if (!cancelled) setStatus(next);
      })
      .catch((error: unknown) => {
        if (!cancelled) onError(error);
      });
    return () => {
      cancelled = true;
    };
  }, [onError]);

  const connect = useCallback(() => {
    setBusy(true);
    void api
      .githubSetToken(token.trim())
      .then((next) => {
        setStatus(next);
        setToken("");
        onNotify("Token do GitHub salvo. Publique uma nota pelo cabeçalho dela.", "success");
      })
      .catch(onError)
      .finally(() => setBusy(false));
  }, [onError, onNotify, token]);

  const forget = useCallback(() => {
    setBusy(true);
    void api
      .githubForgetToken()
      .then((next) => {
        setStatus(next);
        onNotify("Token esquecido. Os gists que já existem continuam no GitHub.", "info");
      })
      .catch(onError)
      .finally(() => setBusy(false));
  }, [onError, onNotify]);

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sheet" role="dialog" aria-modal="true" aria-label="GitHub">
        <div className="sheet-head">
          <p className="confirm-title">
            <GithubLogo size={16} weight="bold" /> GitHub
          </p>
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onClose}
            title="Fechar (Esc)"
            aria-label="Fechar o painel do GitHub"
          >
            <X size={14} weight="bold" />
          </button>
        </div>

        {status === null ? (
          <p className="panel-hint">Carregando…</p>
        ) : status.connected ? (
          <>
            <p className="panel-hint">
              <Check size={13} weight="bold" /> Token salvo. No cabeçalho de cada nota sua aparece o
              botão de publicar como gist — publicar de novo atualiza o mesmo gist.
            </p>
            {status.published.length > 0 && (
              <ul className="member-list">
                {status.published.map((entry) => (
                  <li className="member-row" key={entry.note_id}>
                    <span className="member-who">
                      <a className="link" href={entry.url} target="_blank" rel="noreferrer">
                        {entry.url}
                      </a>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="btn-row">
              <button type="button" className="btn" onClick={forget} disabled={busy}>
                Esquecer o token
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="panel-hint">
              Cole um <b>token pessoal</b> do GitHub com o escopo <b>gist</b> (Settings → Developer
              settings → Personal access tokens). Ele fica guardado no servidor do app, só para
              publicar — e o gist sai como <b>secreto</b>: quem tem o link vê, ninguém lista.
            </p>
            <div className="share-form">
              <input
                className="input"
                type="password"
                value={token}
                placeholder="ghp_... ou github_pat_..."
                onChange={(event) => setToken(event.target.value)}
                aria-label="Token do GitHub"
              />
              <button
                type="button"
                className="btn btn-primary"
                onClick={connect}
                disabled={busy || token.trim().length < 8}
              >
                Salvar token
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
