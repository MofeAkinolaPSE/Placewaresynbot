/** Minimal Markdown for generated reports: headings, bold/italic, lists, tables, paragraphs. */
import { Fragment, ReactNode } from "react";

function inline(s: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const t = m[0];
    out.push(t.startsWith("**") ? <strong key={m.index}>{t.slice(2, -2)}</strong> : <em key={m.index}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

export function Md({ text }: { text: string }) {
  const lines = (text || "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    const h = /^(#{1,4})\s+(.*)/.exec(l);
    if (h) {
      const lvl = h[1].length;
      const cls = lvl === 1 ? "text-xl font-bold mt-2" : lvl === 2 ? "text-lg font-semibold mt-5 border-b pb-1" : "text-sm font-semibold mt-3";
      blocks.push(<div key={i} className={cls}>{inline(h[2])}</div>);
      i++; continue;
    }
    if (l.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      blocks.push(
        <div key={i} className="my-2 overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead><tr className="bg-muted/50">{rows[0]?.map((c, j) => <th key={j} className="px-2 py-1.5 text-left font-medium">{inline(c)}</th>)}</tr></thead>
            <tbody className="divide-y">{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} className="px-2 py-1 align-top">{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*([-*•]|\d+\.)\s+/.test(l)) {
      const ordered = /^\s*\d+\./.test(l);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+\.)\s+/, ""));
        i++;
      }
      const L = ordered ? "ol" : "ul";
      blocks.push(<L key={i} className={`my-1.5 space-y-0.5 pl-5 text-sm ${ordered ? "list-decimal" : "list-disc"}`}>{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</L>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\||\s*([-*•]|\d+\.)\s)/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={i} className="my-1.5 text-sm leading-relaxed">{para.map((p, k) => <Fragment key={k}>{k > 0 && " "}{inline(p)}</Fragment>)}</p>);
  }
  return <div>{blocks}</div>;
}
