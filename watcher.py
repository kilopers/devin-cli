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
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
TG_CHATS_FILE = TASKS_DIR / "tg-chats.json"  # task stem -> chat_id
PENDING_FILE = TASKS_DIR / "tg-pending.json"  # pending id -> {chat_id, text}
MODEL_FILE = TASKS_DIR / "model.txt"  # telegram-selected DEVIN_MODEL override
COMMITS_FILE = TASKS_DIR / "tg-commits.json"  # task stem -> {chat_id, workdir}
PROJECT_FILE = TASKS_DIR / "project.txt"  # selected project name (multi mode)

_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
if _proxy:
    TG_OPENER = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": _proxy, "https": _proxy})
    )
else:
    TG_OPENER = urllib.request.build_opener()

_bot_proc: subprocess.Popen | None = None
_started_at = time.time()

STATE = {
    "current_task": None,
    "last_task": "-",
    "last_status": "-",
    "tasks_done": 0,
}


def log(msg: str) -> None:
    print(f"[watcher] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def next_task() -> Path | None:
    tasks = sorted(INBOX.glob("*.txt"), key=lambda p: p.stat().st_mtime)
    return tasks[0] if tasks else None


def run_task(task: Path) -> None:
    log(f"processing {task.name}")
    STATE["current_task"] = task.name
    processing = task.with_name(task.name + ".processing")
    task.rename(processing)

    started_ts = time.time()
    _, workdir = current_project()
    env = dict(os.environ, DEVIN_TASK_FILE=str(processing),
               DEVIN_MODEL=current_model(), DEVIN_WORKDIR=str(workdir))
    try:
        res = subprocess.run(
            [DEVIN_TASK],
            env=env,
            capture_output=True,
            text=True,
            timeout=TASK_TIMEOUT,
        )
        status = f"exit code: {res.returncode}"
        body = res.stdout
        if res.stderr:
            body += f"\n\n--- STDERR ---\n{res.stderr}"
    except subprocess.TimeoutExpired as e:
        status = f"TIMEOUT after {TASK_TIMEOUT}s"
        body = (e.stdout or "") + (f"\n\n--- STDERR ---\n{e.stderr}" if e.stderr else "")

    response = OUTBOX / f"{task.stem}.response.txt"
    response.write_text(
        f"task:    {task.name}\n"
        f"status:  {status}\n"
        f"started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'=' * 60}\n\n{body}"
    )
    processing.rename(DONE / task.name)
    STATE.update(current_task=None, last_task=task.name,
                 last_status=status, tasks_done=STATE["tasks_done"] + 1)
    log(f"done {task.name} -> outbox/{response.name} ({status})")
    if TG_TOKEN:
        chat_id = _load_chats().get(task.stem)
        notify_chat(task.stem, f"{task.name}\n{status}\n\n{response.read_text()[-3500:]}")
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


def yandex_transcribe(audio: bytes, mime: str = "audio/ogg") -> str:
    """Yandex SpeechKit v1 synchronous recognition (short audio, ~30s)."""
    params = {"format": "oggopus", "lang": YANDEX_LANG,
              "sampleRateHertz": "48000", "model": "general"}
    if YANDEX_FOLDER_ID:
        params["folderId"] = YANDEX_FOLDER_ID
    url = ("https://stt.api.cloud.yandex.net/speech/v1/stt:recognize?"
           + urllib.parse.urlencode(params))
    log(f"stt -> yandex speechkit, {len(audio)} bytes, lang={YANDEX_LANG}")
    started = time.time()
    req = urllib.request.Request(url, data=audio, headers={
        "Authorization": f"Api-Key {STT_API_KEY}",
        "Content-Type": "application/octet-stream",
    })
    try:
        with TG_OPENER.open(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"yandex stt HTTP {e.code}: {e.read().decode()[:500]}")
    if res.get("error_code"):
        raise RuntimeError(f"yandex stt error: {res}")
    text = res.get("result", "").strip()
    log(f"stt <- {time.time() - started:.1f}s: {text!r}")
    return text


def transcribe(audio: bytes, mime: str = "audio/ogg") -> str:
    if STT_PROVIDER == "yandex":
        return yandex_transcribe(audio, mime)
    if STT_PROVIDER == "gemini":
        return gemini_transcribe(audio, mime)
    return openai_transcribe(audio, mime)
    text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
    log(f"gemini <- {time.time() - started:.1f}s: {text!r}")
    return text


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_chats() -> dict:
    return _load_json(TG_CHATS_FILE)


def _save_chat(task_stem: str, chat_id: int) -> None:
    chats = _load_chats()
    chats[task_stem] = chat_id
    TG_CHATS_FILE.write_text(json.dumps(chats))


def enqueue_task(text: str, chat_id: int) -> str:
    name = f"tg-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 100000}.txt"
    (INBOX / name).write_text(text)
    _save_chat(Path(name).stem, chat_id)
    log(f"task file {INBOX / name} written, chat_id={chat_id} remembered")
    return name


def _save_pending(entry: dict) -> str:
    pending = _load_json(PENDING_FILE)
    pid = str(entry.get("id") or int(time.time() * 1000))
    pending[pid] = entry
    PENDING_FILE.write_text(json.dumps(pending))
    return pid


def _pop_pending(pid: str) -> dict | None:
    pending = _load_json(PENDING_FILE)
    entry = pending.pop(pid, None)
    PENDING_FILE.write_text(json.dumps(pending))
    return entry


def _pending_for_chat(chat_id) -> tuple:
    """Newest open pending entry for this chat, or (None, None)."""
    found = (None, None)
    for pid, e in _load_json(PENDING_FILE).items():
        if str(e.get("chat_id")) == str(chat_id):
            found = (pid, e)
    return found


def _update_pending(pid: str, entry: dict) -> None:
    pending = _load_json(PENDING_FILE)
    pending[pid] = entry
    PENDING_FILE.write_text(json.dumps(pending))


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
    try:
        name = PROJECT_FILE.read_text().strip()
    except Exception:
        name = ""
    if name and (PROJECTS_ROOT / name).is_dir():
        return name, PROJECTS_ROOT / name
    return None, PROJECTS_ROOT


def set_project(name: str) -> None:
    PROJECT_FILE.write_text(name)
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


def current_model() -> str:
    """Model for the next task: telegram override wins over DEVIN_MODEL env."""
    try:
        m = MODEL_FILE.read_text().strip()
        if m:
            return m
    except Exception:
        pass
    return os.environ.get("DEVIN_MODEL", "swe")


def set_model(name: str) -> None:
    MODEL_FILE.write_text(name.strip())
    log(f"model switched to {name}")


def devin_models() -> list:
    """Model slugs available to the account, via `devin models list`."""
    try:
        res = subprocess.run(
            ["devin", "models", "list", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(res.stdout)
    except Exception as e:
        log(f"devin models list failed: {e}")
        return []
    found = []

    def walk(x) -> None:
        if isinstance(x, dict):
            for k in ("id", "slug", "model", "name"):
                if isinstance(x.get(k), str):
                    found.append(x[k])
                    return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            found.append(x)

    walk(data)
    models = []
    for m in found:
        if m and m not in models:
            models.append(m)
    return models


def status_text() -> str:
    uptime = int(time.time() - _started_at)
    h, m = uptime // 3600, uptime % 3600 // 60
    queue = len(list(INBOX.glob("*.txt")))
    return (f"uptime: {h}h {m}m\n"
            f"project: {project_label()}\n"
            f"model: {current_model()}\n"
            f"queue: {queue} task(s)\n"
            f"current: {STATE['current_task'] or '-'}\n"
            f"last: {STATE['last_task']} ({STATE['last_status']})\n"
            f"done: {STATE['tasks_done']}")


def send_models(chat_id, msg_id=None) -> None:
    models = devin_models()
    cur = current_model()
    if not models:
        tg_send(chat_id,
                f"Текущая модель: {cur}\nСписок недоступен — "
                "`devin models list` не ответил. Задай явно: /model <name>")
        return
    kb = [[{"text": ("✅ " if m == cur else "") + m,
            "callback_data": f"model:{m}"}] for m in models[:15]]
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


def send_task_stats(chat_id, since: float) -> None:
    s = session_stats(since) or {}
    lines = [
        f"model: {s.get('model') or current_model()}",
        f"tokens: prompt={s.get('prompt_tokens', '?')} "
        f"(cached={s.get('cached_tokens', '?')}), "
        f"completion={s.get('completion_tokens', '?')}",
        f"steps: {s.get('steps', '?')}, session: {s.get('session') or '-'}",
    ]
    tg_send(chat_id, "📊 Статистика задачи:\n" + "\n".join(lines))


def _git(workdir, *args) -> tuple:
    """git in workdir, direct connection (proxy vars stripped)."""
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
    res = subprocess.run(["git", "-C", str(workdir), *args],
                         capture_output=True, text=True, timeout=120, env=env)
    return res.returncode, (res.stdout + res.stderr).strip()


def _save_commit_pending(stem: str, chat_id, workdir) -> None:
    pending = _load_json(COMMITS_FILE)
    pending[stem] = {"chat_id": chat_id, "workdir": str(workdir)}
    COMMITS_FILE.write_text(json.dumps(pending))


def _pop_commit_pending(stem: str) -> dict | None:
    pending = _load_json(COMMITS_FILE)
    entry = pending.pop(stem, None)
    COMMITS_FILE.write_text(json.dumps(pending))
    return entry


def offer_commit(task: Path, chat_id, workdir) -> None:
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
    _save_commit_pending(task.stem, chat_id, workdir)
    tg_api("sendMessage", chat_id=chat_id,
           text=f"В репо: {dirty} незакоммиченных, {unpushed} незапушенных. Что делаем?",
           reply_markup={"inline_keyboard": [
               [{"text": label, "callback_data": f"commit:{task.stem}"}],
               [{"text": "⏭ Пропустить", "callback_data": f"skip:{task.stem}"}],
           ]})
    log(f"commit offer for {task.stem}: dirty={dirty} unpushed={unpushed}")


def do_commit(stem: str, workdir) -> str:
    """git add -A && commit && push; or push only when the tree is clean."""
    _, st = _git(workdir, "status", "--porcelain")
    out = []
    if st:
        msg = f"task: {stem}"
        try:
            first = (DONE / f"{stem}.txt").read_text().strip().splitlines()[0]
            msg = f"task: {first[:70]}"
        except Exception:
            pass
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
                   {"text": "📊 Статус", "callback_data": "cmd:status"},
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
        centry = _pop_commit_pending(pid)
        if not centry:
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Уже обработано")
            return
        cworkdir = (centry.get("workdir") if isinstance(centry, dict)
                    else WORKDIR)
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
            text = transcribe(tg_download(voice["file_id"]))
            pid, entry = _pending_for_chat(chat_id)
            if pid:
                _add_to_pending(chat_id, pid, entry, text)
                return
            pid = str(upd.get("update_id") or int(time.time() * 1000))
            res = tg_api("sendMessage", chat_id=chat_id,
                         text=f"Проект: {project_label()}\n\nРаспознано:\n{text}",
                         reply_markup=_confirm_keyboard(pid))
            _save_pending({"chat_id": chat_id, "text": text,
                           "project": project_label(),
                           "message_id": res["result"]["message_id"],
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
    chat_id = _load_chats().get(task_stem)
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


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        uptime = int(time.time() - _started_at)
        h, m, s = uptime // 3600, uptime % 3600 // 60, uptime % 60
        queue = len(list(INBOX.glob("*.txt")))
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

    def do_POST(self) -> None:
        # any POST path is treated as the telegram webhook — robust against
        # whatever path prefix the reverse proxy preserves
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

    def log_message(self, *args) -> None:  # keep docker logs clean
        pass


def start_web() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), StatusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"status page on :{WEB_PORT}")


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
    global _bot_proc
    for d in (INBOX, DONE, OUTBOX):
        d.mkdir(parents=True, exist_ok=True)

    ensure_repo()
    start_bot()
    register_webhook()
    register_commands()
    start_web()
    log(f"watching {INBOX} every {POLL_INTERVAL}s (timeout {TASK_TIMEOUT}s)")
    while True:
        try:
            if _bot_proc and _bot_proc.poll() is not None:
                log(f"telegram bot exited ({_bot_proc.returncode}), restarting")
                start_bot()
            task = next_task()
            if task is None:
                time.sleep(POLL_INTERVAL)
                continue
            run_task(task)
        except KeyboardInterrupt:
            log("stopping")
            if _bot_proc:
                _bot_proc.terminate()
            return 0
        except Exception as e:  # keep the watcher alive no matter what
            log(f"ERROR: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
