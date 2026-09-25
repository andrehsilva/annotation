import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../lib/api";
import type { ToastKind } from "./ToastStack";

interface PasswordPanelProps {
  onClose: () => void;
  onNotify: (message: string, kind?: ToastKind) => void;
}

const MIN_LENGTH = 8;

/** Self-service password change: the admin resets other people's, this one is the user's own door. */
export function PasswordPanel({ onClose, onNotify }: PasswordPanelProps) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next.length < MIN_LENGTH) {
      setError(`A nova senha precisa de pelo menos ${MIN_LENGTH} caracteres`);
      return;
    }
    if (next !== repeat) {
      setError("A repetição não bate com a nova senha");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.changePassword(current, next);
      onNotify("Senha alterada", "success");
      onClose();
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Falha ao falar com a API local");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <form
        className="confirm"
        role="dialog"
        aria-modal="true"
        aria-label="Trocar senha"
        onSubmit={(event) => void submit(event)}
      >
        <div className="confirm-head">
          <p className="confirm-title" id="password-title">
            Trocar senha
          </p>
        </div>

        <div className="password-fields">
          <label className="form-field">
            <span className="form-label">Senha atual</span>
            <input
              className="input"
              type="password"
              value={current}
              autoComplete="current-password"
              required
              autoFocus
              disabled={busy}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="form-label">Nova senha</span>
            <input
              className="input"
              type="password"
              value={next}
              autoComplete="new-password"
              required
              disabled={busy}
              onChange={(event) => setNext(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="form-label">Repetir a nova senha</span>
            <input
              className="input"
              type="password"
              value={repeat}
              autoComplete="new-password"
              required
              disabled={busy}
              onChange={(event) => setRepeat(event.target.value)}
            />
          </label>
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <p className="panel-hint">
          Mínimo de {MIN_LENGTH} caracteres. As outras sessões abertas caem; esta continua.
        </p>

        <div className="confirm-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Salvando..." : "Trocar senha"}
          </button>
        </div>
      </form>
    </div>
  );
}
