// Minimal Markdown → HTML for the bundled Metodologia text (headings, paragraphs,
// lists, tables, bold, italics, inline code, links and `<a id="…"></a>` anchors).
// Everything else is escaped, so the output is safe to inject.

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const ANCHOR_RE = /<a id="([a-z0-9-]+)"><\/a>/g;

export function inline(text: string): string {
  const codes: string[] = [];
  let s = text.replace(/`([^`]+)`/g, (_, c: string) => {
    codes.push(`<code>${esc(c)}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  const anchors: string[] = [];
  s = s.replace(ANCHOR_RE, (_, id: string) => {
    anchors.push(`<a id="${id}" class="anchor-target"></a>`);
    return `\u0001${anchors.length - 1}\u0001`;
  });
  s = esc(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label: string, href: string) => {
    const safe = /^(#|\/|https?:\/\/)/.test(href) ? href : "#";
    const ext = safe.startsWith("http") ? ' target="_blank" rel="noopener noreferrer"' : "";
    return `<a href="${safe}"${ext}>${label}</a>`;
  });
  s = s.replace(/\u0001(\d+)\u0001/g, (_, i: string) => anchors[Number(i)]);
  return s.replace(/\u0000(\d+)\u0000/g, (_, i: string) => codes[Number(i)]);
}

function slug(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/<[^>]*>/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export interface Heading { level: number; text: string; id: string }

export function renderMarkdown(md: string): { html: string; headings: Heading[] } {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  const headings: Heading[] = [];
  let i = 0;
  const isBlockStart = (l: string) => /^(#{1,6}\s|[-*]\s|\|)/.test(l) || l.trim() === "";
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") { i++; continue; }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const raw = h[2];
      const firstAnchor = /<a id="([a-z0-9-]+)"><\/a>/.exec(raw);
      const text = raw.replace(ANCHOR_RE, "").trim();
      const id = firstAnchor ? firstAnchor[1] : slug(text);
      const extra = [...raw.matchAll(ANCHOR_RE)].slice(firstAnchor ? 1 : 0)
        .map((m) => `<a id="${m[1]}" class="anchor-target"></a>`).join("");
      headings.push({ level, text, id });
      out.push(`<h${level} id="${id}">${extra}${inline(text)}</h${level}>`);
      i++;
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
        i++;
      }
      const [head, , ...body] = rows;
      out.push("<table class=\"md-table\"><thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("")
        + "</tr></thead><tbody>" + body.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("")
        + "</tbody></table>");
      continue;
    }
    if (/^[-*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && (/^[-*]\s/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (/^[-*]\s/.test(lines[i])) items.push(lines[i].replace(/^[-*]\s+/, ""));
        else items[items.length - 1] += " " + lines[i].trim();
        i++;
      }
      out.push("<ul>" + items.map((it) => `<li>${inline(it)}</li>`).join("") + "</ul>");
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && !(para.length && isBlockStart(lines[i])) && lines[i].trim() !== "") {
      para.push(lines[i].trim());
      i++;
    }
    out.push(`<p>${inline(para.join(" "))}</p>`);
  }
  return { html: out.join("\n"), headings };
}

/** Every `id="…"` anchor in the text (used to decide whether a "Como calculamos" link has a target). */
export function anchorsIn(md: string): Set<string> {
  return new Set([...md.matchAll(/<a id="([a-z0-9-]+)"><\/a>/g)].map((m) => m[1]));
}
