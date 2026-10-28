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
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
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
ATTACH_DIR = TASKS_DIR / "attach"   # файлы, прикреплённые к задачам
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
# Деплой-хук: POST /<DEPLOY_PATH> с Bearer <DEPLOY_TOKEN> → проброс в HTTP
# API watchtower внутри compose-сети (он наружу не торчит).
DEPLOY_TOKEN = os.environ.get(
    "DEPLOY_TOKEN") or os.environ.get("WATCHTOWER_HTTP_API_TOKEN", "")
WATCHTOWER_API_URL = os.environ.get(
    "WATCHTOWER_API_URL", "http://watchtower:8080")
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
# токен для внутренних эндпоинтов (задачи наследуют env — агент
# управляет инструкциями только через API, не прямыми запросами к базе)
INTERNAL_TOKEN = os.environ.setdefault(
    "INTERNAL_TOKEN", secrets.token_hex(24))

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
# параллельные воркеры: запущенные devin-task по stem, снимок для
# kill_task/stop. Задачи одного проекта сериализуются через
# RUNNING_PROJS, разных — идут параллельно (WORKER_THREADS штук).
_task_procs: dict = {}
_procs_lock = threading.Lock()
RUNNING_PROJS: set = set()
RUNNING_STEMS: set = set()
_run_lock = threading.Lock()
WORKER_THREADS = max(1, min(int(os.environ.get("WORKER_THREADS", "3")
                                 or 1), 8))
_mihomo_proc: subprocess.Popen | None = None
_started_at = time.time()

STATE = {
    "current_task": None,
    "running_tasks": [],
    "last_task": "-",
    "last_status": "-",
    "tasks_done": 0,
    "stt": None,   # live web-STT status text, shown in the UI
}


def log(msg: str) -> None:
    print(f"[watcher] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


# --- сборка из частей --------------------------------------------------------
# Код разложен по файлам watcher_parts/NN_*.py по логике; части исполняются
# в общем пространстве имён этого модуля (общие глобалы/global работают как
# раньше), порядок = порядок номеров.
PARTS_DIR = Path(os.environ.get(
    "WATCHER_PARTS_DIR", str(Path(__file__).resolve().parent / "watcher_parts")))
for _part in sorted(PARTS_DIR.glob("[0-9][0-9]_*.py")):
    exec(compile(_part.read_text(encoding="utf-8"), str(_part), "exec"),
         globals())


if __name__ == "__main__":
    sys.exit(main())
