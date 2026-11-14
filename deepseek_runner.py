#!/usr/bin/env python3
"""deepseek_runner — движок «deepseek» реестра AGENTS: задача через
DeepSeek chat.completions API с function-calling инструментами
(bash/read_file/write_file/list_dir), исполняемыми локально в
DEVIN_WORKDIR — аналог `claude -p`, только сам ходим в API.

env-контракт как у devin-task/claude-task:
  DEVIN_TASK_FILE   промпт уже собран лаунчером в файл
  DEVIN_WORKDIR     рабочий каталог репо
  DEVIN_MODEL       deepseek-chat (дефолт) / deepseek-reasoner
  DEVIN_EXPORT_FILE финальный result-JSON (usage/session_id/result)
  DEVIN_EXTRA_ARGS  --resume <sid> — продолжить пинненую сессию темы
  DEVIN_CONTINUE    "true" → --continue: последняя сессия workdir'а
  DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_SESS_DIR

Сессии — свои: <SESS_DIR>/<sid>.jsonl с messages (resume их
проигрывает), пин topics.session_id хранит наш sid. Живой транскрипт
<sid>.json (NDJSON-шаги source=agent/tool) — его хвостит
progress_loop/_digest_new_steps. stdout — читаемые маркеры
💬/🔧/└/⛔/🏁 (тот же формат, что у claude-relay) → .progress/<stem>.out.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("DEEPSEEK_BASE_URL",
                      "https://api.deepseek.com").rstrip("/")
KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEVIN_MODEL") or "deepseek-chat"
WORKDIR = Path(os.environ.get("DEVIN_WORKDIR", "/workspace"))
TASK_FILE = os.environ.get("DEVIN_TASK_FILE", "/task/task.txt")
EXPORT = os.environ.get("DEVIN_EXPORT_FILE", "")
SESS_DIR = Path(os.environ.get(
    "DEEPSEEK_SESS_DIR", "/tasks/sessions/deepseek"))
MAX_TURNS = 120
OUT_CAP = 8000        # хвост вывода инструмента в контекст
HIST_MSGS = 60        # сколько последних сообщений держим при resume/росте

_USAGE_KEYS = ("prompt_tokens", "completion_tokens",
               "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
               "total_tokens")


def emit(s: str) -> None:
    print(s, flush=True)


def _sanitized(msgs: list) -> list:
    """Валидная для API история: после усечения/резюма могут остаться
    tool-ответы-сироты или assistant.tool_calls без ответов — API их
    отвергает (400). Сироты выкидываем, недостающие ответы добиваем
    заглушками."""
    call_ids = {tc.get("id") for m in msgs
                for tc in (m.get("tool_calls") or [])}
    tool_ids = {m.get("tool_call_id") for m in msgs
                if m.get("role") == "tool"}
    out = []
    for m in msgs:
        if m.get("role") == "tool" \
                and m.get("tool_call_id") not in call_ids:
            continue
        out.append(m)
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if tc.get("id") and tc.get("id") not in tool_ids:
                    out.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": (tc.get("function") or {}).get("name"),
                        "content": "(ответ утерян при усечении истории)"})
    return out


def api_call(messages: list, tools=None, tries: int = 4) -> dict:
    body = {"model": MODEL, "messages": _sanitized(messages)}
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                BASE + "/chat/completions", data=data,
                headers={"Authorization": "Bearer " + KEY,
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (400, 401, 403):
                break                      # смысла ретраить нет
        except Exception as e:
            last = str(e)
        time.sleep(min(2 ** i * 5, 60))
    raise RuntimeError(f"deepseek API failed after {tries} tries: {last}")


# ---------------------------------------------------------------- tools

def _t_bash(command: str) -> str:
    try:
        p = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=180)
        out = (p.stdout + p.stderr).strip() or f"(exit {p.returncode})"
        return f"exit={p.returncode}\n{out[-OUT_CAP:]}"
    except subprocess.TimeoutExpired:
        return "exit=124\ncommand timed out (180s)"
    except Exception as e:
        return f"error: {e}"


def _resolve(path: str) -> Path:
    p = (WORKDIR / path).resolve() if not os.path.isabs(path) \
        else Path(path).resolve()
    try:
        p.relative_to(WORKDIR.resolve())
    except ValueError:
        raise RuntimeError(f"путь вне workdir: {path}")
    return p


def _t_read(path: str, offset: int = 0, limit: int = 400) -> str:
    try:
        lines = _resolve(path).read_text(
            errors="replace").splitlines()
    except Exception as e:
        return f"error: {e}"
    sel = lines[int(offset):int(offset) + int(limit)]
    return "\n".join(f"{int(offset) + i + 1}|{ln}"
                     for i, ln in enumerate(sel))[:20000] \
        or "(пустой файл)"


def _t_write(path: str, content: str) -> str:
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"written {p} ({len(content)} chars)"
    except Exception as e:
        return f"error: {e}"


def _t_ls(path: str = ".") -> str:
    try:
        ents = sorted(_resolve(path).iterdir(),
                      key=lambda e: e.name)[:300]
        return "\n".join(
            e.name + ("/" if e.is_dir() else "") for e in ents) or "(пусто)"
    except Exception as e:
        return f"error: {e}"


TOOL_IMPL = {
    "bash": lambda a: _t_bash(a.get("command") or ""),
    "read_file": lambda a: _t_read(a.get("path") or "",
                                   a.get("offset") or 0,
                                   a.get("limit") or 400),
    "write_file": lambda a: _t_write(a.get("path") or "",
                                     a.get("content") or ""),
    "list_dir": lambda a: _t_ls(a.get("path") or "."),
}

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description":
            "Выполнить shell-команду в каталоге репозитория "
            "(grep/find/git/python и т.п.). Возвращает exit code и "
            "хвост вывода.",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"}},
                       "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description":
            "Прочитать файл из репозитория (нумерованные строки, "
            "смещение+лимит для постраничного чтения).",
        "parameters": {"type": "object",
                       "properties": {
                           "path": {"type": "string"},
                           "offset": {"type": "integer", "default": 0},
                           "limit": {"type": "integer", "default": 400}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description":
            "Записать файл в репозиторий (создаёт каталоги).",
        "parameters": {"type": "object",
                       "properties": {
                           "path": {"type": "string"},
                           "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_dir", "description": "Список файлов каталога.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string",
                                               "default": "."}}}}},
]


# ---------------------------------------------------------------- session

def _sess_file(sid: str) -> Path:
    return SESS_DIR / f"{sid}.jsonl"


def _load_session(sid: str) -> list:
    try:
        return json.loads(_sess_file(sid).read_text())
    except Exception:
        return []


def _save_session(sid: str, messages: list, tr: Path) -> None:
    try:
        SESS_DIR.mkdir(parents=True, exist_ok=True)
        _sess_file(sid).write_text(
            json.dumps(messages, ensure_ascii=False))
        (SESS_DIR / f"last-{_wd_key()}").write_text(sid)
    except Exception:
        pass


def _wd_key() -> str:
    return str(abs(hash(str(WORKDIR.resolve()))))


def _last_sid() -> str | None:
    try:
        return (SESS_DIR / f"last-{_wd_key()}").read_text().strip() or None
    except Exception:
        return None


def _transcript_write(tr: Path, step: int, source: str,
                      message: str) -> None:
    try:
        with tr.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"step_id": step, "source": source,
                                "message": message},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def _truncate(messages: list) -> list:
    """Окно контекста: системное + первый user + последние HIST_MSGS."""
    if len(messages) <= HIST_MSGS + 2:
        return messages
    head = [m for m in messages if m.get("role") == "system"][:1]
    first_u = [m for m in messages if m.get("role") == "user"][:1]
    tail = messages[-HIST_MSGS:]
    return head + first_u + tail


# ---------------------------------------------------------------- main

def main() -> int:
    if not KEY:
        emit("⛔ DEEPSEEK_API_KEY не задан — добавь его в настройках "
             "(Движки агентов)")
        return 2
    argv = sys.argv[1:]
    resume = None
    if "--resume" in argv:
        i = argv.index("--resume")
        if i + 1 < len(argv):
            resume = argv[i + 1]
    cont = "--continue" in argv or \
        os.environ.get("DEVIN_CONTINUE") == "true"

    sid = resume or (_last_sid() if cont else None) or uuid.uuid4().hex[:12]
    tr = SESS_DIR / f"{sid}.json"
    messages = _load_session(sid) if (resume or cont) else []

    try:
        prompt = Path(TASK_FILE).read_text(errors="replace")
    except Exception as e:
        emit(f"⛔ task file: {e}")
        return 2
    if not messages:
        messages = [{"role": "user", "content": prompt}]
    else:
        messages.append({"role": "user", "content": prompt})
        messages = _truncate(messages)
    if (resume or cont) and not _load_session(sid):
        emit("⚠ session not found — стартую чистую")

    # reasoner не умеет function calling; у прочих моделей (включая
    # совместимые прокси через DEEPSEEK_BASE_URL) инструменты включены
    tools = None if "reasoner" in MODEL.lower() else TOOLS
    emit(f"🚀 deepseek {MODEL} session {sid}"
         + (" · resumed" if len(messages) > 1 else "")
         + ("" if tools else " · без инструментов"))

    step = 0
    result_text, usage_all = "", {}
    started = time.time()
    try:
        for _ in range(MAX_TURNS):
            resp = api_call(messages, tools)
            u = resp.get("usage") or {}
            # суммируем по вызовам: у tool-цикла N запросов к API,
            # последний usage описывает лишь финальный — статистика
            # и цена задачи занижались бы в разы
            for k in _USAGE_KEYS:
                if isinstance(u.get(k), (int, float)):
                    usage_all[k] = usage_all.get(k, 0) + u[k]
            msg = (resp.get("choices") or [{}])[0].get("message") or {}
            messages.append(msg)
            text = (msg.get("content") or "").strip()
            calls = msg.get("tool_calls") or []
            if text:
                result_text = text
                step += 1
                emit("💬 " + " ".join(text.split())[:300])
                _transcript_write(tr, step, "agent", text)
            if not calls:
                break
            for tc in calls:
                fn = (tc.get("function") or {})
                name = fn.get("name") or "tool"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                brief = (args.get("command") or args.get("path") or "")
                brief = " ".join(str(brief).split())[:140]
                emit(f"🔧 {name} {brief}".rstrip())
                step += 1
                _transcript_write(tr, step, "tool", f"{name} {brief}")
                impl = TOOL_IMPL.get(name)
                try:
                    out = impl(args) if impl else f"unknown tool {name}"
                except Exception as e:
                    out = f"error: {e}"
                is_err = str(out).startswith(("error", "unknown"))
                emit(("⛔ " if is_err else "  └ ")
                     + " ".join(str(out).split())[:200])
                messages.append({"role": "tool",
                                 "tool_call_id": tc.get("id"),
                                 "name": name,
                                 "content": str(out)})
        else:
            emit("⛔ max turns reached")
    except Exception as e:
        emit(f"⛔ {e}")
        result_text = result_text or f"Ошибка deepseek: {e}"
        rc = 1
    else:
        rc = 0

    _save_session(sid, messages, tr)
    dur = time.time() - started
    emit(f"🏁 done · {dur:.0f}s · tokens "
         f"{usage_all.get('total_tokens', '?')}")
    if EXPORT:
        try:
            with open(EXPORT, "w", encoding="utf-8") as f:
                json.dump({"type": "result", "result": result_text,
                           "session_id": sid, "model": MODEL,
                           "usage": usage_all,
                           "duration_ms": int(dur * 1000)},
                          f, ensure_ascii=False)
        except OSError:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
