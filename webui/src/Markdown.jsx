// Devin's answer is markdown — render it to sanitized HTML with syntax
// highlighting (marked + DOMPurify + highlight.js, all bundled — no CDN).
import React, { useEffect, useMemo, useRef } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";

// diff fences are colored line-by-line by hand — the github-dark hljs
// theme ships no colors for .hljs-addition/.hljs-deletion at all, so
// highlighted diffs came out pale/invisible; our own spans are guaranteed.
const esc = s => s.replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function paintDiff(codeEl) {
  codeEl.innerHTML = codeEl.textContent.split("\n").map(l => {
    const cls =
      l.startsWith("+++") || l.startsWith("---") ? "meta"
      : l.startsWith("+") ? "add"
      : l.startsWith("-") ? "del"
      : l.startsWith("@@") ? "hunk" : "";
    return `<span class="dline ${cls}">${esc(l)}</span>`;
  }).join("\n");
}

export default React.memo(function Markdown({ text }) {
  const ref = useRef(null);
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(typeof text === "string" ? text : "", { breaks: true, gfm: true })),
    [text]);
  // repaint only when html really changed: React.memo + этот dep —
  // раньше эффект гонялся на КАЖДЫЙ рендер и paintDiff перезаписывал
  // innerHTML, снося выделение текста в модалке на каждом поллинге.
  // paintDiff idempotent; hljs skips already-highlighted nodes.
  useEffect(() => {
    ref.current?.querySelectorAll("pre code").forEach(c => {
      if ((c.className || "").includes("language-diff")) {
        paintDiff(c);
        return;
      }
      try { hljs.highlightElement(c); } catch (e) { /* keep raw block */ }
    });
  }, [html]);
  return <div ref={ref} className="md"
              dangerouslySetInnerHTML={{ __html: html }} />;
});
