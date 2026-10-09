#!/usr/bin/env python3
"""Minimal Telegram bot test: sends a message every INTERVAL seconds.

A bot cannot DM a user by @username — it needs the numeric chat_id.
Either set CHAT_ID directly, or just send any message (/start) to the bot
first: the script picks up the chat_id of TG_USERNAME automatically.

Env:
    TELEGRAM_BOT_TOKEN   BotFather token (required)
    TG_USERNAME          Whose chat to message (default: kiloper)
    CHAT_ID              Skip auto-detection if you know the id
    MESSAGE_TEXT         Text to send (default: "привет")
    INTERVAL             Seconds between messages (default: 60)
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
USERNAME = os.environ.get("TG_USERNAME", "kiloper").lstrip("@")
CHAT_ID = os.environ.get("CHAT_ID") or None
TEXT = os.environ.get("MESSAGE_TEXT", "привет")
INTERVAL = int(os.environ.get("INTERVAL", "60"))

API = f"https://api.telegram.org/bot{TOKEN}"


def log(msg: str) -> None:
    # flush=True: stdout is block-buffered inside docker, or logs stay silent
    print(f"[bot] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def api(method: str, **params) -> dict:
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(f"{API}/{method}", data, timeout=40) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"{method} network error: {e.reason}")
    if not res.get("ok"):
        raise RuntimeError(f"{method} api error: {res}")
    return res


def find_chat_id() -> int:
    """Long-poll getUpdates until TG_USERNAME writes to the bot."""
    log(f"waiting for a message from @{USERNAME} — write /start to the bot")
    offset = 0
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=30)
        except Exception as e:
            log(f"getUpdates error: {e}")
            time.sleep(3)
            continue
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            sender = (msg.get("from") or {}).get("username", "?")
            text = (msg.get("text") or msg.get("caption") or "<non-text>")[:60]
            log(f"update from @{sender}: {text}")
            if sender.lower() == USERNAME.lower() and msg.get("chat"):
                return msg["chat"]["id"]


def main() -> None:
    if not TOKEN:
        log("TELEGRAM_BOT_TOKEN is not set — exiting")
        return

    # connectivity + token sanity check up front
    try:
        me = api("getMe")["result"]
        log(f"connected as @{me.get('username')} (id={me.get('id')})")
    except Exception as e:
        log(f"getMe failed (bad token or no network?): {e}")
        raise

    chat_id = int(CHAT_ID) if CHAT_ID else find_chat_id()
    log(f"chat_id={chat_id} — sending every {INTERVAL}s")
    while True:
        try:
            res = api("sendMessage", chat_id=chat_id, text=TEXT)
            log(f"sent {TEXT!r} -> message_id={res['result']['message_id']}")
        except Exception as e:
            log(f"sendMessage error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
