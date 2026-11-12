// Metodologia: how every number is read from the CVM files (src/content/metodologia.md).
import { useMemo } from "react";
import metodologia from "../content/metodologia.md?raw";
import { renderMarkdown } from "../lib/markdown";
import { useDocumentTitle } from "../lib/hooks";

export default function Metodologia() {
  useDocumentTitle("Metodologia");
  const { html, headings } = useMemo(() => renderMarkdown(metodologia), []);
  const toc = headings.filter((h) => h.level === 2);
  return (
    <div className="metodologia">
      <aside className="toc">
        <div className="toc-title">Nesta página</div>
        {toc.map((h) => <a key={h.id} href={`#${h.id}`}>{h.text}</a>)}
      </aside>
      <article className="prose" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
