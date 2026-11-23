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

// URL внутри <code>/<pre> marked принципиально не линкует — весь текст
// там «сырой код». Пост-проход по DOM: http(s):// в текстовых уздах
// оборачиваем в <a>, ссылка становится кликабельной и в code-блоке.
// stopPropagation — клик по ссылке не должен раскрывать карточку/пузырь.
const URL_RE = /https?:\/\/[^\s<>"'`]+/g;

function linkifyCode(codeEl) {
  const walker = document.createTreeWalker(codeEl, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);
  for (const tn of nodes) {
    if (tn.parentElement?.closest("a")) continue;
    const text = tn.nodeValue || "";
    URL_RE.lastIndex = 0;
    if (!URL_RE.test(text)) continue;
    URL_RE.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0, m;
    while ((m = URL_RE.exec(text))) {
      const url = m[0].replace(/[.,;:!?)\]]+$/, "");
      frag.append(document.createTextNode(text.slice(last, m.index)));
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = url;
      a.addEventListener("click", e => e.stopPropagation());
      frag.append(a, document.createTextNode(m[0].slice(url.length)));
      last = m.index + m[0].length;
    }
    frag.append(document.createTextNode(text.slice(last)));
    tn.parentNode.replaceChild(frag, tn);
  }
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
      } else {
        try { hljs.highlightElement(c); } catch (e) { /* keep raw block */ }
      }
      linkifyCode(c);
    });
    ref.current?.querySelectorAll(":not(pre) > code").forEach(linkifyCode);
  }, [html]);
  return <div ref={ref} className="md"
              dangerouslySetInnerHTML={{ __html: html }} />;
});
