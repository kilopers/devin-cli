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

import os
import subprocess
import sys
import time
from pathlib import Path

TASKS_DIR = Path(os.environ.get("TASKS_DIR", "/tasks"))
INBOX = TASKS_DIR / "inbox"
DONE = TASKS_DIR / "done"
OUTBOX = TASKS_DIR / "outbox"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "7200"))  # 2h
DEVIN_TASK = os.environ.get("DEVIN_TASK_BIN", "/usr/local/bin/devin-task")
BOT_SCRIPT = os.environ.get("BOT_SCRIPT", "/app/bot.py")

_bot_proc: subprocess.Popen | None = None


def log(msg: str) -> None:
    print(f"[watcher] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def next_task() -> Path | None:
    tasks = sorted(INBOX.glob("*.txt"), key=lambda p: p.stat().st_mtime)
    return tasks[0] if tasks else None


def run_task(task: Path) -> None:
    log(f"processing {task.name}")
    processing = task.with_name(task.name + ".processing")
    task.rename(processing)

    env = dict(os.environ, DEVIN_TASK_FILE=str(processing))
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
    log(f"done {task.name} -> outbox/{response.name} ({status})")


def ensure_repo() -> None:
    """Clone GIT_REPO_URL into the workspace if it is not a git repo yet.

    devin-task does the same check before every task, but doing it here too
    means auth/URL problems surface at container start, not on the first task.
    """
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
    res = subprocess.run(args)
    if res.returncode != 0:
        log(f"clone failed (exit {res.returncode}) — check GIT_REPO_URL and git credentials; "
            "devin-task will retry before each task")
    else:
        log("clone finished")


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
