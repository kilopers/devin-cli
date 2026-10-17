#!/usr/bin/env python3
"""Watch a tasks directory and run each incoming task through Devin CLI.

Layout (TASKS_DIR, default /tasks):

    inbox/    drop *.txt task files here
    done/     processed task files are moved here
    outbox/   devin's full output is written here as <name>.response.txt

For every new file in inbox/ the watcher runs /usr/local/bin/devin-task
(which pulls the repo, runs `devin -p` and pushes the result), captures its
output into outbox/, then moves the task file to done/.
Tasks run sequentially, oldest first.
"""

import array
import base64
import functools
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, \
    request, session
from waitress import serve
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pymysql
    import pymysql.cursors
except ImportError:
    pymysql = None

TASKS_DIR = Path(os.environ.get("TASKS_DIR", "/tasks"))
INBOX = TASKS_DIR / "inbox"
DONE = TASKS_DIR / "done"
OUTBOX = TASKS_DIR / "outbox"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "7200"))  # 2h
DEVIN_TASK = os.environ.get("DEVIN_TASK_BIN", "/usr/local/bin/devin-task")
BOT_SCRIPT = os.environ.get("BOT_SCRIPT", "/app/bot.py")
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WORKDIR = Path(os.environ.get("DEVIN_WORKDIR", "/workspace"))
# Multi-project mode: a directory whose direct subdirectories are projects.
# Active only when DEVIN_PROJECTS_DIR contains at least one subfolder;
# otherwise the legacy single WORKDIR mode is used.
PROJECTS_ROOT = Path(os.environ["DEVIN_PROJECTS_DIR"]) \
    if os.environ.get("DEVIN_PROJECTS_DIR") else None

# Telegram webhook bridge: voice -> Gemini STT -> task file; replies go back
# to the originating chat. Set TELEGRAM_WEBHOOK_URL to enable registration.
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
TG_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# STT provider for voice messages: "gemini" or "openai" (OpenAI-compatible
# /audio/transcriptions — works for api.openai.com, Groq, etc.)
STT_PROVIDER = os.environ.get("STT_PROVIDER", "gemini")
STT_API_KEY = os.environ.get("STT_API_KEY", "")
STT_BASE_URL = os.environ.get("STT_BASE_URL", "https://api.openai.com/v1")
STT_MODEL = os.environ.get("STT_MODEL", "whisper-1")
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")
YANDEX_LANG = os.environ.get("YANDEX_LANG", "ru-RU")
# CI build status for the «Изменения» panel: PATs for private repos —
# GitHub needs actions:read, GitLab needs read_api. Empty = public only.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "")
GITLAB_BASE_URL = os.environ.get("GITLAB_BASE_URL",
                                 "https://gitlab.com").rstrip("/")
# Web UI pages are Jinja2 templates rendered by Flask (render_template):
# templates/login.html — MUI login form, templates/webui.html — main page.
TEMPLATES_DIR = Path(os.environ.get("TEMPLATES_DIR", "/app/templates"))
# App version — single file VERSION bumped every change (see AGENTS.md),
# shown in the web header next to the title.
APP_VERSION = (Path(os.environ.get("VERSION_FILE", "/app/VERSION"))
               .read_text().strip()
               if Path(os.environ.get("VERSION_FILE", "/app/VERSION")).exists()
               else "dev")
# Web UI auth: single admin account. The password hash lives in
# kv.admin_password_hash — seeded from WEB_ADMIN_PASSWORD on first use,
# afterwards the profile page rewrites the kv copy (env is a bootstrap only).
# Empty WEB_ADMIN_PASSWORD and no seeded hash = auth disabled (local dev).
WEB_ADMIN_USER = os.environ.get("WEB_ADMIN_USER", "admin")
WEB_ADMIN_PASSWORD = os.environ.get("WEB_ADMIN_PASSWORD", "")
WEB_SESSION_SECRET = os.environ.get("WEB_SESSION_SECRET", "")
# Вся персистентность — в MySQL (сервис `mysql` из compose). На диске остаются
# только транзитные артефакты выполнения: .progress/<stem>.out (живой вывод
# devin) и .progress/<stem>.json (экспорт транскрипта для статистики).
MYSQL = {
    "host": os.environ.get("MYSQL_HOST", "mysql"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "devin"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "devin_worker"),
    "charset": "utf8mb4",
    "autocommit": True,
    "cursorclass": pymysql.cursors.DictCursor if pymysql else None,
}
# mihomo (Clash Meta) — встроенный прокси: бинарь в образе, конфиг монтируется
# с хоста. Стартует только при наличии config.yaml, слушает 127.0.0.1:7890.
MIHOMO_DIR = Path(os.environ.get("MIHOMO_DIR", "/mihomo"))
MIHOMO_PROXY = os.environ.get("MIHOMO_PROXY", "http://127.0.0.1:7890")

_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
if _proxy:
    TG_OPENER = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": _proxy, "https": _proxy})
    )
else:
    TG_OPENER = urllib.request.build_opener()

# Яндекс (SpeechKit) ходит напрямую всегда — как git: пустой ProxyHandler
# игнорирует и явный прокси, и *_proxy env (РФ-сервису европейский выход
# mihomo не нужен и может быть заблокирован).
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_bot_proc: subprocess.Popen | None = None
_task_proc: subprocess.Popen | None = None  # running devin-task, killable via telegram
_mihomo_proc: subprocess.Popen | None = None
_started_at = time.time()

STATE = {
    "current_task": None,
    "last_task": "-",
    "last_status": "-",
    "tasks_done": 0,
    "stt": None,   # live web-STT status text, shown in the UI
}


def log(msg: str) -> None:
    print(f"[watcher] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


# --- MySQL ------------------------------------------------------------------
# Одно соединение на поток (вотчер многопоточный: http-сервер, telegram-
# колбэки, прогресс-тред). autocommit — транзакции не нужны, запросы точечные.

_db_tls = threading.local()


def db():
    """Per-thread pymysql connection with transparent reconnect."""
    conn = getattr(_db_tls, "conn", None)
    if conn is None or not conn.open:
        conn = pymysql.connect(**MYSQL)
        _db_tls.conn = conn
    conn.ping(reconnect=True)
    return conn


def db_query(sql: str, params=()) -> list:
    with db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def db_exec(sql: str, params=()) -> int:
    with db().cursor() as cur:
        return cur.execute(sql, params)


def kv_get(key: str, default: str = "") -> str:
    rows = db_query("SELECT v FROM kv WHERE k=%s", (key,))
    return rows[0]["v"] if rows else default


def kv_set(key: str, val: str) -> None:
    db_exec("INSERT INTO kv (k, v) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE v=VALUES(v)", (key, val))


def init_db() -> None:
    """Create tables and retry until MySQL is up (first boot takes a while)."""
    if pymysql is None:
        log("FATAL: pymysql not installed — worker cannot store state")
        raise SystemExit(1)
    for attempt in range(1, 61):
        try:
            db()
            break
        except Exception as e:
            log(f"mysql not ready ({e}); retry {attempt}/60")
            time.sleep(2)
    else:
        log("FATAL: mysql unreachable after 120s — giving up")
        raise SystemExit(1)
    db_exec("""CREATE TABLE IF NOT EXISTS tasks (
        stem VARCHAR(80) PRIMARY KEY,
        source VARCHAR(16) NOT NULL DEFAULT 'file',
        project VARCHAR(255) NULL,
        chat_id BIGINT NULL,
        status ENUM('queued','running','done') NOT NULL DEFAULT 'queued',
        prompt MEDIUMTEXT NOT NULL,
        output MEDIUMTEXT NULL,
        task_status VARCHAR(255) NULL,
        commit_offered TINYINT NOT NULL DEFAULT 0,
        model VARCHAR(80) NULL,
        reply_mode VARCHAR(8) NULL,
        created DOUBLE NOT NULL,
        started DOUBLE NULL,
        finished DOUBLE NULL,
        KEY idx_status (status),
        KEY idx_created (created)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS kv (
        k VARCHAR(64) PRIMARY KEY,
        v MEDIUMTEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS pending (
        pid VARCHAR(64) PRIMARY KEY,
        chat_id BIGINT NOT NULL,
        text MEDIUMTEXT NOT NULL,
        project VARCHAR(255) NULL,
        message_id BIGINT NULL,
        created DOUBLE NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # мультиюзер: учётки веба (админ = WEB_ADMIN_USER, живёт в kv) и
    # владельцы проектов (папка общая, принадлежность — в базе)
    db_exec("""CREATE TABLE IF NOT EXISTS users (
        username VARCHAR(64) PRIMARY KEY,
        pw_hash VARCHAR(255) NOT NULL,
        is_admin TINYINT NOT NULL DEFAULT 0,
        created DOUBLE NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS project_owner (
        name VARCHAR(190) PRIMARY KEY,
        owner VARCHAR(64) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS project_acl (
        name VARCHAR(190) NOT NULL,
        user VARCHAR(64) NOT NULL,
        PRIMARY KEY (name, user)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # рабочие пространства: у каждого юзера свои; проект попадает в
    # пространство КОНКРЕТНОГО юзера (шаренный → дефолтное получателя)
    db_exec("""CREATE TABLE IF NOT EXISTS workspaces (
        id INT AUTO_INCREMENT PRIMARY KEY,
        owner VARCHAR(64) NOT NULL,
        name VARCHAR(64) NOT NULL,
        color VARCHAR(16) NOT NULL DEFAULT '#1565c0',
        is_default TINYINT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS project_ws (
        user VARCHAR(64) NOT NULL,
        name VARCHAR(190) NOT NULL,
        ws_id INT NOT NULL,
        PRIMARY KEY (user, name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    for col, ddl in (("model", "model VARCHAR(80) NULL"),
                     ("reply_mode", "reply_mode VARCHAR(8) NULL")):
        if not db_query("SELECT 1 FROM information_schema.COLUMNS"
                        " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='tasks'"
                        " AND COLUMN_NAME=%s", (MYSQL["database"], col)):
            db_exec(f"ALTER TABLE tasks ADD COLUMN {ddl}")
    # контейнер пересоздали посреди задачи — 'running' вернуть в очередь
    db_exec("UPDATE tasks SET status='queued' WHERE status='running'")
    log(f"mysql: connected to {MYSQL['host']}:{MYSQL['port']}/"
        f"{MYSQL['database']}, schema ready")


def _task_name(stem: str) -> str:
    return f"{stem}.txt"


def _insert_task(stem: str, prompt: str, source: str,
                 project: str | None, chat_id, created: float,
                 model: str | None = None,
                 reply_mode: str | None = None) -> None:
    db_exec("INSERT INTO tasks (stem, source, project, chat_id, prompt,"
            " model, reply_mode, created) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE prompt=VALUES(prompt)",
            (stem, source, project, chat_id, prompt, model, reply_mode,
             created))


def task_row(stem: str) -> dict | None:
    rows = db_query("SELECT * FROM tasks WHERE stem=%s", (stem,))
    return rows[0] if rows else None


def ingest_inbox_files() -> None:
    """Externally dropped *.txt files still work: import into the tasks
    table, then remove the file (queue itself lives in MySQL now)."""
    for f in sorted(INBOX.glob("*.txt"), key=lambda p: p.stat().st_mtime):
        try:
            stem = f.stem
            src = {"tg": "telegram", "web": "web"}.get(
                stem.split("-", 1)[0], "file")
            proj = current_project()[0] if multi_mode() else None
            _insert_task(stem, f.read_text(errors="replace"), src,
                         proj, None, f.stat().st_mtime)
            f.unlink()
            log(f"inbox file {f.name} imported into mysql")
        except Exception as e:
            log(f"inbox import of {f.name} failed: {e}")


def migrate_files_to_db() -> None:
    """One-time import of the old file-based state (guarded by a kv flag):
    inbox/done/outbox + task-projects, tg-chats, pending and the small
    *.txt settings. Old files are left on disk untouched."""
    if kv_get("files_migrated"):
        return
    kv_set("files_migrated", "1")
    try:
        chats = _load_json(TASKS_DIR / "tg-chats.json")
        projs = _load_json(TASKS_DIR / "task-projects.json")
        seen = set()
        for d, st in ((INBOX, "queued"), (DONE, "done")):
            for f in sorted(d.glob("*.txt"),
                            key=lambda p: p.stat().st_mtime):
                stem = f.stem
                seen.add(stem)
                src = {"tg": "telegram", "web": "web"}.get(
                    stem.split("-", 1)[0], "file")
                out = status = None
                if st == "done":
                    resp = OUTBOX / f"{stem}.response.txt"
                    if resp.exists():
                        raw = resp.read_text(errors="replace")
                        for line in raw[:400].splitlines():
                            if line.startswith("status:"):
                                status = line.split(":", 1)[1].strip()
                        out = (raw.split("=" * 60, 1)[1].strip()
                               if "=" * 60 in raw else raw)
                db_exec("INSERT INTO tasks (stem, source, project, chat_id,"
                        " status, prompt, output, task_status, created)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        " ON DUPLICATE KEY UPDATE stem=stem",
                        (stem, src, projs.get(stem), chats.get(stem), st,
                         f.read_text(errors="replace"), out, status,
                         f.stat().st_mtime))
        # .processing files were running when the container died — requeue
        for f in INBOX.glob("*.txt.processing"):
            db_exec("UPDATE tasks SET status='queued' WHERE stem=%s",
                    (f.name[:-len(".txt.processing")],))
        for pid, e in _load_json(TASKS_DIR / "tg-pending.json").items():
            db_exec("INSERT INTO pending (pid, chat_id, text, project,"
                    " message_id, created) VALUES (%s,%s,%s,%s,%s,%s)"
                    " ON DUPLICATE KEY UPDATE text=VALUES(text)",
                    (str(pid), e.get("chat_id") or 0, e.get("text") or "",
                     e.get("project"), e.get("message_id"),
                     float(e.get("id") or time.time())))
        for fname, key in (("model.txt", "model"),
                           ("project.txt", "project"),
                           ("session-mode.txt", "session_mode"),
                           ("reply-mode.txt", "reply_mode")):
            p = TASKS_DIR / fname
            if p.exists():
                kv_set(key, p.read_text().strip())
        p = TASKS_DIR / "devin-models.json"
        if p.exists():
            kv_set("models_cache", p.read_text())
        log(f"file state migrated into mysql ({len(seen)} tasks)")
    except Exception as e:
        kv_set("files_migrated", "")
        log(f"file->mysql migration failed (will retry): {e}")


def cleanup_legacy_files() -> None:
    """Удаляет старые файловые хвосты, если миграция в MySQL прошла:
    done/*.txt, outbox/*.txt и мелкие state-файлы (их содержимое уже в
    kv/tasks). inbox/ и .progress/ не трогаем — они живые."""
    if not kv_get("files_migrated") or not TASKS_DIR.is_dir():
        return
    n = 0
    for d in (TASKS_DIR / "done", TASKS_DIR / "outbox"):
        for f in d.glob("*.txt") if d.is_dir() else []:
            f.unlink(); n += 1
    for f in ("model.txt", "project.txt", "reply-mode.txt",
              "session-mode.txt", "task-projects.json", "tg-chats.json",
              "tg-commits.json", "tg-pending.json", "devin-models.json"):
        p = TASKS_DIR / f
        if p.exists():
            p.unlink(); n += 1
    if n:
        log(f"legacy task files cleaned: {n}")


def _tool_line(tc: dict) -> str:
    """One human-readable line for a transcript tool call."""
    fn = tc.get("function_name", "?")
    a = tc.get("arguments") or {}
    base = lambda p: Path(p or "").name or p
    if fn == "exec":
        return f"$ {(a.get('command') or '')[:80]}"
    if fn == "read":
        return f"читает {base(a.get('file_path'))}"
    if fn in ("edit", "write"):
        return f"правит {base(a.get('file_path'))}"
    if fn == "find_file_by_name":
        return f"ищет файлы: {a.get('pattern', '')}"
    if fn == "grep":
        return f"grep: {str(a.get('pattern', ''))[:40]}"
    if fn == "code_search":
        return f"поиск: {str(a.get('search_term', ''))[:60]}"
    if fn == "run_subagent":
        return f"субагент: {a.get('title', '')}"
    if fn in ("web_search", "webfetch"):
        return f"web: {str(a.get('query') or a.get('url') or '')[:60]}"
    if fn.startswith("mcp"):
        return f"mcp: {a.get('tool_name', fn)}"
    if fn == "todo_write":
        return "обновляет план"
    if fn == "skill":
        return f"skill: {a.get('skill', '')}"
    return fn


def _load_transcript_docs(path: Path) -> list:
    """Parse the devin --export file tolerantly: whole JSON, NDJSON lines,
    or concatenated JSON objects."""
    try:
        raw = path.read_text()
    except Exception:
        return []
    try:
        return [json.loads(raw)]
    except ValueError:
        pass
    docs = []
    for line in raw.splitlines():
        try:
            docs.append(json.loads(line))
        except ValueError:
            pass
    if docs:
        return docs
    dec, i, n = json.JSONDecoder(), 0, len(raw)
    while i < n:
        while i < n and raw[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        try:
            obj, j = dec.raw_decode(raw, i)
            docs.append(obj)
            i = j
        except ValueError:
            break
    return docs


def _digest_new_steps(path: Path, last_id: int) -> tuple:
    """Digest lines for transcript steps after last_id; (lines, new last_id)."""
    steps = []
    for d in _load_transcript_docs(path):
        if isinstance(d, dict):
            steps += d.get("steps") or ([d] if "step_id" in d else [])
    lines = []
    for s in steps:
        sid = s.get("step_id") or 0
        if sid <= last_id or s.get("source") != "agent":
            continue
        last_id = max(last_id, sid)
        lines += [_tool_line(tc) for tc in s.get("tool_calls") or []]
        msg = (s.get("message") or "").strip()
        if msg:
            lines.append("💬 " + msg[:150].replace("\n", " "))
    return [l for l in lines if l], last_id


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def progress_loop(chat_id, export_path: Path, out_path: Path,
                  proc: subprocess.Popen, since: float) -> None:
    """While the task runs, send live progress to telegram.

    Primary source: devin-task's stdout/stderr captured to out_path (tail).
    Bonus source: the --export file, or the live session transcript if the
    export only lands at session end — parsed into step digests.
    """
    last_id, last_sent, tick = 0, 0.0, 0
    offset, buf, seen_sizes = 0, [], {}
    transcripts = Path.home() / ".local/share/devin/cli/transcripts"
    live_transcript = None
    while proc.poll() is None:
        time.sleep(10)
        tick += 1
        try:
            if out_path.exists():
                with out_path.open(errors="replace") as f:
                    f.seek(offset)
                    chunk = ANSI.sub("", f.read()).strip()
                    offset = f.tell()
                if chunk:
                    buf.append(chunk)
        except Exception:
            pass
        src = export_path if export_path.exists() else None
        if src is None:
            if live_transcript is None:
                try:
                    cand = [f for f in transcripts.glob("*.json")
                            if f.stat().st_mtime >= since]
                    if cand:
                        live_transcript = max(
                            cand, key=lambda f: f.stat().st_mtime)
                        log(f"progress: no export, tailing transcript "
                            f"{live_transcript.name}")
                except Exception:
                    pass
            src = live_transcript
        if src is not None:
            try:
                sz = src.stat().st_size
                if sz != seen_sizes.get(src):
                    log(f"progress: {src.name} {sz} bytes")
                    seen_sizes[src] = sz
            except Exception:
                pass
            try:
                lines, last_id = _digest_new_steps(src, last_id)
                buf += lines
            except Exception:
                pass
        elif tick % 6 == 0:
            log("progress: no export file / live transcript yet")
        if buf and time.time() - last_sent >= 20:
            text = "\n".join(buf)
            buf.clear()
            tg_send(chat_id, "🛠 " + text[-3500:])
            last_sent = time.time()


def kill_task() -> None:
    """SIGKILL the whole process group of the running devin-task."""
    if not _task_proc:
        return
    try:
        os.killpg(_task_proc.pid, signal.SIGKILL)
        log(f"task process group {_task_proc.pid} killed")
    except Exception as e:
        log(f"killpg failed ({e}), falling back to kill()")
        _task_proc.kill()


def next_task() -> dict | None:
    ingest_inbox_files()
    rows = db_query("SELECT * FROM tasks WHERE status='queued'"
                    " ORDER BY created LIMIT 1")
    return rows[0] if rows else None


def run_task(task: dict) -> None:
    stem, name = task["stem"], _task_name(task["stem"])
    log(f"processing {name}")
    STATE["current_task"] = name
    db_exec("UPDATE tasks SET status='running', started=%s WHERE stem=%s",
            (time.time(), stem))

    started_ts = time.time()
    tproj = task.get("project")
    # владелец проекта = чьи креды/настройки идут в задачу
    task_user = _project_owner(tproj) if tproj else WEB_ADMIN_USER
    if tproj and PROJECTS_ROOT and (PROJECTS_ROOT / tproj).is_dir():
        workdir = PROJECTS_ROOT / tproj
    else:
        _, workdir = current_project()
    progress_dir = TASKS_DIR / ".progress"
    progress_dir.mkdir(exist_ok=True)
    export_path = progress_dir / f"{stem}.json"
    # devin-task reads the prompt from a file — keep that contract via a
    # transient file in .progress/
    task_file = progress_dir / f"{stem}.task.txt"
    task_file.write_text(task["prompt"], errors="replace")
    env = dict(os.environ, DEVIN_TASK_FILE=str(task_file),
               DEVIN_MODEL=task.get("model") or current_model(),
               DEVIN_WORKDIR=str(workdir),
               DEVIN_CONTINUE="true" if continue_mode() else "false",
               REPLY_MODE=task.get("reply_mode") or reply_mode(),
               DEVIN_EXPORT_FILE=str(export_path),
               GIT_AUTO_COMMIT=("true" if pj_get(tproj, "auto_commit")
                                        == "1" else "false"),
               WINDSURF_API_KEY=uset("devin.api_key", task_user,
                                     "WINDSURF_API_KEY"),
               GIT_USER_NAME=uset("git.name", task_user, "GIT_USER_NAME",
                                  "devin-bot"),
               GIT_USER_EMAIL=uset("git.email", task_user,
                                   "GIT_USER_EMAIL", ""))
    chat_id = task.get("chat_id")
    out_path = progress_dir / f"{stem}.out"
    global _task_proc
    try:
        # stdout+stderr go to a file the progress thread tails — devin -p
        # prints as it goes, so this gives live output for free.
        # start_new_session: own process group, so telegram /stop kills the
        # whole tree (devin-task -> devin -> its children), not just the shell
        out_f = open(out_path, "w", errors="replace")
        _task_proc = subprocess.Popen(
            [DEVIN_TASK], env=env,
            stdout=out_f, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
        if chat_id:
            threading.Thread(
                target=progress_loop, daemon=True,
                args=(chat_id, export_path, out_path,
                      _task_proc, started_ts)).start()
        try:
            _task_proc.wait(timeout=TASK_TIMEOUT)
            status = f"exit code: {_task_proc.returncode}"
        except subprocess.TimeoutExpired:
            kill_task()
            _task_proc.wait()
            status = f"TIMEOUT after {TASK_TIMEOUT}s"
        out_f.close()
        body = out_path.read_text(errors="replace") \
            if out_path.exists() else ""
    finally:
        _task_proc = None

    db_exec("UPDATE tasks SET status='done', output=%s, task_status=%s,"
            " finished=%s WHERE stem=%s", (body, status, time.time(), stem))
    STATE.update(current_task=None, last_task=name,
                 last_status=status, tasks_done=STATE["tasks_done"] + 1)
    log(f"done {name} ({status}), output -> mysql")
    offer_commit(task, chat_id, workdir)
    if TG_TOKEN:
        notify_chat(stem, f"{name}\n{status}\n\n{body[-3500:]}")
        if chat_id:
            send_task_stats(chat_id, started_ts)


def ensure_repo() -> None:
    """Clone GIT_REPO_URL into the workspace if it is not a git repo yet.

    devin-task does the same check before every task, but doing it here too
    means auth/URL problems surface at container start, not on the first task.
    """
    if multi_mode():
        log(f"multi-project mode: {len(list_projects())} project(s) "
            f"in {PROJECTS_ROOT}, current: {project_label()}")
        return
    workdir = Path(os.environ.get("DEVIN_WORKDIR", "/workspace"))
    if (workdir / ".git").exists():
        return
    url = os.environ.get("GIT_REPO_URL")
    if not url:
        log(f"{workdir} is empty and GIT_REPO_URL is not set — "
            "tasks will fail until a repo is mounted or cloned")
        return
    log(f"cloning {url} -> {workdir}")
    args = ["git", "clone"]
    if branch := os.environ.get("GIT_BRANCH"):
        args += ["--branch", branch]
    args += [url, str(workdir)]
    # git bypasses the proxy — strip *_proxy so the clone goes direct
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
    res = subprocess.run(args, env=env)
    if res.returncode != 0:
        log(f"clone failed (exit {res.returncode}) — check GIT_REPO_URL and git credentials; "
            "devin-task will retry before each task")
    else:
        log("clone finished")


# --- telegram / gemini -------------------------------------------------------

def tg_api(method: str, **params) -> dict:
    shown = {k: ("***" if k == "secret_token" else str(v)[:120])
             for k, v in params.items()}
    log(f"tg -> {method} {shown}")
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with TG_OPENER.open(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} HTTP {e.code}: {e.read().decode()[:300]}")
    log(f"tg <- {method}: {json.dumps(res)[:200]}")
    if not res.get("ok"):
        raise RuntimeError(f"{method} api error: {res}")
    return res


def tg_send(chat_id: int, text: str) -> None:
    """sendMessage, splitting into <=4000-char chunks, max 5 messages."""
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)][:5]
    if len(text) > 20000:
        chunks[-1] += "\n…[truncated]"
    log(f"reply to chat {chat_id}: {len(chunks)} message(s), {len(text)} chars")
    for chunk in chunks:
        try:
            tg_api("sendMessage", chat_id=chat_id, text=chunk)
        except Exception as e:
            log(f"telegram sendMessage error: {e}")


def tg_download(file_id: str) -> bytes:
    file_path = tg_api("getFile", file_id=file_id)["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{TG_TOKEN}/{file_path}"
    log(f"downloading voice file {file_path}")
    with TG_OPENER.open(url, timeout=60) as r:
        data = r.read()
    log(f"voice file: {len(data)} bytes")
    return data


def gemini_transcribe(audio: bytes, mime: str = "audio/ogg",
                      user: str | None = None) -> str:
    gm = uset("gemini.model", user, "GEMINI_MODEL", "gemini-2.5-flash")
    gk = uset("gemini.api_key", user, "GEMINI_API_KEY")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{gm}:generateContent?key={gk}")
    payload = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
        {"text": "Transcribe this voice message. Reply with only the "
                 "transcription, in its original language."},
    ]}]}
    log(f"gemini -> transcribing {len(audio)} bytes with {gm}")
    started = time.time()
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with TG_OPENER.open(req, timeout=120) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"gemini HTTP {e.code}: {e.read().decode()[:500]}")


def openai_transcribe(audio: bytes, mime: str = "audio/ogg", user: str | None = None) -> str:
    """OpenAI-compatible /audio/transcriptions (OpenAI, Groq, …)."""
    boundary = "----devincli" + str(int(time.time() * 1000))
    ext = {"audio/ogg": "oga", "audio/mpeg": "mp3", "audio/mp4": "m4a",
           "audio/wav": "wav"}.get(mime, "ogg")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="model"\r\n\r\n{uset("stt.model", user, "STT_MODEL", "whisper-1")}\r\n'.encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="file"; filename="voice.{ext}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode() + audio + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    sb = uset("stt.base_url", user, "STT_BASE_URL",
              "https://api.openai.com/v1")
    sk = uset("stt.api_key", user, "STT_API_KEY")
    sm = uset("stt.model", user, "STT_MODEL", "whisper-1")
    log(f"stt -> transcribing {len(audio)} bytes via {sb} ({sm})")
    started = time.time()
    req = urllib.request.Request(
        f"{sb}/audio/transcriptions",
        data=b"".join(parts),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {sk}",
        })
    try:
        with TG_OPENER.open(req, timeout=120) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"stt HTTP {e.code}: {e.read().decode()[:500]}")
    text = res["text"].strip()
    log(f"stt <- {time.time() - started:.1f}s: {text!r}")
    return text


YANDEX_STT_HOST = os.environ.get("YANDEX_STT_URL",
                                 "https://stt.api.cloud.yandex.net")


def _yandex_request(path: str, body: dict | None = None, user: str | None = None) -> str:
    headers = {"Authorization": "Api-Key " + uset("stt.api_key", user,
                                                  "STT_API_KEY"),
               "Content-Type": "application/json"}
    if (fid := uset("yandex.folder_id", user, "YANDEX_FOLDER_ID")):
        headers["x-folder-id"] = fid
    req = urllib.request.Request(
        YANDEX_STT_HOST + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with DIRECT_OPENER.open(req, timeout=120) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"yandex {path} HTTP {e.code}: {e.read().decode()[:500]}")


def _extract_texts(obj, finals: list, refined: list) -> None:
    """Recursively find {final|finalRefinement}.alternatives[].text in any
    nesting — getRecognition may wrap chunks in result/response or a list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("final", "finalRefinement") and isinstance(v, dict):
                tgt = refined if k == "finalRefinement" else finals
                for alt in v.get("alternatives") or []:
                    t = (alt.get("text") or "").strip()
                    if t:
                        tgt.append(t)
            else:
                _extract_texts(v, finals, refined)
    elif isinstance(obj, list):
        for v in obj:
            _extract_texts(v, finals, refined)


def _collect_recognition_text(raw: str) -> str:
    """Join final alternatives from a getRecognition response — it may be
    a single JSON object, a {result: ...} wrapper, or NDJSON chunks."""
    blobs = []
    try:
        blobs.append(json.loads(raw))
    except ValueError:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                blobs.append(json.loads(line))
            except ValueError:
                pass
    finals, refined = [], []
    for blob in blobs:
        _extract_texts(blob, finals, refined)
    # finalRefinement replaces the plain final — don't concatenate both
    return " ".join(refined or finals).strip()


def yandex_transcribe_sync(audio: bytes, mime: str = "audio/ogg", user: str | None = None,
                           rate: int = 48000) -> str:
    """SpeechKit v1 sync recognition — fast path for short clips (≤~30s).
    mime audio/wav / raw PCM -> format=lpcm (browser mic path)."""
    started = time.time()
    fmt = "lpcm" if mime in ("audio/wav", "audio/x-wav", "audio/L16",
                             "application/octet-stream") else "oggopus"
    qs = "?lang=" + uset("yandex.lang", user, "YANDEX_LANG", "ru-RU") \
        + f"&format={fmt}&sampleRateHertz={rate}"
    if (fid := uset("yandex.folder_id", user, "YANDEX_FOLDER_ID")):
        qs += f"&folderId={fid}"
    req = urllib.request.Request(
        YANDEX_STT_HOST + "/speech/v1/stt:recognize" + qs,
        data=audio,
        headers={"Authorization": f"Api-Key {STT_API_KEY}"},
        method="POST")
    log(f"stt -> yandex v1 sync, {len(audio)} bytes")
    try:
        with DIRECT_OPENER.open(req, timeout=60) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"yandex stt:recognize HTTP {e.code}: {e.read().decode()[:500]}")
    if res.get("error_code"):
        raise RuntimeError(f"yandex stt: {res.get('error_message')}")
    text = (res.get("result") or "").strip()
    log(f"stt <- {time.time() - started:.1f}s (sync): {text!r}")
    return text


def yandex_transcribe(audio: bytes, mime: str = "audio/ogg",
                      on_status=None) -> str:
    """SpeechKit v3 async recognition — audio goes as base64 `content`,
    no Object Storage needed. Polls getRecognition every 10s (≤10 min),
    reporting progress through on_status()."""
    started = time.time()
    body = {
        "content": base64.b64encode(audio).decode(),
        "recognitionModel": {
            "model": "general",
            "audioFormat": {"containerAudio": {"containerAudioType": (
                "WAV" if mime in ("audio/wav", "audio/x-wav", "audio/L16",
                                  "application/octet-stream")
                else "OGG_OPUS")}},
            "textNormalization": {"textNormalization":
                                  "TEXT_NORMALIZATION_ENABLED",
                                  "literatureText": True},
            "languageRestriction": {"restrictionType": "WHITELIST",
                                    "languageCode": [uset("yandex.lang", user, "YANDEX_LANG", "ru-RU")]},
        },
    }
    log(f"stt -> yandex speechkit v3 async, {len(audio)} bytes")
    op = json.loads(_yandex_request("/stt/v3/recognizeFileAsync", body))
    op_id = op.get("id") or op.get("operationId")
    if not op_id:
        raise RuntimeError(f"yandex stt: no operation id in {op}")
    log(f"stt operation {op_id}, polling every 10s")
    if on_status:
        on_status(f"🔎 Отправлено на распознавание (операция {op_id[:12]}…), "
                  "проверяю каждые 10с")

    for attempt in range(1, 61):
        time.sleep(10)
        try:
            raw = _yandex_request(
                f"/stt/v3/getRecognition?operationId={op_id}")
        except Exception as e:
            log(f"stt poll {attempt}: {e}")
            raw = ""
        text = _collect_recognition_text(raw)
        if text:
            log(f"stt <- {time.time() - started:.1f}s, "
                f"{attempt} polls: {text!r}")
            return text
        log(f"stt poll {attempt}: not ready yet, raw[:200]={raw[:200]!r}")
        if on_status:
            on_status(f"⏳ Пока не готово — проверяю ещё раз через 10с "
                      f"({attempt}/60)")
    raise RuntimeError("yandex stt: recognition did not finish in 10 min")


def _stt_chain(user: str | None = None) -> list[str]:
    """STT providers to try, in order — stt.provider (env STT_PROVIDER)
    может быть цепочкой 'gemini,openai': при падении первого следующий
    всё равно транскрибирует. Пусто → openai-совместимый дефолт."""
    p = uset("stt.provider", user, "STT_PROVIDER") or "openai"
    return [x.strip() for x in p.split(",") if x.strip()] or ["openai"]


def _stt_ready(p: str, user: str | None = None) -> bool:
    """У провайдера есть ключ: openai/yandex делят stt.api_key, у gemini
    свой gemini.api_key — всё из настроек юзера с env-фолбэком."""
    if p == "gemini":
        return bool(uset("gemini.api_key", user, "GEMINI_API_KEY"))
    return bool(uset("stt.api_key", user, "STT_API_KEY"))


def _stt_run(chain: list[str], try_fn, on_status=None) -> str:
    """First success wins; failures are logged and tried against the next
    provider. The combined error of all providers is raised at the end."""
    errs = []
    for i, p in enumerate(chain):
        try:
            return try_fn(p)
        except Exception as e:
            errs.append(f"{p}: {e}")
            log(f"stt provider {p} failed: {e}")
            if on_status and i < len(chain) - 1:
                try:
                    on_status("⚠️ Провайдер не ответил — "
                              "пробую запасной…")
                except Exception:
                    pass
    raise RuntimeError("STT провайдеры упали: " + " | ".join(errs))


def _stt_dispatch(p: str, audio: bytes, mime: str, on_status=None,
                  duration=None, rate: int = 48000, user=None) -> str:
    if p == "yandex":
        if duration is not None and duration < 28:
            return yandex_transcribe_sync(audio, mime, rate, user)
        return yandex_transcribe(audio, mime, on_status, user)
    if p == "gemini":
        return gemini_transcribe(audio, mime, user)
    return openai_transcribe(audio, mime, user)


def transcribe(audio: bytes, mime: str = "audio/ogg", on_status=None,
               duration=None, user=None) -> str:
    return _stt_run(
        _stt_chain(user),
        lambda p: _stt_dispatch(p, audio, mime, on_status, duration,
                                user=user),
        on_status)


def _wav_rate(wav: bytes) -> int:
    if wav[:4] == b"RIFF" and len(wav) > 28:
        return int.from_bytes(wav[24:28], "little")
    return 16000


def _pcm_resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-resample mono PCM16 LE — Yandex accepts only 8/16/48 kHz."""
    if src_rate == dst_rate:
        return pcm
    src = array.array("h")
    src.frombytes(pcm[:len(pcm) // 2 * 2])
    n = len(src)
    dst = array.array("h", bytes(max(1, round(n * dst_rate / src_rate)) * 2))
    ratio = src_rate / dst_rate
    for i in range(len(dst)):
        p = i * ratio
        i0 = int(p)
        i1 = min(i0 + 1, n - 1)
        dst[i] = int(src[i0] + (src[i1] - src[i0]) * (p - i0))
    return dst.tobytes()


def _wav_wrap(pcm: bytes, rate: int) -> bytes:
    """Canonical 44-byte RIFF header + PCM16 mono — WAV container for the
    v3 async API."""
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
            b"data" + struct.pack("<I", len(pcm)) + pcm)


def web_transcribe(wav: bytes) -> str:
    """Browser mic → WAV → STT. Yandex: <28s LPCM sync, longer clips go
    through the v3 async path with progress in STATE["stt"]; gemini/openai
    take the WAV file as-is."""
    def _status(msg: str) -> None:
        STATE["stt"] = msg
        log(f"web stt: {msg}")

    u = _current_user()
    chain = _stt_chain(u)
    if not any(_stt_ready(p, u) for p in chain):
        raise RuntimeError("STT не настроен: нет ключей провайдеров "
                           "(GEMINI_API_KEY / STT_API_KEY)")
    rate = _wav_rate(wav)
    pcm = wav[44:] if wav[:4] == b"RIFF" else wav
    if rate not in (8000, 16000, 48000):   # safety net for odd clients
        pcm, rate = _pcm_resample(pcm, rate, 16000), 16000
    duration = len(pcm) / 2 / rate

    def _try(p: str) -> str:
        if p != "yandex":
            return _stt_dispatch(p, wav, "audio/wav")
        try:
            if duration < 28:
                return yandex_transcribe_sync(pcm, "audio/L16", rate)
            _status(f"Запись {duration:.0f}с — длинная, ушла в асинхронное "
                    "распознавание Яндекса")
            return yandex_transcribe(_wav_wrap(pcm, rate), "audio/wav",
                                     on_status=_status)
        finally:
            STATE["stt"] = None

    return _stt_run(chain, _try, _status)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def enqueue_task(text: str, chat_id: int | None = None,
                 project: str | None = None, prefix: str = "tg") -> str:
    stem = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}" \
           f"-{(int(time.time() * 1000) % 100000):05d}"
    source = {"tg": "telegram", "web": "web"}.get(prefix, prefix)
    scope = source if source in ("web", "telegram") else ""
    proj = project or (current_project(scope)[0] if multi_mode() else None)
    model = pj_get(proj, "model") if proj else ""
    model = model or current_model(scope)
    rmode = pj_get(proj, "reply_mode") if proj else ""
    rmode = rmode or reply_mode(scope)
    _insert_task(stem, text, source, proj, chat_id, time.time(), model,
                 rmode)
    log(f"task {_task_name(stem)} queued in mysql, chat_id={chat_id}, "
        f"project={proj}, model={model}, mode={rmode}")
    return _task_name(stem)


def _save_pending(entry: dict) -> str:
    pid = str(entry.get("id") or int(time.time() * 1000))
    db_exec("INSERT INTO pending (pid, chat_id, text, project, message_id,"
            " created) VALUES (%s,%s,%s,%s,%s,%s)"
            " ON DUPLICATE KEY UPDATE text=VALUES(text),"
            " message_id=VALUES(message_id)",
            (pid, entry.get("chat_id") or 0, entry.get("text") or "",
             entry.get("project"), entry.get("message_id"), time.time()))
    return pid


def _pop_pending(pid: str) -> dict | None:
    rows = db_query("SELECT * FROM pending WHERE pid=%s", (str(pid),))
    if not rows:
        return None
    db_exec("DELETE FROM pending WHERE pid=%s", (str(pid),))
    return dict(rows[0], id=pid)


def _pending_for_chat(chat_id) -> tuple:
    """Newest open pending entry for this chat, or (None, None)."""
    rows = db_query("SELECT * FROM pending WHERE chat_id=%s"
                    " ORDER BY created DESC LIMIT 1", (chat_id,))
    if not rows:
        return None, None
    return rows[0]["pid"], dict(rows[0], id=rows[0]["pid"])


def _update_pending(pid: str, entry: dict) -> None:
    db_exec("UPDATE pending SET text=%s, project=%s, message_id=%s"
            " WHERE pid=%s",
            (entry.get("text") or "", entry.get("project"),
             entry.get("message_id"), str(pid)))


def _pending_text(entry: dict) -> str:
    proj = entry.get("project")
    head = f"Проект: {proj}\n\n" if proj else ""
    return f"{head}Распознано:\n{entry['text']}"


def _add_to_pending(chat_id, pid: str, entry: dict, extra: str) -> None:
    """Append extra text to an open pending task and refresh its message."""
    entry["text"] = f"{entry['text']}\n{extra}".strip()
    _update_pending(pid, entry)
    try:
        tg_api("editMessageText", chat_id=chat_id,
               message_id=entry.get("message_id"),
               text=_pending_text(entry),
               reply_markup=_confirm_keyboard(pid))
    except Exception as e:
        log(f"editMessageText failed ({e}), sending a new confirm message")
        res = tg_api("sendMessage", chat_id=chat_id,
                     text=_pending_text(entry),
                     reply_markup=_confirm_keyboard(pid))
        entry["message_id"] = res["result"]["message_id"]
        _update_pending(pid, entry)
    log(f"pending {pid} appended ({len(entry['text'])} chars total)")


def _confirm_keyboard(pid: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Принять", "callback_data": f"ok:{pid}"},
        {"text": "❌ Отмена", "callback_data": f"no:{pid}"},
    ]]}


def list_projects() -> list:
    """Direct subdirectories of PROJECTS_ROOT — non-recursive, auto-scanned."""
    if not PROJECTS_ROOT or not PROJECTS_ROOT.is_dir():
        return []
    return sorted(d.name for d in PROJECTS_ROOT.iterdir()
                  if d.is_dir() and not d.name.startswith("."))


def multi_mode() -> bool:
    """Multi-project mode is on while the projects dir has subfolders."""
    return bool(list_projects())


def current_project(scope: str = "telegram") -> tuple:
    """(project name or None, workdir Path). Single mode: (None, WORKDIR).

    Скоупы раздельные: у телеграма свой последний выбранный проект
    (kv.project), у веба — свой (kv.project_web, fallback на телеграмовский).
    """
    if not multi_mode():
        return None, WORKDIR
    name = kv_get("project_web" if scope == "web" else "project")
    if not name and scope == "web":
        name = kv_get("project")
    if name and (PROJECTS_ROOT / name).is_dir():
        return name, PROJECTS_ROOT / name
    return None, PROJECTS_ROOT


def set_project(name: str, scope: str = "telegram") -> None:
    kv_set("project_web" if scope == "web" else "project", name)
    log(f"project switched to {name} (scope {scope})")


def project_label() -> str:
    return current_project()[0] or "не выбран"


def send_projects(chat_id, msg_id=None) -> None:
    projects = list_projects()
    cur = current_project()[0]
    if not projects:
        tg_send(chat_id, "Проектов нет — положи папки с репозиториями "
                f"в {PROJECTS_ROOT} (multi-project mode выключен, "
                "работаю с /workspace).")
        return
    kb = [[{"text": ("✅ " if p == cur else "") + p,
            "callback_data": f"proj:{p}"}] for p in projects[:15]]
    text = f"Текущий проект: {project_label()}\nВыбери проект:"
    if msg_id:
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=text, reply_markup={"inline_keyboard": kb})
    else:
        tg_api("sendMessage", chat_id=chat_id, text=text,
               reply_markup={"inline_keyboard": kb})


def continue_mode() -> bool:
    """Session mode for the next task: UI/telegram override wins over env."""
    m = kv_get("session_mode")
    if m in ("continue", "new"):
        return m == "continue"
    return os.environ.get("DEVIN_CONTINUE", "").lower() == "true"


def set_session_mode(mode: str) -> None:
    kv_set("session_mode", mode)
    log(f"session mode -> {mode}")


def send_session_menu(chat_id, msg_id=None) -> None:
    cont = continue_mode()
    kb = [[{"text": ("✅ " if cont else "") + "🔁 Продолжать сессию проекта",
            "callback_data": "sess:continue"}],
          [{"text": ("✅ " if not cont else "") + "🆕 Каждая задача — новая",
            "callback_data": "sess:new"}]]
    text = ("Режим сессий: каждый проект хранит свои сессии — "
            "'продолжать' резюмит последнюю сессию выбранного проекта.")
    if msg_id:
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=text, reply_markup={"inline_keyboard": kb})
    else:
        tg_api("sendMessage", chat_id=chat_id, text=text,
               reply_markup={"inline_keyboard": kb})


def reply_mode(scope: str = "telegram") -> str:
    """'ask' = answer questions about the repo, no edits; 'code' = do tasks.
    Web-скоуп — настройка юзера (us:<uid>.reply_mode); telegram — админ."""
    if scope == "web":
        m = us_get(_current_user(), "reply_mode")
        if m in ("ask", "code"):
            return m
    if scope:
        m = kv_get(f"reply_mode_{scope}")
        if m in ("ask", "code"):
            return m
    m = kv_get("reply_mode")
    if m in ("ask", "code"):
        return m
    return os.environ.get("REPLY_MODE", "code")


def set_reply_mode(mode: str, scope: str = "telegram") -> None:
    if scope == "web":
        us_set(_current_user(), "reply_mode", mode)
    else:
        kv_set(f"reply_mode_{scope}", mode)
    log(f"reply mode -> {mode} (scope {scope})")


def send_mode_menu(chat_id, msg_id=None) -> None:
    cur = reply_mode()
    kb = [[{"text": ("✅ " if cur == "code" else "") + "🛠 Написание кода",
            "callback_data": "mode:code"}],
          [{"text": ("✅ " if cur == "ask" else "") + "💬 Ответ на вопрос",
            "callback_data": "mode:ask"}]]
    text = ("Режим ответа: «код» — выполняет задачу и меняет репо; "
            "«вопрос» — читает код и отвечает, ничего не трогая.")
    if msg_id:
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=text, reply_markup={"inline_keyboard": kb})
    else:
        tg_api("sendMessage", chat_id=chat_id, text=text,
               reply_markup={"inline_keyboard": kb})


def current_model(scope: str = "telegram") -> str:
    """Default model for a scope ('web'|'telegram'): scoped kv wins,
    then the legacy global override, then DEVIN_MODEL env."""
    if scope == "web":
        m = us_get(_current_user(), "model")
        if m:
            return m
    if scope:
        m = kv_get(f"model_{scope}")
        if m:
            return m
    return kv_get("model") or os.environ.get("DEVIN_MODEL", "swe")


def set_model(name: str, scope: str = "telegram") -> None:
    if scope == "web":
        us_set(_current_user(), "model", name.strip())
    else:
        kv_set(f"model_{scope}", name.strip())
    log(f"model switched to {name} (scope {scope})")


def _models_from_json(data) -> list:
    """Normalize `devin models list --format json` to [{id, description}].

    The exact schema isn't documented: families may nest runnable models
    under "models"/"variants" and short names under "aliases". A family
    name itself isn't a runnable model id, so it's never offered."""
    out = []

    def add(mid, desc="", info=None, fam=""):
        if isinstance(mid, str) \
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", mid) \
                and all(m["id"] != mid for m in out):
            out.append({"id": mid,
                        "description": desc if isinstance(desc, str) else "",
                        "family": fam,
                        "info": info or {}})

    def walk(x, desc="", fam=""):
        if isinstance(x, dict):
            d = x.get("description") or x.get("display_name") \
                or x.get("label") or desc
            kids = next((x[k] for k in ("models", "variants", "items",
                                        "children")
                         if isinstance(x.get(k), list)), None)
            mid = next((x[k] for k in ("model_uid", "id", "slug", "model")
                        if isinstance(x.get(k), str)), None)
            if mid is None and kids is None:
                v = x.get("name")
                if isinstance(v, str):
                    mid = v  # leaf dict — name is the model id
            if mid and kids is None:
                # всё, что devin отдал по модели — цены, токены, лимиты;
                # из info режем только вложенные дети-моделей
                info = {k: v for k, v in x.items()
                        if k not in ("models", "variants", "items",
                                     "children")}
                add(mid, d, info, fam)
            # имя группы — family_label/label семейства, не runnable id
            fam = (x.get("family_label") or x.get("label") or
                   x.get("name") if kids else None) or fam or \
                  (x.get("name") if isinstance(x.get("name"), str) else "")
            for v in kids or []:
                walk(v, d, fam)
            for a in x.get("aliases") or []:
                if isinstance(a, str):
                    add(a, f"алиас {fam}".strip(), fam=fam)
                else:
                    walk(a, d, fam)
            if mid is None and kids is None:
                for v in x.values():
                    if isinstance(v, (dict, list)):
                        walk(v, d, fam)
        elif isinstance(x, list):
            for v in x:
                walk(v, desc, fam)
        elif isinstance(x, str):
            add(x, desc, fam=fam)

    walk(data)
    return out


def devin_models() -> list:
    """[{id, description}] via `devin models list --format json`.
    Successful results are cached to disk — the catalog survives restarts
    and is still served while the proxy warms up."""
    try:
        res = subprocess.run(
            ["devin", "models", "list", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        models = _models_from_json(json.loads(res.stdout))
    except Exception as e:
        log(f"devin models list failed: {e}")
        return []
    if models:
        try:
            kv_set("models_cache", json.dumps(models, ensure_ascii=False))
        except Exception:
            pass
    return models


_models_cache: list | None = None
_models_last_try = 0.0


def get_models() -> list:
    """Cached model catalog for the web UI; empty cache kicks off a
    background `devin models list` refresh at most once a minute."""
    global _models_cache, _models_last_try
    if _models_cache is None:
        try:
            _models_cache = json.loads(kv_get("models_cache") or "[]")
        except Exception:
            _models_cache = []
    if not _models_cache and time.time() - _models_last_try > 60:
        _models_last_try = time.time()
        threading.Thread(target=refresh_models, daemon=True).start()
    return _models_cache


def refresh_models() -> None:
    global _models_cache
    got = devin_models()
    if got:
        _models_cache = got


def status_text() -> str:
    uptime = int(time.time() - _started_at)
    h, m = uptime // 3600, uptime % 3600 // 60
    queue = db_query(
        "SELECT COUNT(*) AS n FROM tasks WHERE status='queued'")[0]["n"]
    day, nday, week, nweek = usage_totals()
    sess = "continue" if continue_mode() else "new"
    return ("📊 Статус воркера\n"
            f"▫️ uptime: {h}ч {m}м\n"
            f"▫️ проект: {project_label()}  ·  модель: {current_model()}\n"
            f"▫️ сессии: {sess}  ·  режим: {reply_mode()}\n"
            f"▫️ очередь: {queue} задач  ·  выполняется: "
            f"{STATE['current_task'] or '—'}\n"
            f"▫️ последняя: {STATE['last_task']} ({STATE['last_status']})\n"
            f"▫️ выполнено задач: {STATE['tasks_done']}\n"
            f"▫️ токены — 24ч: {day} ({nday} задач), "
            f"7д: {week} ({nweek} задач)\n"
            f"▫️ репо: {_git_head()}")


def send_models(chat_id, msg_id=None) -> None:
    models = devin_models()
    cur = current_model()
    if not models:
        tg_send(chat_id,
                f"Текущая модель: {cur}\nСписок недоступен — "
                "`devin models list` не ответил. Задай явно: /model <name>")
        return
    kb = [[{"text": ("✅ " if m["id"] == cur else "") + m["id"],
            "callback_data": f"model:{m['id']}"}] for m in models[:15]]
    text = f"Текущая модель: {cur}\nВыбери модель:"
    if msg_id:
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=text, reply_markup={"inline_keyboard": kb})
    else:
        tg_api("sendMessage", chat_id=chat_id, text=text,
               reply_markup={"inline_keyboard": kb})


def session_stats(since: float) -> dict | None:
    """Metrics of the devin session finished after `since`, from its transcript."""
    td = Path.home() / ".local/share/devin/cli/transcripts"
    try:
        files = [f for f in td.glob("*.json") if f.stat().st_mtime >= since]
        if not files:
            return None
        d = json.loads(max(files, key=lambda f: f.stat().st_mtime).read_text())
    except Exception as e:
        log(f"session stats read failed: {e}")
        return None
    fm = d.get("final_metrics") or {}
    return {
        "session": d.get("session_id"),
        "model": (d.get("agent") or {}).get("model_name"),
        "prompt_tokens": fm.get("total_prompt_tokens"),
        "completion_tokens": fm.get("total_completion_tokens"),
        "cached_tokens": fm.get("total_cached_tokens"),
        "steps": fm.get("total_steps"),
    }


def usage_totals() -> tuple:
    """Cumulative tokens across all sessions: (24h tokens, 24h tasks,
    7d tokens, 7d tasks). CLI exposes no credit/money balance — only
    token metrics in transcripts."""
    td = Path.home() / ".local/share/devin/cli/transcripts"
    day = week = nday = nweek = 0
    try:
        files = list(td.glob("*.json"))
    except Exception:
        files = []
    now = time.time()
    for f in files:
        try:
            age = now - f.stat().st_mtime
            fm = (json.loads(f.read_text()).get("final_metrics") or {})
            toks = (fm.get("total_prompt_tokens") or 0) + \
                   (fm.get("total_completion_tokens") or 0)
        except Exception:
            continue
        if age <= 86400:
            day += toks
            nday += 1
        if age <= 7 * 86400:
            week += toks
            nweek += 1
    return day, nday, week, nweek


def send_task_stats(chat_id, since: float) -> None:
    s = session_stats(since) or {}
    day, nday, week, nweek = usage_totals()
    lines = [
        f"model: {s.get('model') or current_model()}",
        f"tokens: prompt={s.get('prompt_tokens', '?')} "
        f"(cached={s.get('cached_tokens', '?')}), "
        f"completion={s.get('completion_tokens', '?')}",
        f"steps: {s.get('steps', '?')}, session: {s.get('session') or '-'}",
        f"за 24ч: {day} токенов ({nday} задач), "
        f"за 7д: {week} токенов ({nweek} задач)",
    ]
    tg_send(chat_id, "📊 Статистика задачи:\n" + "\n".join(lines))


def _git(workdir, *args) -> tuple:
    """git in workdir, direct connection (proxy vars stripped)."""
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
    res = subprocess.run(["git", "-C", str(workdir), *args],
                         capture_output=True, text=True, timeout=120, env=env)
    return res.returncode, (res.stdout + res.stderr).strip()


def offer_commit(task: dict, chat_id, workdir) -> None:
    """After a task: flag commit_offered (web buttons) + tg buttons if chat."""
    try:
        _, st = _git(workdir, "status", "--porcelain")
        dirty = len(st.splitlines()) if st else 0
        rc, up = _git(workdir, "log", "@{u}..HEAD", "--oneline")
        unpushed = len(up.splitlines()) if rc == 0 and up else 0
    except Exception as e:
        log(f"git state check failed: {e}")
        return
    if not dirty and not unpushed:
        return
    stem = task["stem"]
    db_exec("UPDATE tasks SET commit_offered=1 WHERE stem=%s", (stem,))
    log(f"commit offer for {stem}: dirty={dirty} unpushed={unpushed}")
    if not chat_id or not TG_TOKEN:
        return
    if dirty:
        label = f"✅ Закоммитить и запушить ({dirty} файл(ов))"
    else:
        label = f"⬆ Запушить {unpushed} коммит(ов)"
    tg_api("sendMessage", chat_id=chat_id,
           text=f"В репо: {dirty} незакоммиченных, {unpushed} незапушенных. Что делаем?",
           reply_markup={"inline_keyboard": [
               [{"text": label, "callback_data": f"commit:{stem}"}],
               [{"text": "⏭ Пропустить", "callback_data": f"skip:{stem}"}],
           ]})


def do_commit(stem: str, workdir) -> str:
    """git add -A && commit && push; or push only when the tree is clean."""
    _, st = _git(workdir, "status", "--porcelain")
    out = []
    if st:
        msg = f"task: {stem}"
        row = task_row(stem)
        if row and row["prompt"]:
            first = row["prompt"].strip().splitlines()[0]
            msg = f"task: {first[:70]}"
        for args in (("add", "-A"), ("commit", "-m", msg)):
            rc, o = _git(workdir, *args)
            out.append(o)
            if rc != 0:
                return "\n".join(out)
    rc, o = _git(workdir, "push")
    out.append(o)
    return "\n".join(out) or "nothing to do"


def handle_command(chat_id, text: str) -> None:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().lstrip("/").split("@")[0]  # strip /cmd@botname
    if cmd in ("menu", "start", "help"):
        tg_api("sendMessage", chat_id=chat_id, text="Меню:",
               reply_markup={"inline_keyboard": [[
                   {"text": "📁 Проект", "callback_data": "cmd:projects"},
                   {"text": "🧠 Модели", "callback_data": "cmd:models"},
                   {"text": "🔁 Сессия", "callback_data": "cmd:session"},
                   {"text": "💬 Режим", "callback_data": "cmd:mode"},
                   {"text": "📊 Статус", "callback_data": "cmd:status"},
                   {"text": "⛔ Стоп", "callback_data": "cmd:stop"},
               ]]})
    elif cmd == "models":
        send_models(chat_id)
    elif cmd in ("projects", "project"):
        if arg.strip() and arg.strip() in list_projects():
            set_project(arg.strip())
            tg_send(chat_id, f"Проект: {arg.strip()}")
        else:
            send_projects(chat_id)
    elif cmd == "model":
        if arg.strip():
            set_model(arg.strip())
            tg_send(chat_id, f"Модель: {arg.strip()}")
        else:
            send_models(chat_id)
    elif cmd == "session":
        if arg.strip() in ("new", "continue"):
            set_session_mode(arg.strip())
            tg_send(chat_id, f"Режим сессий: {arg.strip()}")
        else:
            send_session_menu(chat_id)
    elif cmd == "stop":
        if _task_proc and STATE["current_task"]:
            kill_task()
            tg_send(chat_id,
                    f"⛔ Задача {STATE['current_task']} остановлена — "
                    "воркер возьмёт следующую из очереди.")
        else:
            tg_send(chat_id, "Сейчас ничего не выполняется.")
    elif cmd == "status":
        tg_send(chat_id, status_text())
    else:
        tg_send(chat_id,
                "Команды: /menu, /models, /model <name>, /status.\n"
                "Или пришли задачу текстом/голосовым.")


def handle_callback(cb: dict) -> None:
    cb_id = cb["id"]
    data = cb.get("data", "")
    action, _, pid = data.partition(":")
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    msg_id = msg.get("message_id")
    log(f"callback {data!r} from chat {chat_id}")

    if action == "model":
        set_model(pid)
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"Модель переключена на {pid}.",
               reply_markup={"inline_keyboard": []})
        tg_api("answerCallbackQuery", callback_query_id=cb_id,
               text=f"Модель: {pid}")
        return
    if data == "cmd:models":
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        send_models(chat_id, msg_id)
        return
    if data == "cmd:status":
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        tg_send(chat_id, status_text())
        return
    if data == "cmd:projects":
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        send_projects(chat_id, msg_id)
        return
    if data == "cmd:stop":
        if _task_proc and STATE["current_task"]:
            kill_task()
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Остановлено")
            tg_send(chat_id,
                    f"⛔ Задача {STATE['current_task']} остановлена — "
                    "воркер возьмёт следующую из очереди.")
        else:
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Ничего не выполняется")
        return
    if data == "cmd:mode":
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        send_mode_menu(chat_id, msg_id)
        return
    if action == "mode":
        if pid not in ("ask", "code"):
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Неизвестный режим")
            return
        set_reply_mode(pid)
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"Режим ответа: {pid}.",
               reply_markup={"inline_keyboard": []})
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        return
    if data == "cmd:session":
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        send_session_menu(chat_id, msg_id)
        return
    if action == "sess":
        if pid not in ("new", "continue"):
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Неизвестный режим")
            return
        set_session_mode(pid)
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"Режим сессий: {pid}.",
               reply_markup={"inline_keyboard": []})
        tg_api("answerCallbackQuery", callback_query_id=cb_id)
        return
    if action == "proj":
        if pid not in list_projects():
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Проект не найден")
            return
        set_project(pid)
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"Проект переключён на {pid}.",
               reply_markup={"inline_keyboard": []})
        tg_api("answerCallbackQuery", callback_query_id=cb_id,
               text=f"Проект: {pid}")
        return
    if action in ("commit", "skip"):
        row = task_row(pid)
        if not row or not row.get("commit_offered"):
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Уже обработано")
            return
        db_exec("UPDATE tasks SET commit_offered=0 WHERE stem=%s", (pid,))
        proj = row.get("project")
        cworkdir = (PROJECTS_ROOT / proj) \
            if (proj and PROJECTS_ROOT and (PROJECTS_ROOT / proj).is_dir()) \
            else WORKDIR
        if action == "commit":
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Коммичу и пушу…")
            result = do_commit(pid, cworkdir)
            tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="✅ Закоммичено и запушено.",
                   reply_markup={"inline_keyboard": []})
            tg_send(chat_id, f"git output:\n{result[-3500:]}")
            log(f"commit accepted for {pid}")
        else:
            tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
                   text="⏭ Изменения оставлены в репо — следующая задача их увидит.",
                   reply_markup={"inline_keyboard": []})
            tg_api("answerCallbackQuery", callback_query_id=cb_id)
            log(f"commit skipped for {pid}")
        return

    entry = _pop_pending(pid)
    if not entry:
        tg_api("answerCallbackQuery", callback_query_id=cb_id,
               text="Уже обработано или устарело")
        return

    if action == "ok":
        name = enqueue_task(entry["text"], chat_id)
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"Распознано:\n{entry['text']}\n\n✅ Задача {name} в очереди.",
               reply_markup={"inline_keyboard": []})
    else:
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"Распознано:\n{entry['text']}\n\n❌ Отменено.",
               reply_markup={"inline_keyboard": []})
    tg_api("answerCallbackQuery", callback_query_id=cb_id)


def handle_update(upd: dict) -> None:
    if cb := upd.get("callback_query"):
        try:
            handle_callback(cb)
        except Exception as e:
            log(f"callback error: {e}")
        return

    msg = upd.get("message") or upd.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    sender = (msg.get("from") or {}).get("username", "?")
    if not chat_id:
        log(f"update ignored (no chat): {json.dumps(upd)[:200]}")
        return
    try:
        if voice := msg.get("voice"):
            log(f"voice from @{sender} chat={chat_id}, {voice.get('duration', '?')}s")
            chain = _stt_chain(WEB_ADMIN_USER)
            if not any(_stt_ready(p, WEB_ADMIN_USER) for p in chain):
                tg_send(chat_id, "voice received, but no STT provider "
                                 "keys are set")
                return
            if multi_mode() and not current_project()[0]:
                tg_send(chat_id, "Сначала выбери проект: /projects")
                send_projects(chat_id)
                return
            dur = voice.get("duration")
            dur_txt = f" ({dur}с)" if dur else ""
            if chain == ["yandex"]:
                mode_txt = "синхронный" if dur is not None and dur < 28 \
                    else "асинхронный"
            else:
                mode_txt = "+".join(chain)
            res = tg_api("sendMessage", chat_id=chat_id,
                         text=f"📤 Аудио{dur_txt} отправлено на распознавание"
                              f" ({mode_txt} режим), жду…")
            status_msg = res["result"]["message_id"]

            def _st(stext: str) -> None:
                try:
                    tg_api("editMessageText", chat_id=chat_id,
                           message_id=status_msg, text=stext)
                except Exception:
                    pass

            text = transcribe(tg_download(voice["file_id"]),
                              on_status=_st, duration=dur)
            pid, entry = _pending_for_chat(chat_id)
            if pid:
                _add_to_pending(chat_id, pid, entry, text)
                return
            pid = str(upd.get("update_id") or int(time.time() * 1000))
            tg_api("editMessageText", chat_id=chat_id,
                   message_id=status_msg,
                   text=f"Проект: {project_label()}\n\nРаспознано:\n{text}",
                   reply_markup=_confirm_keyboard(pid))
            _save_pending({"chat_id": chat_id, "text": text,
                           "project": project_label(),
                           "message_id": status_msg,
                           "id": pid})
            log(f"pending confirm {pid} -> chat {chat_id}")
        elif text := (msg.get("text") or "").strip():
            log(f"text from @{sender} chat={chat_id}: {text[:100]}")
            if text.startswith("/"):
                handle_command(chat_id, text)
                return
            pid, entry = _pending_for_chat(chat_id)
            if pid:
                _add_to_pending(chat_id, pid, entry, text)
                return
            if multi_mode() and not current_project()[0]:
                tg_send(chat_id, "Сначала выбери проект: /projects")
                send_projects(chat_id)
                return
            name = enqueue_task(text, chat_id)
            tg_send(chat_id,
                    f"Проект: {project_label()}\nЗадача {name} в очереди.")
        else:
            log(f"update from @{sender} chat={chat_id}: unsupported content, skipped")
    except Exception as e:
        log(f"telegram update error: {e}")
        try:
            tg_send(chat_id, f"Error: {e}")
        except Exception:
            pass


def notify_chat(task_stem: str, response_text: str) -> None:
    row = task_row(task_stem)
    chat_id = row.get("chat_id") if row else None
    if not chat_id:
        log(f"no chat mapping for {task_stem} — result not sent to telegram")
        return
    log(f"delivering result of {task_stem} to chat {chat_id}")
    tg_send(chat_id, response_text)


def register_webhook() -> None:
    if not (TG_TOKEN and TG_WEBHOOK_URL):
        return
    try:
        params = {"url": TG_WEBHOOK_URL}
        if TG_WEBHOOK_SECRET:
            params["secret_token"] = TG_WEBHOOK_SECRET
        tg_api("setWebhook", **params)
        log(f"telegram webhook registered: {TG_WEBHOOK_URL}")
        info = tg_api("getWebhookInfo").get("result") or {}
        if err := info.get("last_error_message"):
            log(f"telegram webhook last error: {err} "
                f"(pending updates: {info.get('pending_update_count', 0)})")
    except Exception as e:
        log(f"setWebhook failed: {e}")


def register_commands() -> None:
    """Native telegram Menu button next to the input field."""
    if not TG_TOKEN:
        return
    try:
        tg_api("setMyCommands", commands=[
            {"command": "menu", "description": "меню бота"},
            {"command": "projects", "description": "выбор проекта"},
            {"command": "models", "description": "выбор модели"},
            {"command": "session", "description": "режим сессий"},
            {"command": "stop", "description": "убить текущую задачу"},
            {"command": "mode", "description": "код или ответ на вопрос"},
            {"command": "status", "description": "статус воркера"},
        ])
        log("telegram commands registered (menu button)")
    except Exception as e:
        log(f"setMyCommands failed: {e}")


def _git_head() -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(current_project()[1]), "log", "-1", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        return res.stdout.strip() or "n/a"
    except Exception:
        return "n/a"


# --- web UI / JSON API -------------------------------------------------------

def api_status() -> dict:
    return {
        "uptime": int(time.time() - _started_at),
        "queue": db_query(
            "SELECT COUNT(*) AS n FROM tasks WHERE status='queued'")[0]["n"],
        "current_task": STATE["current_task"],
        "last_task": STATE["last_task"],
        "last_status": STATE["last_status"],
        "tasks_done": STATE["tasks_done"],
        "model": current_model("web"),
        "project": project_label(),
        "mode": reply_mode("web"),
        "stt_status": STATE.get("stt") or "",
        "version": APP_VERSION,
        "user": _current_user() if _admin_hash() else "",
        "is_admin": _is_admin(),
    }


def api_projects() -> dict:
    u = _current_user()
    visible = _user_projects(u)
    wid = _active_ws(u)
    # только проекты активного пространства; wsmap — цвета точек в селекте
    mine = [p for p in visible if _project_ws(u, p) == wid]
    cur = current_project("web")[0]
    return {"projects": mine,
            "wsmap": {p: _project_ws(u, p) for p in visible},
            "current": cur if cur in mine else (mine[0] if mine else None),
            "multi": multi_mode()}


def api_models(fresh: bool = False) -> dict:
    global _models_cache
    # fresh — страница «Модели»: синхронный вызов `devin models list`
    # с полной выдачей; кэш при этом тоже обновляется
    models = devin_models() if fresh else get_models()
    if fresh and models:
        _models_cache = models
    return {"models": models, "current": current_model("web"),
            "fresh": bool(fresh)}


def _tail(path: Path, limit: int = 12000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return ANSI.sub("", data[-limit:].decode(errors="replace")).strip()


def api_tasks(project: str | None = None, limit: int = 5,
              before: str | None = None) -> dict:
    """Task feed, oldest -> newest, from the tasks table. The UI loads the
    newest `limit` tasks first and pages upward on scroll — `before` is a
    stem cursor: return up to `limit` items immediately older than that
    task (immune to new arrivals)."""
    running = Path(STATE["current_task"]).stem \
        if STATE["current_task"] else None
    sql, params = "SELECT * FROM tasks", []
    if project:
        sql += " WHERE project=%s"
        params.append(project)
    rows = db_query(sql + " ORDER BY created", params)
    items = []
    for r in rows:
        stem = r["stem"]
        st = "running" if stem == running else r["status"]
        out = ""
        if st == "running":
            out = _tail(TASKS_DIR / ".progress" / f"{stem}.out")
        elif st == "done":
            out = r["output"] or ""
            # история задач ещё содержит старый diff-блок в output —
            # обрезаем при отдаче, раздел «Изменения» покрывает это
            cut = out.find("### Что изменилось в репо")
            if cut != -1:
                out = out[:cut].rstrip()
        items.append({
            "name": _task_name(stem),
            "stem": stem,
            "project": r["project"] or "",
            "model": r["model"] or "",
            "mode": r["reply_mode"] or "",
            "source": r["source"],
            "status": st,
            "task_status": r["task_status"] or "",
            "commit_offered": bool(r["commit_offered"]),
            "created": int(r["created"]),
            "prompt": (r["prompt"] or "")[:2000],
            "output": out,
            # per-item content hash — the feed re-renders a card only when
            # this changes (no flicker on identical polls)
            "h": hashlib.md5(
                f"{st}|{r['task_status']}|{r['commit_offered']}|{out}"
                .encode()).hexdigest()[:12],
        })
    if before:
        idx = next((i for i, t in enumerate(items)
                    if t["stem"] == before), len(items))
        page, has_more = items[max(0, idx - limit):idx], idx > limit
    else:
        page, has_more = items[-limit:], len(items) > limit
    return {"tasks": page, "has_more": has_more}


# --- Flask app (replaces the hand-rolled BaseHTTPRequestHandler) -------------
# Same sync/threaded model as before — waitress runs handler threads; the
# blocking urllib/subprocess/PyMySQL code inside is unchanged.

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
app.config.update(SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax")

_admin_pw_hash: str | None = None  # cached; seeded into kv from env once


def _admin_hash() -> str:
    """Hash of the single admin account from kv.admin_password_hash —
    seeded there from WEB_ADMIN_PASSWORD on first use; /api/password
    rewrites the kv copy afterwards (env is only a bootstrap)."""
    global _admin_pw_hash
    if _admin_pw_hash is None:
        _admin_pw_hash = kv_get("admin_password_hash")
        if not _admin_pw_hash and WEB_ADMIN_PASSWORD:
            _admin_pw_hash = generate_password_hash(WEB_ADMIN_PASSWORD)
            kv_set("admin_password_hash", _admin_pw_hash)
            log(f"web admin password seeded from WEB_ADMIN_PASSWORD "
                f"(user {WEB_ADMIN_USER})")
    return _admin_pw_hash


def _user_hash(user: str) -> str:
    """Password hash for a web account: admin из kv, остальные — users."""
    if user == WEB_ADMIN_USER:
        return _admin_hash()
    r = db_query("SELECT pw_hash FROM users WHERE username=%s", (user,))
    return r[0]["pw_hash"] if r else ""


def _current_user() -> str:
    """uid из сессии; без auth (пустой пароль) — условный админ."""
    return session.get("uid") or WEB_ADMIN_USER


def _is_admin(user: str | None = None) -> bool:
    u = user or _current_user()
    if u == WEB_ADMIN_USER:
        return True
    r = db_query("SELECT is_admin FROM users WHERE username=%s", (u,))
    return bool(r and r[0]["is_admin"])


def _project_owner(name: str) -> str:
    """Владелец проекта; не размеченные (существовавшие до мультиюзера)
    лениво отдаются админу."""
    r = db_query("SELECT owner FROM project_owner WHERE name=%s", (name,))
    if r:
        return r[0]["owner"]
    db_exec("INSERT IGNORE INTO project_owner(name, owner)"
            " VALUES(%s,%s)", (name, WEB_ADMIN_USER))
    return WEB_ADMIN_USER


def _granted_projects(user: str) -> set:
    """Проекты, к которым юзеру выдан доступ (project_acl) — видит и
    работает в них, но владельцем не становится."""
    r = db_query("SELECT name FROM project_acl WHERE user=%s", (user,))
    return {x["name"] for x in r}


def _user_projects(user: str) -> list:
    """Проекты, видимые пользователю: админ — все, юзер — свои + выданные."""
    allp = list_projects()
    if _is_admin(user):
        return allp
    granted = _granted_projects(user)
    return [p for p in allp
            if _project_owner(p) == user or p in granted]


def _owns_project(name: str) -> bool:
    # «workspace» и прочие несуществующие папки — не проекты, доступны всем
    if not PROJECTS_ROOT or not (PROJECTS_ROOT / name).is_dir():
        return True
    u = _current_user()
    return _is_admin(u) or _project_owner(name) == u or \
        name in _granted_projects(u)


# --- per-user settings & secrets (kv.us:<uid> = JSON) -------------------

_SECRET_KEYS = {"stt.api_key", "gemini.api_key", "devin.api_key",
                "telegram.bot_token", "stt.base_url", "gitlab.base_url"}


def _fernet():
    """Fernet шифрование секретов в kv; ключ — kv.secret_key (сидится один
    раз). cryptography идёт в образе."""
    from cryptography.fernet import Fernet
    k = kv_get("secret_key")
    if not k:
        k = Fernet.generate_key().decode()
        kv_set("secret_key", k)
    return Fernet(k.encode())


def _us_raw(u: str) -> dict:
    try:
        return json.loads(kv_get(f"us:{u}", "{}"))
    except Exception:
        return {}


def us_get(u: str, key: str, default: str = "") -> str:
    """Декриптованное значение настройки юзера."""
    v = _us_raw(u).get(key, "")
    if isinstance(v, str) and v.startswith("enc:v1:"):
        try:
            return _fernet().decrypt(v[7:].encode()).decode()
        except Exception:
            return ""
    return v if isinstance(v, str) else default


def us_set(u: str, key: str, val: str) -> None:
    """Секретные ключи хранятся зашифрованными (enc:v1:…), остальное —
    plain. Пустое значение удаляет ключ."""
    d = _us_raw(u)
    if val == "":
        d.pop(key, None)
    else:
        d[key] = ("enc:v1:" + _fernet().encrypt(val.encode()).decode()
                  if key in _SECRET_KEYS else val)
    kv_set(f"us:{u}", json.dumps(d, ensure_ascii=False))


def us_all(u: str, mask: bool = True) -> dict:
    """Все настройки юзера; mask=True — секреты отдаются как …хвост."""
    out = {}
    for k, v in _us_raw(u).items():
        if isinstance(v, str) and v.startswith("enc:v1:"):
            p = us_get(u, k)
            out[k] = ("…" + p[-4:]) if (mask and len(p) > 4) else                      ("set" if p else "")
        else:
            out[k] = v
    return out


def uset(key: str, user: str | None = None,
         env: str | None = None, default: str = "") -> str:
    """Настройка: значение юзера → env → дефолт."""
    u = user or _current_user()
    return us_get(u, key) or os.environ.get(
        env or key.upper().replace(".", "_"), default)


def migrate_env_secrets() -> None:
    """Разово: env-креды сливаются в настройки админа (зашифрованные).
    Остальные юзеры получают пустые и видят env-фолбэк."""
    if kv_get("secrets_migrated"):
        return
    kv_set("secrets_migrated", "1")
    try:
        env_map = {
            "stt.provider": "STT_PROVIDER", "stt.api_key": "STT_API_KEY",
            "stt.base_url": "STT_BASE_URL", "stt.model": "STT_MODEL",
            "gemini.api_key": "GEMINI_API_KEY",
            "gemini.model": "GEMINI_MODEL",
            "yandex.folder_id": "YANDEX_FOLDER_ID",
            "yandex.lang": "YANDEX_LANG",
            "devin.api_key": "WINDSURF_API_KEY",
            "telegram.bot_token": "TELEGRAM_BOT_TOKEN",
            "gitlab.base_url": "GITLAB_BASE_URL",
            "git.name": "GIT_USER_NAME", "git.email": "GIT_USER_EMAIL",
        }
        a = WEB_ADMIN_USER
        for k, e in env_map.items():
            v = os.environ.get(e)
            if v and not us_get(a, k):
                us_set(a, k, v)
        # git-токены env → git_creds админа
        gh, gl = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITLAB_TOKEN")
        d = json.loads(kv_get(f"git_creds:{a}") or "{}") or {}
        if gh and "github.com" not in d:
            d["github.com"] = gh
        if gl:
            h = urllib.parse.urlparse(
                os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")
            ).hostname or "gitlab.com"
            d.setdefault(h, gl)
        if gh or gl:
            kv_set(f"git_creds:{a}", json.dumps(d))
        log(f"env secrets migrated to user settings ({a})")
    except Exception as e:
        kv_set("secrets_migrated", "")
        log(f"env->user secrets migration failed (retry): {e}")


# --- настройки проекта (kv.pj:<name> = JSON) -----------------------------
# model / reply_mode / auto_commit — задаются в шестерёнке селекта
# проектов; пустое = наследовать (модель — юзера, режим — юзера,
# auto_commit — по умолчанию ВЫКЛ).

def pj_get(name: str, key: str, default: str = "") -> str:
    try:
        v = json.loads(kv_get(f"pj:{name}", "{}")).get(key, "")
        return v if isinstance(v, str) else default
    except Exception:
        return default


def pj_set(name: str, key: str, val: str) -> None:
    try:
        d = json.loads(kv_get(f"pj:{name}", "{}"))
    except Exception:
        d = {}
    if val == "":
        d.pop(key, None)
    else:
        d[key] = val
    kv_set(f"pj:{name}", json.dumps(d, ensure_ascii=False))


# --- рабочие пространства (per-user) ------------------------------------

def _ensure_default_ws(user: str) -> int:
    """«По умолчанию» — создаётся каждому юзеру один раз, удалить нельзя
    (только переименовать/перекрасить)."""
    r = db_query("SELECT id FROM workspaces"
                 " WHERE owner=%s AND is_default=1", (user,))
    if r:
        return r[0]["id"]
    db_exec("INSERT INTO workspaces(owner, name, color, is_default)"
            " VALUES(%s,'По умолчанию','#1565c0',1)", (user,))
    return db_query("SELECT id FROM workspaces"
                    " WHERE owner=%s AND is_default=1", (user,))[0]["id"]


def _user_ws(user: str) -> list:
    _ensure_default_ws(user)
    return db_query("SELECT id, name, color, is_default"
                    " FROM workspaces WHERE owner=%s ORDER BY id", (user,))


def _active_ws(user: str) -> int:
    """Активное пространство юзера (kv.ws:<uid>), невалидное → дефолтное."""
    ws = _user_ws(user)
    wid = int(kv_get(f"ws:{user}") or 0)
    if not any(w["id"] == wid for w in ws):
        wid = next(w["id"] for w in ws if w["is_default"])
        kv_set(f"ws:{user}", str(wid))
    return wid


def _project_ws(user: str, name: str) -> int:
    """Пространство проекта для юзера; без записи → дефолтное
    (новые/зашаренные сюда и попадают)."""
    r = db_query("SELECT ws_id FROM project_ws WHERE user=%s AND name=%s",
                 (user, name))
    if r:
        return r[0]["ws_id"]
    wid = _ensure_default_ws(user)
    db_exec("INSERT IGNORE INTO project_ws(user, name, ws_id)"
            " VALUES(%s,%s,%s)", (user, name, wid))
    return wid


def _migrate_workspaces() -> None:
    """Одноразово: дефолтное пространство каждому юзеру + все существующие
    проекты в дефолт их владельцев/получателей."""
    users = {WEB_ADMIN_USER} | {
        r["username"] for r in db_query("SELECT username FROM users")}
    for u in users:
        _ensure_default_ws(u)
    for r in db_query("SELECT name, owner FROM project_owner"):
        _project_ws(r["owner"], r["name"])
    for r in db_query("SELECT name, user FROM project_acl"):
        _project_ws(r["user"], r["name"])


def login_required(fn):
    """Session gate: 401 JSON for /api/*, redirect to /login for pages.
    Disabled entirely when no admin password is configured."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if _admin_hash() and not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "auth required"}), 401
            return redirect("/login")
        return fn(*a, **kw)
    return wrapper


def _req_json() -> dict:
    return request.get_json(silent=True) or {}


@app.route("/login", methods=["GET", "POST"])
def _login():
    if not _admin_hash():          # no password configured → auth off
        return redirect("/")
    if request.method == "POST":
        user = request.form.get("user", "")
        pw = request.form.get("password", "")
        if _user_hash(user) and \
                check_password_hash(_user_hash(user), pw):
            session["uid"] = user
            log(f"web login ok: {user}")
            return redirect("/")
        log(f"web login failed: {user!r}")
        return redirect("/login?err=1")
    if session.get("uid"):
        return redirect("/")
    return render_template("login.html",
                           error=bool(request.args.get("err")))


@app.post("/logout")
def _logout():
    session.clear()
    return redirect("/login")


@app.post("/api/password")
@login_required
def _api_password():
    global _admin_pw_hash
    body = _req_json()
    u = _current_user()
    if not check_password_hash(_user_hash(u), body.get("current") or ""):
        return jsonify({"ok": False,
                        "error": "неверный текущий пароль"}), 403
    new = body.get("new") or ""
    if len(new) < 6:
        return jsonify({"ok": False,
                        "error": "новый пароль короче 6 символов"}), 400
    h = generate_password_hash(new)
    if u == WEB_ADMIN_USER:
        _admin_pw_hash = h
        kv_set("admin_password_hash", h)
    else:
        db_exec("UPDATE users SET pw_hash=%s WHERE username=%s", (h, u))
    log(f"web password changed ({u})")
    return jsonify({"ok": True})


# --- управление пользователями (только админ) ---------------------------

def _admin_only() -> bool:
    return _admin_hash() and _is_admin()


@app.get("/api/users")
@login_required
def _api_users():
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    out = [{"user": WEB_ADMIN_USER, "admin": True}]
    for r in db_query("SELECT username, is_admin FROM users"
                      " ORDER BY created"):
        out.append({"user": r["username"], "admin": bool(r["is_admin"])})
    return jsonify({"ok": True, "users": out})


@app.post("/api/users")
@login_required
def _api_users_add():
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    body = _req_json()
    u = (body.get("user") or "").strip()
    pw = body.get("password") or ""
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,64}", u):
        return jsonify({"ok": False, "error":
                        "логин: 2-64 символа, a-z, 0-9, точка, _ -"}), 400
    if u == WEB_ADMIN_USER or \
            db_query("SELECT 1 FROM users WHERE username=%s", (u,)):
        return jsonify({"ok": False,
                        "error": "такой пользователь уже есть"}), 409
    if len(pw) < 6:
        return jsonify({"ok": False,
                        "error": "пароль короче 6 символов"}), 400
    db_exec("INSERT INTO users(username, pw_hash, is_admin, created)"
            " VALUES(%s,%s,%s,%s)",
            (u, generate_password_hash(pw), 0, time.time()))
    _ensure_default_ws(u)   # «По умолчанию» — у каждого с рождения
    log(f"web user created: {u}")
    return jsonify({"ok": True, "user": u})


@app.post("/api/users/delete")
@login_required
def _api_users_del():
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    u = (_req_json().get("user") or "").strip()
    if u == WEB_ADMIN_USER:
        return jsonify({"ok": False, "error": "админа нельзя"}), 400
    db_exec("DELETE FROM users WHERE username=%s", (u,))
    # проекты ушедшего юзера переходят админу — иначе «осиротеют»
    db_exec("UPDATE project_owner SET owner=%s WHERE owner=%s",
            (WEB_ADMIN_USER, u))
    db_exec("DELETE FROM project_acl WHERE user=%s", (u,))
    log(f"web user deleted: {u}")
    return jsonify({"ok": True})


@app.get("/api/users/perms")
@login_required
def _api_users_perms_get():
    """Выданные юзеру проекты — для модалки прав (клик по юзеру)."""
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    u = (request.args.get("user") or "").strip()
    return jsonify({"ok": True, "user": u,
                    "granted": sorted(_granted_projects(u))})


@app.post("/api/users/perms")
@login_required
def _api_users_perms_set():
    """Заменить список выданных проектов юзера целиком."""
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    body = _req_json()
    u = (body.get("user") or "").strip()
    if u == WEB_ADMIN_USER:
        return jsonify({"ok": False,
                        "error": "админу права не нужны"}), 400
    projs = [p for p in (body.get("projects") or [])
             if p in list_projects()]
    db_exec("DELETE FROM project_acl WHERE user=%s", (u,))
    for p in projs:
        db_exec("INSERT INTO project_acl(name, user) VALUES(%s,%s)",
                (p, u))
        _project_ws(u, p)   # зашаренный проект → дефолт юзера
    log(f"web perms for {u}: {projs}")
    return jsonify({"ok": True, "granted": projs})


# --- API рабочих пространств ---------------------------------------------

@app.get("/api/ws")
@login_required
def _api_ws_list():
    u = _current_user()
    return jsonify({"ok": True, "active": _active_ws(u),
                    "ws": [{"id": w["id"], "name": w["name"],
                            "color": w["color"],
                            "default": bool(w["is_default"])}
                           for w in _user_ws(u)]})


@app.post("/api/ws")
@login_required
def _api_ws_new():
    body = _req_json()
    name = (body.get("name") or "").strip()[:64]
    color = (body.get("color") or "#1565c0").strip()[:16]
    if not name:
        return jsonify({"ok": False, "error": "имя пустое"}), 400
    db_exec("INSERT INTO workspaces(owner, name, color, is_default)"
            " VALUES(%s,%s,%s,0)", (_current_user(), name, color))
    return jsonify({"ok": True})


@app.post("/api/ws/update")
@login_required
def _api_ws_update():
    """Переименовать/перекрасить своё пространство (дефолтное — можно)."""
    body = _req_json()
    wid = int(body.get("id") or 0)
    u = _current_user()
    ws = [w for w in _user_ws(u) if w["id"] == wid]
    if not ws:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    name = (body.get("name") or ws[0]["name"]).strip()[:64]
    color = (body.get("color") or ws[0]["color"]).strip()[:16]
    db_exec("UPDATE workspaces SET name=%s, color=%s WHERE id=%s",
            (name, color, wid))
    return jsonify({"ok": True})


@app.post("/api/ws/delete")
@login_required
def _api_ws_del():
    body = _req_json()
    wid = int(body.get("id") or 0)
    u = _current_user()
    ws = [w for w in _user_ws(u) if w["id"] == wid]
    if not ws:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    if ws[0]["is_default"]:
        return jsonify({"ok": False,
                        "error": "дефолтное нельзя удалить"}), 400
    dw = _ensure_default_ws(u)
    db_exec("UPDATE project_ws SET ws_id=%s WHERE user=%s AND ws_id=%s",
            (dw, u, wid))
    db_exec("DELETE FROM workspaces WHERE id=%s", (wid,))
    if _active_ws(u) == wid:
        kv_set(f"ws:{u}", str(dw))
    return jsonify({"ok": True})


# --- настройки юзера (API-ключи и пр.) ----------------------------------

SETTING_FIELDS = [
    # (key, label, секрет?, подсказка, env-фолбэк)
    ("devin.api_key", "Devin API ключ", True,
     "ключ аккаунта Devin — им задачи кладутся в CLI", "WINDSURF_API_KEY"),
    ("stt.provider", "STT провайдер(ы)", False,
     "gemini / openai / yandex, через запятую — fallback-цепочка",
     "STT_PROVIDER"),
    ("stt.api_key", "STT API ключ", True,
     "openai-совместимый и yandex делят один ключ", "STT_API_KEY"),
    ("stt.base_url", "STT base URL", True,
     "напр. https://api.groq.com/openai/v1 или api.openai.com",
     "STT_BASE_URL"),
    ("stt.model", "STT модель", False,
     "whisper-1 / whisper-large-v3-turbo", "STT_MODEL"),
    ("gemini.api_key", "Gemini API ключ", True, "AIza…", "GEMINI_API_KEY"),
    ("gemini.model", "Gemini модель", False, "gemini-2.5-flash",
     "GEMINI_MODEL"),
    ("yandex.folder_id", "Yandex folder id", False, "b1g…",
     "YANDEX_FOLDER_ID"),
    ("yandex.lang", "Yandex язык", False, "ru-RU", "YANDEX_LANG"),
    ("telegram.bot_token", "Telegram bot token", True,
     "свой бот для задач — иначе общий (env)", "TELEGRAM_BOT_TOKEN"),
    ("gitlab.base_url", "GitLab base URL", True, "self-hosted домен",
     "GITLAB_BASE_URL"),
    ("git.name", "Git user.name", False, "подпись коммитов",
     "GIT_USER_NAME"),
    ("git.email", "Git user.email", False, "email коммитов",
     "GIT_USER_EMAIL"),
]


def _env_masked(env_name: str) -> str:
    """env-значение поля — маской, чтобы UI показывал фолбэк."""
    v = os.environ.get(env_name, "")
    return ("…" + v[-4:]) if len(v) > 4 else v


@app.get("/api/project/settings")
@login_required
def _api_project_settings_get():
    p = (request.args.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    return jsonify({"ok": True,
                    "model": pj_get(p, "model"),
                    "reply_mode": pj_get(p, "reply_mode"),
                    "auto_commit": pj_get(p, "auto_commit")})


@app.post("/api/project/settings")
@login_required
def _api_project_settings_set():
    body = _req_json()
    p = (body.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    for k, ok in (("model", None),
                  ("reply_mode", ("", "ask", "code")),
                  ("auto_commit", ("", "0", "1"))):
        v = (body.get(k) or "").strip()
        if ok is None or v in ok:
            pj_set(p, k, v)
    return jsonify({"ok": True})


@app.get("/api/settings")
@login_required
def _api_settings_get():
    """Настройки текущего юзера; секреты уходят маской …хвост.
    `env` — env-фолбэк каждого поля (маской), `effective` — итоговое
    значение, которое реально уйдёт в работу."""
    u = _current_user()
    mine = us_all(u)
    fields, eff = [], {}
    for k, l, s, h, e in SETTING_FIELDS:
        ev = _env_masked(e)
        fields.append({"key": k, "label": l, "secret": s, "hint": h,
                       "env": ev, "set": k in mine})
        eff[k] = mine.get(k) or ev
    return jsonify({"ok": True, "settings": mine, "effective": eff,
                    "fields": fields})


@app.post("/api/settings")
@login_required
def _api_settings_set():
    """Сохранить настройки: непустые значения пишутся (секреты
    шифруются), пустые пропускаются. Удаление — отдельным списком
    clear: [key…]."""
    body = _req_json()
    u = _current_user()
    for k in body.get("clear") or []:
        us_set(u, k, "")
    for k, l, s, h, e in SETTING_FIELDS:
        if k in body and isinstance(body[k], str) and body[k] != "":
            us_set(u, k, body[k])
    return jsonify({"ok": True})


@app.post("/api/ws/active")
@login_required
def _api_ws_active():
    wid = int((_req_json().get("id") or 0))
    u = _current_user()
    if wid not in [w["id"] for w in _user_ws(u)]:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    kv_set(f"ws:{u}", str(wid))
    return jsonify({"ok": True})


@app.post("/api/project/ws")
@login_required
def _api_project_ws():
    """Перенести проект в другое своё пространство (точка в селекте)."""
    body = _req_json()
    p = (body.get("project") or "").strip()
    wid = int(body.get("ws") or 0)
    u = _current_user()
    if not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    if wid not in [w["id"] for w in _user_ws(u)]:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    db_exec("INSERT INTO project_ws(user, name, ws_id) VALUES(%s,%s,%s)"
            " ON DUPLICATE KEY UPDATE ws_id=VALUES(ws_id)", (u, p, wid))
    return jsonify({"ok": True})


@app.get("/api/status")
@login_required
def _api_status():
    return jsonify(api_status())


@app.get("/api/projects")
@login_required
def _api_projects():
    return jsonify(api_projects())


@app.get("/api/models")
@login_required
def _api_models():
    return jsonify(api_models(
        fresh=request.args.get("fresh") == "1"))


@app.get("/api/tasks")
@login_required
def _api_tasks():
    try:
        limit = int(request.args.get("limit", "5"))
    except ValueError:
        limit = 5
    proj = request.args.get("project")
    if proj and not _owns_project(proj):
        abort(403)
    return jsonify(api_tasks(proj,
                             min(max(limit, 1), 50),
                             request.args.get("before")))


@app.get("/api/files")
@login_required
def _api_files():
    """One directory level of the selected project's file tree. The web
    panel lazy-loads children on each expand — a full recursive listing
    of a big repo would hang the request (and the browser)."""
    proj = (request.args.get("project") or "").strip()
    rel = (request.args.get("path") or "").strip().strip("/")
    root = _proj_root(proj)
    try:
        base = root.resolve()
        target = (base / rel).resolve()
    except OSError:
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not target.is_relative_to(base):   # ../ traversal stays out
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not target.is_dir():
        return jsonify({"ok": False, "error": "not a dir"}), 404
    try:
        items = sorted(
            (p for p in target.iterdir() if p.name != ".git"),
            key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    entries = [{"name": it.name,
                "type": "dir" if it.is_dir() else "file"}
               for it in items[:500]]
    return jsonify({"ok": True, "path": rel, "entries": entries,
                    "truncated": len(items) > 500})


def _proj_root(proj: str) -> Path:
    if proj and PROJECTS_ROOT and (PROJECTS_ROOT / proj).is_dir():
        if not _owns_project(proj):
            abort(403)
        return PROJECTS_ROOT / proj
    return WORKDIR


@app.get("/api/diff")
@login_required
def _api_diff():
    """Changed files of the project repo (git status --porcelain) — feeds
    the collapsible «Изменения» section under the web file tree."""
    proj = (request.args.get("project") or "").strip()
    root = _proj_root(proj)
    if not (root / ".git").exists():
        return jsonify({"ok": True, "entries": []})
    rc, out = _git(root, "status", "--porcelain")
    if rc != 0:
        return jsonify({"ok": False, "error": out[:200]}), 500
    entries = []
    for line in out.splitlines():
        # _git() strips stdout — the leading " " of " M file" is gone, so
        # fixed offsets won't do: split on the first whitespace run
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        status, path = parts
        if " -> " in path:           # rename: "old -> new"
            path = path.split(" -> ", 1)[1]
        entries.append({"path": path.strip(), "status": status.strip()})
    return jsonify({"ok": True, "entries": entries})


@app.get("/api/diff/file")
@login_required
def _api_diff_file():
    """Unified diff of one changed file (git diff HEAD — staged+unstaged);
    untracked files get an all-added diff via `git diff --no-index`."""
    proj = (request.args.get("project") or "").strip()
    rel = (request.args.get("path") or "").strip().strip("/")
    try:
        base = _proj_root(proj).resolve()
        target = (base / rel).resolve()
    except OSError:
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not rel or not target.is_relative_to(base):
        return jsonify({"ok": False, "error": "bad path"}), 400
    rc, out = _git(base, "diff", "--no-color", "HEAD", "--", rel)
    if rc == 0 and out.strip():
        return jsonify({"ok": True, "path": rel,
                        "diff": out[:300_000]})
    if target.is_file():
        # untracked — exit code 1 means "differs", that's expected here
        rc, out = _git(base, "diff", "--no-index", "--no-color",
                       "--", "/dev/null", str(target))
        if out.strip():
            return jsonify({"ok": True, "path": rel,
                            "diff": out[:300_000]})
        return jsonify({"ok": True, "path": rel, "diff": "",
                        "error": (out[:200] or "not a file")})
    return jsonify({"ok": True, "path": rel, "diff": ""})


_BUILD_CACHE: dict = {}    # proj -> (timestamp, result) — CI APIs rate-limit
_BUILD_TTL = 60


def _http_json(url: str, headers: dict | None = None, timeout: int = 20):
    """GET JSON via TG_OPENER (proxy-aware — GitHub/GitLab may need it)."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "devin-worker",
        **(headers or {})})
    try:
        with TG_OPENER.open(req, timeout=timeout) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        # verbose for the UI popover — "404: repo not found / private"
        body = e.read().decode("utf-8", errors="replace")[:300]
        return None, f"HTTP {e.code} {e.reason}: {body.strip()}"
    except urllib.error.URLError as e:
        return None, f"сеть: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def _parse_remote(url: str):
    """git remote URL -> (host, 'group/repo', token|None). The token is
    the password part of https user:pass@ remotes (e.g. cloned with
    x-access-token:ghp_…@github.com — reuse it for the CI API)."""
    url = url.strip()
    m = re.match(r"^(?:https?|ssh)://(?:([^@/\s]+)@)?([^/:]+)(?::\d+)?/"
                 r"(.+?)(?:\.git)?/?$", url)
    if m:
        userinfo, host, path = m.groups()
        token = userinfo.split(":", 1)[1] \
            if userinfo and ":" in userinfo else None
        return host.lower(), path.strip("/"), token
    m = re.match(r"^[^@\s]+@([^:\s]+):(.+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip("/"), None


def _gha_run(r: dict) -> dict:
    if r.get("status") != "completed":
        st = "running"
    else:
        st = {"success": "success", "failure": "failed",
              "timed_out": "failed", "startup_failure": "failed",
              "cancelled": "canceled"}.get(r.get("conclusion"), "unknown")
    return {"status": st, "name": r.get("name") or "",
            "ref": r.get("head_branch") or "",
            "num": r.get("run_number"),
            "url": r.get("html_url"), "when": r.get("created_at") or ""}


def _gha_status(repo: str, token: str | None = None) -> dict:
    tk = token or GITHUB_TOKEN
    headers = {"Authorization": f"Bearer {tk}"} if tk else {}
    data, err = _http_json(
        f"https://api.github.com/repos/{repo}/actions/runs?per_page=6",
        headers)
    if err:
        if err.startswith("HTTP 404"):
            err += " — репо не найден или приватный; " + \
                ("токен из remote не подошёл" if tk
                 else "задай GITHUB_TOKEN в .env")
        return {"ok": False, "error": f"GitHub: {err}"}
    raw = (data or {}).get("workflow_runs") or []
    if not raw:
        return {"ok": True, "provider": "github", "status": "none",
                "runs": []}
    runs = [_gha_run(r) for r in raw]
    top = runs[0]
    return {"ok": True, "provider": "github", "status": top["status"],
            "url": top["url"], "ref": top["ref"], "name": top["name"],
            "runs": runs}


def _gitlab_status(host: str, path: str, token: str | None = None) -> dict:
    tk = token or GITLAB_TOKEN
    headers = {"PRIVATE-TOKEN": tk} if tk else {}
    enc = urllib.parse.quote(path, safe="")
    data, err = _http_json(
        f"https://{host}/api/v4/projects/{enc}/pipelines?per_page=1",
        headers)
    if err:
        if err.startswith("HTTP 404"):
            err += " — проект не найден или приватный; " + \
                ("токен из remote не подошёл" if tk
                 else "задай GITLAB_TOKEN в .env")
        return {"ok": False, "error": f"GitLab: {err}"}
    if not data:
        return {"ok": True, "provider": "gitlab", "status": "none",
                "runs": []}

    def _gl_run(p):
        raw = p.get("status", "")
        st = {"success": "success", "failed": "failed",
              "canceled": "canceled", "skipped": "canceled"}.get(raw)
        if st is None:
            st = "running" if raw in (
                "running", "pending", "preparing", "created",
                "waiting_for_resource", "scheduled", "manual") \
                else "unknown"
        return {"status": st, "name": f"pipeline #{p.get('id', '')}",
                "ref": p.get("ref") or "", "num": p.get("id"),
                "url": p.get("web_url"),
                "when": p.get("updated_at") or p.get("created_at") or ""}

    runs = [_gl_run(p) for p in data[:6]]
    top = runs[0]
    return {"ok": True, "provider": "gitlab", "status": top["status"],
            "url": top["url"], "ref": top["ref"], "name": top["name"],
            "runs": runs}


def _build_status(root: Path) -> dict:
    """Last CI run of the project's origin — GitHub Actions or GitLab."""
    if not (root / ".git").exists():
        return {"ok": True, "status": "none"}
    rc, url = _git(root, "remote", "get-url", "origin")
    parsed = _parse_remote(url) if rc == 0 else None
    if not parsed:
        return {"ok": True, "status": "none"}
    host, path, token = parsed
    token = token or _cred_get(host)
    if host == "github.com":
        return _gha_status(path, token)
    gl_host = urllib.parse.urlparse(uset("gitlab.base_url", _current_user(), "GITLAB_BASE_URL", "https://gitlab.com")).hostname or ""
    if "gitlab" in host or host == gl_host:
        return _gitlab_status(host, path, token)
    return {"ok": True, "status": "none", "remote": host}


@app.get("/api/build")
@login_required
def _api_build():
    """CI status icon for the «Изменения» panel. Cached 60 s — the GHA
    rate limit is 60 req/h without a token, and pipeline state is slow."""
    proj = (request.args.get("project") or "").strip()
    hit = _BUILD_CACHE.get(proj)
    if hit and time.time() - hit[0] < _BUILD_TTL:
        return jsonify(hit[1])
    res = _build_status(_proj_root(proj))
    if res.get("ok"):
        _BUILD_CACHE[proj] = (time.time(), res)
    return jsonify(res)


@app.get("/api/stream")
@login_required
def _api_stream():
    """SSE keepalive stream. The web UI opens an EventSource here purely
    for connection liveness — the header dot goes green on open, spinner
    while the browser auto-reconnects (retry: 2 s), red when it can't.
    (Waitress is WSGI — no WebSocket — so SSE, which is the right fit:
    one thread per client out of the 16, keepalives keep the channel
    under channel_timeout and detect dead peers on write.)"""
    def gen():
        yield "retry: 2000\n\n"
        yield f"event: version\ndata: {json.dumps({'v': APP_VERSION})}\n\n"
        while True:
            yield ": ping\n\n"
            time.sleep(15)
            # piggyback the build version — the client reloads itself when
            # this no longer matches the version it was loaded with
            yield f"event: version\n" \
                  f"data: {json.dumps({'v': APP_VERSION})}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


def _file_target(proj: str, rel: str):
    """Resolve a project-relative file path, rejecting ../ traversal."""
    try:
        base = _proj_root(proj).resolve()
        target = (base / rel).resolve()
    except OSError:
        return None
    if not rel or not target.is_relative_to(base):
        return None
    return target


@app.get("/api/file")
@login_required
def _api_file_get():
    """Read one project file for the web code editor (CodeMirror modal).
    Text files only, ≤1 МБ — binaries and large files are refused."""
    proj = (request.args.get("project") or "").strip()
    rel = (request.args.get("path") or "").strip().strip("/")
    target = _file_target(proj, rel)
    if target is None:
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not target.is_file():
        return jsonify({"ok": False, "error": "not a file"}), 404
    try:
        if target.stat().st_size > 1_000_000:
            return jsonify({"ok": False,
                            "error": "файл больше 1 МБ"}), 413
        data = target.read_bytes()
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    if b"\x00" in data[:8192]:
        return jsonify({"ok": False, "error": "бинарный файл"}), 415
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"ok": False,
                        "error": "не UTF-8 текст"}), 415
    return jsonify({"ok": True, "path": rel, "content": text})


@app.post("/api/file")
@login_required
def _api_file_save():
    """Save text back into a project file from the web editor."""
    body = request.get_json(silent=True) or {}
    proj = (body.get("project") or "").strip()
    rel = (body.get("path") or "").strip().strip("/")
    content = body.get("content")
    if not isinstance(content, str) or len(content) > 2_000_000:
        return jsonify({"ok": False, "error": "bad content"}), 400
    target = _file_target(proj, rel)
    if target is None:
        return jsonify({"ok": False, "error": "bad path"}), 400
    if target.exists() and not target.is_file():
        return jsonify({"ok": False, "error": "not a file"}), 400
    try:
        tmp = target.with_name(target.name + ".~edit")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)          # atomic — no half-written files
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    return jsonify({"ok": True, "path": rel})


@app.post("/api/stt")
@login_required
def _api_stt():
    # browser mic → WAV octet-stream → STT → {text}
    audio = request.get_data()
    if not audio or len(audio) > 16_000_000:
        return jsonify({"ok": False, "error": "bad audio"}), 400
    try:
        text = web_transcribe(audio)
    except Exception as e:
        log(f"web stt failed: {e}")
        return jsonify({"ok": False, "error": str(e)[:300]}), 502
    log(f"web stt <- {len(audio)} bytes: {text!r}")
    return jsonify({"ok": True, "text": text})


@app.post("/api/project")
@login_required
def _api_project():
    p = (_req_json().get("project") or "").strip()
    if p not in list_projects():
        return jsonify({"ok": False, "error": "unknown project"}), 400
    set_project(p, "web")
    return jsonify({"ok": True, "project": p})


@app.post("/api/model")
@login_required
def _api_model():
    m = (_req_json().get("model") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", m):
        return jsonify({"ok": False, "error": "bad model"}), 400
    set_model(m, "web")
    return jsonify({"ok": True, "model": m})


@app.post("/api/mode")
@login_required
def _api_mode():
    m = (_req_json().get("mode") or "").strip()
    if m not in ("ask", "code"):
        return jsonify({"ok": False, "error": "bad mode"}), 400
    set_reply_mode(m, "web")
    return jsonify({"ok": True, "mode": m})


@app.post("/api/commit")
@login_required
def _api_commit():
    # same as tg commit/skip buttons: {"stem","action"}
    body = _req_json()
    stem = (body.get("stem") or "").strip()
    action = (body.get("action") or "").strip()
    row = task_row(stem)
    if not row or not row.get("commit_offered"):
        return jsonify({"ok": False, "error": "уже обработано"}), 409
    db_exec("UPDATE tasks SET commit_offered=0 WHERE stem=%s", (stem,))
    proj = row.get("project")
    cworkdir = (PROJECTS_ROOT / proj) \
        if (proj and PROJECTS_ROOT and (PROJECTS_ROOT / proj).is_dir()) \
        else WORKDIR
    if action == "commit":
        result = do_commit(stem, cworkdir)
        log(f"web commit accepted for {stem}")
        return jsonify({"ok": True, "result": result})
    log(f"web commit skipped for {stem}")
    return jsonify({"ok": True, "skipped": True})


@app.post("/api/stop")
@login_required
def _api_stop():
    """Web «Стоп» button — same kill_task() as telegram /stop."""
    if _task_proc and STATE["current_task"]:
        name = STATE["current_task"]
        kill_task()
        log(f"web stop killed {name}")
        return jsonify({"ok": True, "stopped": name})
    return jsonify({"ok": False, "error": "нет активной задачи"})


@app.post("/api/task/cancel")
@login_required
def _api_task_cancel():
    """Drop a still-queued task — web «удалить» on the card. Running
    tasks go through /api/stop (kill_task) instead."""
    stem = (_req_json().get("stem") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["status"] != "queued":
        return jsonify({"ok": False,
                        "error": "задача уже не в очереди"}), 409
    db_exec("DELETE FROM tasks WHERE stem=%s", (stem,))
    log(f"web cancel removed queued {stem}")
    return jsonify({"ok": True, "stem": stem})


@app.post("/api/project/add")
@login_required
def _api_project_add():
    """«+ Добавить проект» в вебе: clone a repo into PROJECTS_ROOT/<folder>.
    https URLs get the token injected (x-access-token@ for GitHub,
    oauth2@ for GitLab); ssh git@ URLs clone as-is (token not used).
    Output is echoed back for the dark <pre> in the modal, token masked."""
    body = _req_json()
    folder = (body.get("folder") or "").strip()
    url = (body.get("url") or "").strip()
    token = (body.get("token") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", folder or ""):
        return jsonify({"ok": False, "error":
                        "имя папки: только a-z, 0-9, точка, _ и -"}), 400
    if not PROJECTS_ROOT or not PROJECTS_ROOT.is_dir():
        return jsonify({"ok": False, "error":
                        "мультирежим не настроен (DEVIN_PROJECTS_DIR)"}), 400
    if (PROJECTS_ROOT / folder).exists():
        return jsonify({"ok": False,
                        "error": f"папка {folder} уже существует"}), 409
    parsed = _parse_remote(url)
    if not parsed:
        return jsonify({"ok": False, "error":
                        "не понимаю ссылку — нужен https://… или git@…"}), 400
    host, path, url_token = parsed
    is_ssh = url.startswith(("git@", "ssh://"))
    tk = token or url_token or _cred_get(host)
    if not tk and not is_ssh:
        return jsonify({"ok": False, "error":
                        f"для {host} нет сохранённого ключа — добавь его в "
                        "профиле → «Ключи репозиториев»"}), 400
    clone_url = url
    if url.startswith(("https://", "http://")) and not url_token:
        scheme = "https" if url.startswith("https://") else "http"
        user = "x-access-token" if host == "github.com" else "oauth2"
        clone_url = f"{scheme}://{user}:{tk}@{host}/{path}.git"
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
    dest = PROJECTS_ROOT / folder
    try:
        res = subprocess.run(["git", "clone", "--progress",
                              clone_url, str(dest)],
                             capture_output=True, text=True,
                             timeout=600, env=env)
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        return jsonify({"ok": False, "error": "clone timeout 600 c"}), 500
    out = (res.stdout + res.stderr).replace(tk, "***")
    if res.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        return jsonify({"ok": False, "error":
                        out[-4000:] or "clone failed"}), 500
    db_exec("INSERT IGNORE INTO project_owner(name, owner)"
            " VALUES(%s,%s)", (folder, _current_user()))
    wsel = int(body.get("ws") or 0)
    if wsel in [w["id"] for w in _user_ws(_current_user())]:
        db_exec("INSERT IGNORE INTO project_ws(user, name, ws_id)"
                " VALUES(%s,%s,%s)", (_current_user(), folder, wsel))
    log(f"web added project {folder} <- {host}/{path}"
        f" (owner {_current_user()})")
    return jsonify({"ok": True, "folder": folder, "output": out[-4000:]})


# --- repo credential store (kv.git_creds:<user> = {"host": "token"}) ----

def _creds() -> dict:
    try:
        d = json.loads(kv_get(f"git_creds:{_current_user()}", ""))
    except Exception:
        d = {}
    # наследие: до мультиюзера ключи лежали глобально — админ их видит
    if not d and _is_admin():
        try:
            d = json.loads(kv_get("git_creds", "{}"))
        except Exception:
            d = {}
    return d


def _creds_save(d: dict) -> None:
    kv_set(f"git_creds:{_current_user()}",
           json.dumps(d, ensure_ascii=False))


def _cred_get(host: str) -> str:
    """Saved token for a git host (github.com → GitHub, otherwise GitLab
    incl. self-hosted) — used when the add-project form has no token."""
    return _creds().get((host or "").lower(), "")


def _cred_propagate(host: str, token: str) -> int:
    """Rewrite the token in every cloned project's origin remote that
    points at <host> — rotating a key must not break existing clones."""
    user = "x-access-token" if host == "github.com" else "oauth2"
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
    n = 0
    for d in (PROJECTS_ROOT.iterdir() if PROJECTS_ROOT else []):
        # только свои проекты: чужие ремоуты трогать нельзя
        if _project_owner(d.name) != _current_user():
            continue
        if not d.is_dir() or not (d / ".git").exists():
            continue
        try:
            r = subprocess.run(["git", "-C", str(d), "remote",
                                "get-url", "origin"],
                               capture_output=True, text=True,
                               timeout=10, env=env)
            cur = r.stdout.strip()
            pr = _parse_remote(cur)
            if (r.returncode == 0 and pr and
                    pr[0] == host and
                    cur.startswith(("https://", "http://"))):
                new = f"https://{user}:{token}@{host}/{pr[1]}.git"
                subprocess.run(["git", "-C", str(d), "remote",
                                "set-url", "origin", new],
                               capture_output=True, text=True,
                               timeout=10, env=env)
                n += 1
        except Exception:
            continue
    return n


@app.get("/api/creds")
@login_required
def _api_creds_list():
    """Repository keys for the profile modal — token masked, only the
    last 4 chars shown."""
    out = []
    for host, tk in sorted(_creds().items()):
        out.append({"host": host,
                    "kind": "github" if host == "github.com" else "gitlab",
                    "mask": f"…{tk[-4:]}" if len(tk) > 4 else "…"})
    return jsonify({"ok": True, "creds": out})


@app.post("/api/creds")
@login_required
def _api_creds_set():
    body = _req_json()
    kind = (body.get("type") or "").strip()
    host = "github.com" if kind == "github" else \
        (body.get("host") or "").strip().lower().removeprefix("https://") \
        .split("/")[0]
    token = (body.get("token") or "").strip()
    if not host or "/" in host:
        return jsonify({"ok": False, "error": "укажи домен хоста"}), 400
    if not token:
        return jsonify({"ok": False, "error": "ключ пустой"}), 400
    d = _creds()
    old = d.get(host)
    d[host] = token
    _creds_save(d)
    # всегда — idempotent: если remote уже с этим токеном, set-url no-op;
    # зато чинит remote'ы, когда ключ сохранили до появления propagate.
    n = _cred_propagate(host, token)
    log(f"web saved cred for {host}" + (f", updated {n} remotes" if n else ""))
    return jsonify({"ok": True, "host": host, "updated": n})


@app.post("/api/creds/delete")
@login_required
def _api_creds_del():
    host = (body := _req_json()).get("host", "")
    d = _creds()
    if host in d:
        del d[host]
        _creds_save(d)
    return jsonify({"ok": True})


@app.post("/api/tasks")
@login_required
def _api_task_new():
    body = _req_json()
    text = (body.get("text") or "").strip()
    project = (body.get("project") or "").strip() or None
    if not text:
        return jsonify({"ok": False, "error": "empty text"}), 400
    if len(text) > 20000:
        return jsonify({"ok": False, "error": "text too long"}), 400
    if multi_mode() and project not in _user_projects(_current_user()):
        return jsonify({"ok": False, "error": "unknown project"}), 400
    name = enqueue_task(text, project=project, prefix="web")
    return jsonify({"ok": True, "name": name}), 201


@app.get("/")
@app.get("/index.html")
@login_required
def _index():
    return render_template("webui.html")


@app.post("/")
@app.post("/<path:_any>")
def _webhook(_any: str = ""):
    # any POST to a non-/api path is the telegram webhook — robust against
    # whatever path prefix the reverse proxy preserves; secret-token check
    if TG_WEBHOOK_SECRET and \
            request.headers.get("X-Telegram-Bot-Api-Secret-Token") \
            != TG_WEBHOOK_SECRET:
        log(f"POST /{_any}: bad webhook secret — 403")
        return "", 403
    body = request.get_data()
    try:
        upd = json.loads(body)
    except ValueError:
        log(f"POST /{_any}: bad JSON ({len(body)} bytes), ignored")
        return "", 200
    log(f"POST /{_any}: update_id={upd.get('update_id')}, {len(body)} bytes")
    threading.Thread(target=handle_update, args=(upd,), daemon=True).start()
    return "", 200


def _legacy_status_page() -> str:
    uptime = int(time.time() - _started_at)
    h, m, s = uptime // 3600, uptime % 3600 // 60, uptime % 60
    queue = db_query(
        "SELECT COUNT(*) AS n FROM tasks WHERE status='queued'")[0]["n"]
    bot = "running" if (_bot_proc and _bot_proc.poll() is None) else "off"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>devin watcher</title></head>
<body style="font-family:monospace;max-width:640px;margin:40px auto">
<h1>devin watcher — I'm working</h1>
<table>
<tr><td>status</td><td><b>running</b></td></tr>
<tr><td>uptime</td><td>{h}h {m}m {s}s</td></tr>
<tr><td>repo HEAD</td><td>{html.escape(_git_head())}</td></tr>
<tr><td>queue</td><td>{queue} task(s) in inbox</td></tr>
<tr><td>model</td><td>{html.escape(current_model())}</td></tr>
<tr><td>project</td><td>{html.escape(project_label())}</td></tr>
<tr><td>current task</td><td>{html.escape(STATE["current_task"] or "-")}</td></tr>
<tr><td>last task</td><td>{html.escape(str(STATE["last_task"]))} ({html.escape(str(STATE["last_status"]))})</td></tr>
<tr><td>tasks done</td><td>{STATE["tasks_done"]}</td></tr>
<tr><td>telegram bot</td><td>{bot}</td></tr>
</table>
</body></html>"""


@app.get("/favicon.ico")
def _favicon():
    # browsers still probe /favicon.ico directly — without this they'd get
    # the status-page HTML from the catch-all below
    return app.send_static_file("favicon.ico")


@app.get("/sw.js")
def _service_worker():
    # PWA service worker — served from the root path so its scope covers "/"
    # (a script under /static/ could only control /static/*); the spec
    # requires the Service-Worker-Allowed header for a scope that wide.
    # no-cache: SW updates must be picked up promptly.
    resp = app.send_static_file("sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/status")
@app.get("/<path:_any>")   # unknown GET → status page (public, as before)
def _status_page(_any: str = ""):
    return Response(_legacy_status_page(), mimetype="text/html")


def start_web() -> None:
    # env wins; otherwise a generated key persisted in kv — sessions survive
    # container restarts either way
    app.secret_key = WEB_SESSION_SECRET or kv_get("session_secret") \
        or secrets.token_hex(32)
    kv_set("session_secret", app.secret_key)
    threading.Thread(
        target=lambda: serve(app, host="0.0.0.0", port=WEB_PORT,
                             threads=16, channel_timeout=600),
        daemon=True).start()
    log(f"web ui on :{WEB_PORT}"
        + ("" if _admin_hash()
           else " — auth OFF (set WEB_ADMIN_PASSWORD to enable)"))


def start_mihomo() -> None:
    """Run mihomo when /mihomo/config.yaml is mounted.

    mihomo exposes a local HTTP/SOCKS5 proxy at MIHOMO_PROXY (default
    127.0.0.1:7890) forwarding to the nodes from the config. If no explicit
    *_proxy env is set, it becomes the default proxy for the devin API and
    telegram — children inherit os.environ, TG_OPENER is rebuilt for the
    in-process webhook handler. Git stays direct either way.
    """
    global _mihomo_proc, TG_OPENER
    cfg = MIHOMO_DIR / "config.yaml"
    if not cfg.exists():
        return
    if _mihomo_proc and _mihomo_proc.poll() is None:
        return
    try:
        _mihomo_proc = subprocess.Popen(["mihomo", "-d", str(MIHOMO_DIR)])
    except FileNotFoundError:
        log("mihomo config found but the binary is missing — not starting")
        return
    log(f"mihomo started (config {cfg}), waiting for {MIHOMO_PROXY}")
    port = int(MIHOMO_PROXY.rsplit(":", 1)[-1])
    for _ in range(50):
        if _mihomo_proc.poll() is not None:
            log(f"mihomo exited ({_mihomo_proc.returncode}) — "
                "check /mihomo/config.yaml; running without it")
            return
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        log("mihomo port did not open in 10s — continuing anyway")
    if not (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")):
        os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"] = MIHOMO_PROXY
        os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
        os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
        TG_OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {"http": MIHOMO_PROXY, "https": MIHOMO_PROXY}))
        log(f"proxy -> {MIHOMO_PROXY} (mihomo) for devin API and telegram; "
            "git stays direct")


def start_bot() -> None:
    """Run bot.py in parallel when TELEGRAM_BOT_TOKEN is set."""
    global _bot_proc
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    if _bot_proc and _bot_proc.poll() is None:
        return
    log("starting telegram bot")
    # -u: unbuffered stdout so bot logs show up in `docker logs`
    _bot_proc = subprocess.Popen([sys.executable, "-u", BOT_SCRIPT])


def main() -> int:
    global _bot_proc, _mihomo_proc
    for d in (INBOX, DONE, OUTBOX):
        d.mkdir(parents=True, exist_ok=True)

    init_db()
    migrate_files_to_db()
    migrate_env_secrets()
    _migrate_workspaces()
    cleanup_legacy_files()
    ensure_repo()
    start_mihomo()
    start_bot()
    register_webhook()
    register_commands()
    start_web()
    # каталог моделей для веб-селекта — в фоне: mihomo может ещё мерить ноды
    threading.Thread(target=refresh_models, daemon=True).start()
    log(f"watching {INBOX} every {POLL_INTERVAL}s (timeout {TASK_TIMEOUT}s)")
    while True:
        try:
            if _bot_proc and _bot_proc.poll() is not None \
                    and _bot_proc.returncode != 0:
                # clean exit (e.g. INTERVAL<=0 one-shot mode) — don't restart
                log(f"telegram bot exited ({_bot_proc.returncode}), restarting")
                start_bot()
            if _mihomo_proc and _mihomo_proc.poll() is not None:
                log(f"mihomo exited ({_mihomo_proc.returncode}), restarting")
                _mihomo_proc = None
                start_mihomo()
            task = next_task()
            if task is None:
                time.sleep(POLL_INTERVAL)
                continue
            run_task(task)
        except KeyboardInterrupt:
            log("stopping")
            if _bot_proc:
                _bot_proc.terminate()
            if _mihomo_proc:
                _mihomo_proc.terminate()
            return 0
        except Exception as e:  # keep the watcher alive no matter what
            log(f"ERROR: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
