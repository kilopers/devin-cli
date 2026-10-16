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

import base64
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
WEBUI_FILE = Path(os.environ.get("WEBUI_FILE", "/app/webui.html"))
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
    # контейнер пересоздали посреди задачи — 'running' вернуть в очередь
    db_exec("UPDATE tasks SET status='queued' WHERE status='running'")
    log(f"mysql: connected to {MYSQL['host']}:{MYSQL['port']}/"
        f"{MYSQL['database']}, schema ready")


def _task_name(stem: str) -> str:
    return f"{stem}.txt"


def _insert_task(stem: str, prompt: str, source: str,
                 project: str | None, chat_id, created: float) -> None:
    db_exec("INSERT INTO tasks (stem, source, project, chat_id, prompt, "
            "created) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE prompt=VALUES(prompt)",
            (stem, source, project, chat_id, prompt, created))


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
               DEVIN_MODEL=current_model(), DEVIN_WORKDIR=str(workdir),
               DEVIN_CONTINUE="true" if continue_mode() else "false",
               REPLY_MODE=reply_mode(),
               DEVIN_EXPORT_FILE=str(export_path))
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
    if TG_TOKEN:
        notify_chat(stem, f"{name}\n{status}\n\n{body[-3500:]}")
        if chat_id:
            send_task_stats(chat_id, started_ts)
            offer_commit(task, chat_id, workdir)


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


def gemini_transcribe(audio: bytes, mime: str = "audio/ogg") -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    payload = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
        {"text": "Transcribe this voice message. Reply with only the "
                 "transcription, in its original language."},
    ]}]}
    log(f"gemini -> transcribing {len(audio)} bytes with {GEMINI_MODEL}")
    started = time.time()
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with TG_OPENER.open(req, timeout=120) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"gemini HTTP {e.code}: {e.read().decode()[:500]}")


def openai_transcribe(audio: bytes, mime: str = "audio/ogg") -> str:
    """OpenAI-compatible /audio/transcriptions (OpenAI, Groq, …)."""
    boundary = "----devincli" + str(int(time.time() * 1000))
    ext = {"audio/ogg": "oga", "audio/mpeg": "mp3", "audio/mp4": "m4a",
           "audio/wav": "wav"}.get(mime, "ogg")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="model"\r\n\r\n{STT_MODEL}\r\n'.encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="file"; filename="voice.{ext}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode() + audio + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    log(f"stt -> transcribing {len(audio)} bytes via {STT_BASE_URL} ({STT_MODEL})")
    started = time.time()
    req = urllib.request.Request(
        f"{STT_BASE_URL}/audio/transcriptions",
        data=b"".join(parts),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {STT_API_KEY}",
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


def _yandex_request(path: str, body: dict | None = None) -> str:
    headers = {"Authorization": f"Api-Key {STT_API_KEY}",
               "Content-Type": "application/json"}
    if YANDEX_FOLDER_ID:
        headers["x-folder-id"] = YANDEX_FOLDER_ID
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


def yandex_transcribe_sync(audio: bytes, mime: str = "audio/ogg") -> str:
    """SpeechKit v1 sync recognition — fast path for short clips (≤~30s)."""
    started = time.time()
    qs = f"?lang={YANDEX_LANG}&format=oggopus&sampleRateHertz=48000"
    if YANDEX_FOLDER_ID:
        qs += f"&folderId={YANDEX_FOLDER_ID}"
    req = urllib.request.Request(
        YANDEX_STT_HOST + "/speech/v1/stt:recognize" + qs,
        data=audio,
        headers={"Authorization": f"Api-Key {STT_API_KEY}"},
        method="POST")
    log(f"stt -> yandex v1 sync, {len(audio)} bytes, lang={YANDEX_LANG}")
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
            "audioFormat": {"containerAudio":
                            {"containerAudioType": "OGG_OPUS"}},
            "textNormalization": {"textNormalization":
                                  "TEXT_NORMALIZATION_ENABLED",
                                  "literatureText": True},
            "languageRestriction": {"restrictionType": "WHITELIST",
                                    "languageCode": [YANDEX_LANG]},
        },
    }
    log(f"stt -> yandex speechkit v3 async, {len(audio)} bytes, lang={YANDEX_LANG}")
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


def transcribe(audio: bytes, mime: str = "audio/ogg", on_status=None,
               duration=None) -> str:
    if STT_PROVIDER == "yandex":
        if duration is not None and duration < 28:
            return yandex_transcribe_sync(audio, mime)
        return yandex_transcribe(audio, mime, on_status)
    if STT_PROVIDER == "gemini":
        return gemini_transcribe(audio, mime)
    return openai_transcribe(audio, mime)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def enqueue_task(text: str, chat_id: int | None = None,
                 project: str | None = None, prefix: str = "tg") -> str:
    stem = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}" \
           f"-{(int(time.time() * 1000) % 100000):05d}"
    proj = project or (current_project()[0] if multi_mode() else None)
    source = {"tg": "telegram", "web": "web"}.get(prefix, prefix)
    _insert_task(stem, text, source, proj, chat_id, time.time())
    log(f"task {_task_name(stem)} queued in mysql, chat_id={chat_id}, "
        f"project={proj}")
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


def current_project() -> tuple:
    """(project name or None, workdir Path). Single mode: (None, WORKDIR)."""
    if not multi_mode():
        return None, WORKDIR
    name = kv_get("project")
    if name and (PROJECTS_ROOT / name).is_dir():
        return name, PROJECTS_ROOT / name
    return None, PROJECTS_ROOT


def set_project(name: str) -> None:
    kv_set("project", name)
    log(f"project switched to {name}")


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


def reply_mode() -> str:
    """'ask' = answer questions about the repo, no edits; 'code' = do tasks."""
    m = kv_get("reply_mode")
    if m in ("ask", "code"):
        return m
    return os.environ.get("REPLY_MODE", "code")


def set_reply_mode(mode: str) -> None:
    kv_set("reply_mode", mode)
    log(f"reply mode -> {mode}")


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


def current_model() -> str:
    """Model for the next task: UI/telegram override wins over DEVIN_MODEL."""
    return kv_get("model") or os.environ.get("DEVIN_MODEL", "swe")


def set_model(name: str) -> None:
    kv_set("model", name.strip())
    log(f"model switched to {name}")


def _models_from_json(data) -> list:
    """Normalize `devin models list --format json` to [{id, description}].

    The exact schema isn't documented: families may nest runnable models
    under "models"/"variants" and short names under "aliases". A family
    name itself isn't a runnable model id, so it's never offered."""
    out = []

    def add(mid, desc=""):
        if isinstance(mid, str) \
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", mid) \
                and all(m["id"] != mid for m in out):
            out.append({"id": mid,
                        "description": desc if isinstance(desc, str) else ""})

    def walk(x, desc=""):
        if isinstance(x, dict):
            d = x.get("description") or x.get("display_name") or desc
            kids = next((x[k] for k in ("models", "variants", "items",
                                        "children")
                         if isinstance(x.get(k), list)), None)
            mid = next((x[k] for k in ("id", "slug", "model")
                        if isinstance(x.get(k), str)), None)
            if mid is None and kids is None:
                v = x.get("name")
                if isinstance(v, str):
                    mid = v  # leaf dict — name is the model id
            if mid and kids is None:
                add(mid, d)
            fam = mid or (x.get("name") if isinstance(x.get("name"), str)
                          else "")
            for v in kids or []:
                walk(v, d)
            for a in x.get("aliases") or []:
                if isinstance(a, str):
                    add(a, f"алиас {fam}".strip())
                else:
                    walk(a, d)
            if mid is None and kids is None:
                for v in x.values():
                    if isinstance(v, (dict, list)):
                        walk(v, d)
        elif isinstance(x, list):
            for v in x:
                walk(v, desc)
        elif isinstance(x, str):
            add(x, desc)

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
    """After a task: show repo state with commit/push/skip buttons."""
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
    if dirty:
        label = f"✅ Закоммитить и запушить ({dirty} файл(ов))"
    else:
        label = f"⬆ Запушить {unpushed} коммит(ов)"
    stem = task["stem"]
    db_exec("UPDATE tasks SET commit_offered=1 WHERE stem=%s", (stem,))
    tg_api("sendMessage", chat_id=chat_id,
           text=f"В репо: {dirty} незакоммиченных, {unpushed} незапушенных. Что делаем?",
           reply_markup={"inline_keyboard": [
               [{"text": label, "callback_data": f"commit:{stem}"}],
               [{"text": "⏭ Пропустить", "callback_data": f"skip:{stem}"}],
           ]})
    log(f"commit offer for {stem}: dirty={dirty} unpushed={unpushed}")


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
            if STT_PROVIDER == "gemini" and not GEMINI_API_KEY:
                tg_send(chat_id, "voice received, but GEMINI_API_KEY is not set")
                return
            if STT_PROVIDER != "gemini" and not STT_API_KEY:
                tg_send(chat_id, "voice received, but STT_API_KEY is not set")
                return
            if multi_mode() and not current_project()[0]:
                tg_send(chat_id, "Сначала выбери проект: /projects")
                send_projects(chat_id)
                return
            dur = voice.get("duration")
            dur_txt = f" ({dur}с)" if dur else ""
            if STT_PROVIDER == "yandex":
                mode_txt = "синхронный" if dur is not None and dur < 28 \
                    else "асинхронный"
            else:
                mode_txt = STT_PROVIDER
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
        "model": current_model(),
        "project": project_label(),
        "mode": reply_mode(),
    }


def api_projects() -> dict:
    return {"projects": list_projects(), "current": current_project()[0],
            "multi": multi_mode()}


def api_models() -> dict:
    return {"models": get_models(), "current": current_model()}


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
    # tasks without a recorded project show up under every tab
    if project:
        sql += " WHERE project=%s OR project IS NULL"
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
        items.append({
            "name": _task_name(stem),
            "stem": stem,
            "project": r["project"] or "",
            "source": r["source"],
            "status": st,
            "task_status": r["task_status"] or "",
            "created": int(r["created"]),
            "prompt": (r["prompt"] or "")[:2000],
            "output": out,
        })
    if before:
        idx = next((i for i, t in enumerate(items)
                    if t["stem"] == before), len(items))
        page, has_more = items[max(0, idx - limit):idx], idx > limit
    else:
        page, has_more = items[-limit:], len(items) > limit
    return {"tasks": page, "has_more": has_more}


class StatusHandler(BaseHTTPRequestHandler):
    def _json(self, obj, code: int = 200) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path: Path, ctype: str) -> bool:
        try:
            data = path.read_bytes()
        except OSError:
            return False
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            return self._json(api_status())
        if path == "/api/projects":
            return self._json(api_projects())
        if path == "/api/models":
            return self._json(api_models())
        if path == "/api/tasks":
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                limit = int((qs.get("limit") or ["5"])[0])
            except ValueError:
                limit = 5
            return self._json(api_tasks(
                (qs.get("project") or [None])[0],
                min(max(limit, 1), 50),
                (qs.get("before") or [None])[0]))
        if path in ("/", "/index.html") and \
                self._serve_file(WEBUI_FILE, "text/html; charset=utf-8"):
            return
        self._legacy_status_page()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ("/api/tasks", "/api/model", "/api/project"):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"ok": False, "error": "bad json"}, 400)
            if path == "/api/project":
                p = (body.get("project") or "").strip()
                if p not in list_projects():
                    return self._json({"ok": False,
                                       "error": "unknown project"}, 400)
                set_project(p)
                return self._json({"ok": True, "project": p})
            if path == "/api/model":
                m = (body.get("model") or "").strip()
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", m):
                    return self._json({"ok": False, "error": "bad model"}, 400)
                set_model(m)
                return self._json({"ok": True, "model": m})
            text = (body.get("text") or "").strip()
            project = (body.get("project") or "").strip() or None
            if not text:
                return self._json({"ok": False, "error": "empty text"}, 400)
            if len(text) > 20000:
                return self._json({"ok": False, "error": "text too long"}, 400)
            if multi_mode() and project not in list_projects():
                return self._json({"ok": False, "error": "unknown project"},
                                  400)
            name = enqueue_task(text, project=project, prefix="web")
            return self._json({"ok": True, "name": name}, 201)
        # any other POST path is treated as the telegram webhook — robust
        # against whatever path prefix the reverse proxy preserves
        if TG_WEBHOOK_SECRET and \
                self.headers.get("X-Telegram-Bot-Api-Secret-Token") != TG_WEBHOOK_SECRET:
            log(f"POST {self.path}: bad webhook secret — 403")
            self.send_response(403)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        try:
            upd = json.loads(body)
        except ValueError:
            log(f"POST {self.path}: bad JSON ({length} bytes), ignored")
            return
        log(f"POST {self.path}: update_id={upd.get('update_id')}, "
            f"{length} bytes")
        threading.Thread(target=handle_update, args=(upd,), daemon=True).start()

    def _legacy_status_page(self) -> None:
        uptime = int(time.time() - _started_at)
        h, m, s = uptime // 3600, uptime % 3600 // 60, uptime % 60
        queue = db_query(
            "SELECT COUNT(*) AS n FROM tasks WHERE status='queued'")[0]["n"]
        bot = "running" if (_bot_proc and _bot_proc.poll() is None) else "off"
        body = f"""<!doctype html><html><head><meta charset="utf-8">
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
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # keep docker logs clean
        pass


def start_web() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), StatusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"status page on :{WEB_PORT}")


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
