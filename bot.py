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
import urllib.parse
import urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
USERNAME = os.environ.get("TG_USERNAME", "kiloper").lstrip("@")
CHAT_ID = os.environ.get("CHAT_ID")
TEXT = os.environ.get("MESSAGE_TEXT", "привет")
INTERVAL = int(os.environ.get("INTERVAL", "60"))

API = f"https://api.telegram.org/bot{TOKEN}"


def api(method: str, **params) -> dict:
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"{API}/{method}", data, timeout=40) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(f"{method} failed: {res}")
    return res


def find_chat_id() -> int:
    """Long-poll getUpdates until TG_USERNAME writes to the bot."""
    print(f"waiting for a message from @{USERNAME} — write /start to the bot")
    offset = 0
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=30)
        except Exception as e:
            print(f"getUpdates error: {e}")
            time.sleep(3)
            continue
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            sender = (msg.get("from") or {}).get("username", "")
            if sender.lower() == USERNAME.lower() and msg.get("chat"):
                return msg["chat"]["id"]


def main() -> None:
    chat_id = int(CHAT_ID) if CHAT_ID else find_chat_id()
    print(f"chat_id={chat_id} — sending every {INTERVAL}s, Ctrl+C to stop")
    while True:
        try:
            api("sendMessage", chat_id=chat_id, text=TEXT)
            print(f"sent: {TEXT!r}")
        except Exception as e:
            print(f"sendMessage error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
