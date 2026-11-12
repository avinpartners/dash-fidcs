// Shown when an /api call answers 401 (APP_PASSCODE set in .env).
import { useEffect, useState } from "react";
import { api } from "../api";

export function PasscodeGate() {
  const [needed, setNeeded] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const on = () => setNeeded(true);
    window.addEventListener("dash:passcode", on);
    return () => window.removeEventListener("dash:passcode", on);
  }, []);
  if (!needed) return null;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(code);
      window.location.reload();
    } catch {
      setError("Senha incorreta.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="passcode-backdrop">
      <form className="passcode card" onSubmit={submit}>
        <h1>Dash FIDCs</h1>
        <p className="muted">Este painel está protegido por uma senha compartilhada da equipe.</p>
        <label htmlFor="passcode">Senha</label>
        <input id="passcode" type="password" autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy || !code}>{busy ? "Entrando…" : "Entrar"}</button>
      </form>
    </div>
  );
}
