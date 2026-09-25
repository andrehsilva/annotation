import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../lib/api";
import type { User } from "../lib/types";

interface LoginViewProps {
  onLoggedIn: (user: User) => void;
}

/** The door: full screen, no sidebar and no top bar, until the cookie answers back. */
export function LoginView({ onLoggedIn }: LoginViewProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const emailRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLoggedIn(await api.login(email.trim(), password));
    } catch (failure) {
      console.error(failure);
      setError(failure instanceof ApiError ? failure.message : "Falha ao falar com a API local");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view login-view">
      <form className="panel login-card" onSubmit={(event) => void submit(event)}>
        <div className="login-brand">
          <span className="logo-mark" aria-hidden="true">
            {">_"}
          </span>
          <span className="wordmark">NotAI</span>
        </div>
        <p className="panel-hint">Entre com a sua conta para abrir os seus cadernos.</p>

        <label className="form-field">
          <span className="form-label">E-mail</span>
          <input
            ref={emailRef}
            className="input"
            type="email"
            value={email}
            autoComplete="email"
            required
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className="form-field">
          <span className="form-label">Senha</span>
          <input
            className="input"
            type="password"
            value={password}
            autoComplete="current-password"
            required
            disabled={busy}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </div>
  );
}
