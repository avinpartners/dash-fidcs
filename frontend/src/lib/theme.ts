// Light/dark theme: "system" follows prefers-color-scheme; the choice is kept in localStorage.
import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "dash-fidcs-theme";
const EVENT = "dash-theme-change";

export function storedTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch { /* private window or blocked storage: the choice lasts for this page only */ }
  window.dispatchEvent(new Event(EVENT));
}

function systemDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function effectiveTheme(): "light" | "dark" {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return systemDark() ? "dark" : "light";
}

/** Re-renders when the effective theme changes (toggle or OS setting). */
export function useEffectiveTheme(): "light" | "dark" {
  const [t, setT] = useState(effectiveTheme);
  useEffect(() => {
    const update = () => setT(effectiveTheme());
    window.addEventListener(EVENT, update);
    const mq = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    mq?.addEventListener?.("change", update);
    return () => {
      window.removeEventListener(EVENT, update);
      mq?.removeEventListener?.("change", update);
    };
  }, []);
  return t;
}

/** Reads a CSS custom property from :root (chart colours follow the tokens in styles.css). */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
