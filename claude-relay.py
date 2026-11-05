#!/usr/bin/env python3
"""claude-relay — мост stream-json Claude Code -> живой лог + export.

Читает NDJSON-события `claude -p --output-format stream-json --verbose`
со stdin, печатает читаемые строки в stdout (их пишет .progress/<stem>.out
и читает живая консоль 📄) и сохраняет финальное {"type":"result"} в файл
экспорта (argv[1]) — оттуда движок собирает статистику задачи.
"""
import json
import sys


def _fmt_tool(b: dict) -> str:
    name = b.get("name") or "tool"
    inp = b.get("input") or {}
    brief = (inp.get("command") or inp.get("file_path")
             or inp.get("pattern") or inp.get("description")
             or inp.get("prompt") or "")
    brief = " ".join(str(brief).split())[:140]
    return f"🔧 {name} {brief}".rstrip()


def main() -> int:
    export = sys.argv[1] if len(sys.argv) > 1 else ""
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            print(line, file=out, flush=True)
            continue
        t = ev.get("type")
        if t == "assistant":
            for b in (ev.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    print("💬 " + " ".join(b["text"].split())[:300],
                          file=out, flush=True)
                elif b.get("type") == "tool_use":
                    print(_fmt_tool(b), file=out, flush=True)
        elif t == "user":
            # краткий итог tool_result — флаг успеха без простыни вывода
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "")
                                     for x in c if isinstance(x, dict))
                    c = " ".join(str(c or "").split())[:200]
                    if c:
                        mark = "⛔" if b.get("is_error") else "  └"
                        print(f"{mark} {c}", file=out, flush=True)
        elif t == "result":
            if export:
                try:
                    with open(export, "w", encoding="utf-8") as f:
                        json.dump(ev, f, ensure_ascii=False)
                except OSError:
                    pass
            dur = (ev.get("duration_ms") or 0) / 1000
            cost = ev.get("total_cost_usd")
            tail = f" · ${cost:.4f}" if isinstance(cost, (int, float)) else ""
            print(f"🏁 {ev.get('subtype') or 'result'} · "
                  f"{dur:.0f}s{tail}", file=out, flush=True)
        elif t == "system" and ev.get("subtype") == "init":
            print("🚀 claude session started", file=out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
