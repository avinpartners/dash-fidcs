import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { api, JOB_LABELS, type ActiveJobs } from "../api";
import { useInterval } from "../lib/hooks";
import { applyTheme, storedTheme, type ThemeChoice } from "../lib/theme";
// AVIN logos (Guia de Identidade Visual): colorida no cabeçalho claro, branca no tema escuro.
import avinCor from "../assets/avin_h_cor.png";
import avinBranco from "../assets/avin_h_branco.png";

const THEME_NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "Tema: sistema", light: "Tema: claro", dark: "Tema: escuro" };
// Drawn as SVG (not text glyphs, which come from a fallback font and render tiny on Windows).
const THEME_ICON: Record<ThemeChoice, JSX.Element> = {
  system: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" />
    </svg>
  ),
  light: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6 13 13M3 13l1.4-1.4M11.6 4.4 13 3"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  dark: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path d="M13.5 10.2A6 6 0 0 1 5.8 2.5a6 6 0 1 0 7.7 7.7z" fill="none" stroke="currentColor" strokeWidth="1.5"
        strokeLinejoin="round" />
    </svg>
  ),
};

/** Shows only when it matters: an update running, or the worker stopped (the last-update time lives on Status). */
function UpdateIndicator() {
  const [active, setActive] = useState<ActiveJobs | null>(null);
  const load = () => { api.jobsActive().then(setActive).catch(() => setActive(null)); };
  useEffect(load, []);
  const running = !!active?.current || !!active?.queued.length;
  useInterval(load, running ? 5000 : 60000);
  if (running) {
    const name = active?.current?.job;
    const text = `Atualizando${name ? `: ${JOB_LABELS[name] ?? name}` : "…"}`;
    return (
      <Link to="/status" className="update-ind running" title={`${text} · ver progresso em Status dos dados`} aria-label={text}>
        <span className="spinner" aria-hidden /> <span className="update-text">{text}</span>
      </Link>
    );
  }
  if (active?.worker_alive !== false) return null;
  const text = "Atualizações: tarefas paradas";
  const title = `${text} · as atualizações automáticas não estão rodando: feche com Parar.cmd e abra de novo com Iniciar.cmd`;
  return (
    <Link to="/status" className="update-ind err" title={title} aria-label={text}>
      <span className="dot" aria-hidden />
      <span className="update-text">{text}</span>
      <span className="update-short" aria-hidden>tarefas paradas</span>
    </Link>
  );
}

const MORE = [
  { to: "/custodiantes", label: "Custodiantes" }, { to: "/status", label: "Status dos dados" },
  { to: "/metodologia", label: "Metodologia" },
];

/** "Mais": the pages the team opens less often. */
function MoreMenu() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const active = MORE.some((m) => pathname.startsWith(m.to));
  return (
    <div className="nav-more" ref={box}>
      <button type="button" className={active ? "active" : undefined} aria-haspopup="true" aria-expanded={open}
              onClick={() => setOpen((o) => !o)}>Mais <span aria-hidden>▾</span></button>
      {open && <div className="nav-more-menu">{MORE.map((m) => <NavLink key={m.to} to={m.to}>{m.label}</NavLink>)}</div>}
    </div>
  );
}

export function TopBar({ onSearch }: { onSearch: () => void }) {
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="AVIN Empresas, início">
        <img className="brand-logo logo-light" src={avinCor} alt="AVIN" height={26} />
        <img className="brand-logo logo-dark" src={avinBranco} alt="AVIN" height={26} />
        <span className="area-tag">Empresas</span>
      </Link>
      <nav className="mainnav">
        <NavLink to="/" end>Início</NavLink>
        <NavLink to="/fidcs">FIDCs</NavLink>
        <NavLink to="/gestoras">Gestoras</NavLink>
        <NavLink to="/administradores">Administradores</NavLink>
        <NavLink to="/cedentes">Cedentes</NavLink>
        <MoreMenu />
      </nav>
      <button className="search-trigger" onClick={onSearch} aria-label="Buscar (Ctrl+K)" title="Buscar FIDC, CNPJ, gestora, administrador ou cedente (Ctrl+K)">
        <span aria-hidden>⌕</span> <span className="search-text">Buscar…</span> <kbd>{mac ? "⌘" : "Ctrl"} K</kbd>
      </button>
      <UpdateIndicator />
      <button
        className="btn-icon"
        title={THEME_LABEL[theme]}
        aria-label={THEME_LABEL[theme]}
        onClick={() => { const n = THEME_NEXT[theme]; setTheme(n); applyTheme(n); }}
      >{THEME_ICON[theme]}</button>
    </header>
  );
}
