import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { PasscodeGate } from "./components/Passcode";
import { SearchPalette } from "./components/SearchPalette";
import { TopBar } from "./components/TopBar";
import { Loading } from "./components/ui";
import { Home } from "./pages/Home";
import avinCor from "./assets/avin_h_cor.png";
import avinBranco from "./assets/avin_h_branco.png";

const Fidcs = lazy(() => import("./pages/Fidcs"));
const Fidc = lazy(() => import("./pages/Fidc"));
const Groups = lazy(() => import("./pages/Groups"));
const Cedentes = lazy(() => import("./pages/Cedentes").then((m) => ({ default: m.CedentesList })));
const Cedente = lazy(() => import("./pages/Cedentes").then((m) => ({ default: m.CedentePage })));
const Status = lazy(() => import("./pages/Status"));
const Metodologia = lazy(() => import("./pages/Metodologia"));

function NotFound() {
  return <div className="page-narrow"><h1>Página não encontrada</h1><p><Link to="/">Voltar ao início</Link></p></div>;
}

export function App() {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchInit, setSearchInit] = useState("");
  const location = useLocation();
  const close = useCallback(() => { setSearchOpen(false); setSearchInit(""); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearchOpen((o) => !o); }
      else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); setSearchOpen(true); }
    };
    const onOpen = (e: Event) => { setSearchInit(String((e as CustomEvent).detail ?? "")); setSearchOpen(true); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("dash:search", onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("dash:search", onOpen); };
  }, []);
  useEffect(() => { setSearchOpen(false); }, [location.pathname]);

  return (
    <>
      <TopBar onSearch={() => setSearchOpen(true)} />
      <main className="main">
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/fidcs" element={<Fidcs />} />
            <Route path="/fidcs/:cnpj" element={<Fidc />} />
            <Route path="/gestoras" element={<Groups kind="gestoras" />} />
            <Route path="/administradores" element={<Groups kind="administradores" />} />
            <Route path="/custodiantes" element={<Groups kind="custodiantes" />} />
            <Route path="/cedentes" element={<Cedentes />} />
            <Route path="/cedentes/:cnpj" element={<Cedente />} />
            <Route path="/status" element={<Status />} />
            <Route path="/metodologia" element={<Metodologia />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </main>
      <footer className="site-foot">
        <div className="site-foot-brand">
          <img className="logo-light" src={avinCor} alt="AVIN" height={22} />
          <img className="logo-dark" src={avinBranco} alt="AVIN" height={22} />
          <span className="foot-sep" aria-hidden>|</span>
          <span className="area-tag">Empresas</span>
        </div>
        <div className="muted small">Dash FIDCs · dados públicos da CVM (informe mensal FIDC e cadastro de fundos e classes) · uso interno</div>
      </footer>
      <SearchPalette open={searchOpen} onClose={close} initial={searchInit} />
      <PasscodeGate />
    </>
  );
}
