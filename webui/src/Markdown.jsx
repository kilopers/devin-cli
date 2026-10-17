// Devin's answer is markdown — render it to sanitized HTML with syntax
// highlighting (marked + DOMPurify + highlight.js, all bundled — no CDN).
import { useEffect, useMemo, useRef } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";

export default function Markdown({ text }) {
  const ref = useRef(null);
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true })),
    [text]);
  useEffect(() => {
    ref.current?.querySelectorAll("pre code").forEach(c => {
      try { hljs.highlightElement(c); } catch (e) { /* keep raw block */ }
    });
  }, [html]);
  return <div ref={ref} className="md"
              dangerouslySetInnerHTML={{ __html: html }} />;
}
