# --- telegram / gemini -------------------------------------------------------

_tg_tls = threading.local()  # токен бота, обслуживающего текущий апдейт


def _chat_token(chat_id) -> str:
    """Токен бота для чата: per-user бот из карты tg_bot:<chat_id>, иначе
    токен из TLS (тред вебхука), иначе основной env-бот."""
    t = getattr(_tg_tls, "token", "")
    if not t and chat_id:
        t = kv_get(f"tg_bot:{chat_id}")
    return t or TG_TOKEN


def tg_api(method: str, **params) -> dict:
    token = params.pop("_token", None) or _chat_token(params.get("chat_id"))
    shown = {k: ("***" if k == "secret_token" else str(v)[:120])
             for k, v in params.items()}
    log(f"tg -> {method} {shown}")
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
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


def tg_send(chat_id: int, text: str, token: str | None = None) -> None:
    """sendMessage, splitting into <=4000-char chunks, max 5 messages."""
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)][:5]
    if len(text) > 20000:
        chunks[-1] += "\n…[truncated]"
    log(f"reply to chat {chat_id}: {len(chunks)} message(s), {len(text)} chars")
    for chunk in chunks:
        try:
            tg_api("sendMessage", chat_id=chat_id, text=chunk,
                   _token=token)
        except Exception as e:
            log(f"telegram sendMessage error: {e}")


def tg_download(file_id: str) -> bytes:
    file_path = tg_api("getFile", file_id=file_id)["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{_chat_token(None)}/{file_path}"
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


def yandex_transcribe_sync(audio: bytes, mime: str = "audio/ogg",
                           rate: int = 48000, user=None) -> str:
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
                      on_status=None, user: str | None = None) -> str:
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
    op = json.loads(_yandex_request("/stt/v3/recognizeFileAsync", body, user=user))
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
                f"/stt/v3/getRecognition?operationId={op_id}",
                user=user)
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
            return _stt_dispatch(p, wav, "audio/wav", user=u)
        try:
            if duration < 28:
                return yandex_transcribe_sync(pcm, "audio/L16", rate,
                                              user=u)
            _status(f"Запись {duration:.0f}с — длинная, ушла в асинхронное "
                    "распознавание Яндекса")
            return yandex_transcribe(_wav_wrap(pcm, rate), "audio/wav",
                                     on_status=_status, user=u)
        finally:
            STATE["stt"] = None

    return _stt_run(chain, _try, _status)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def enqueue_task(text: str, chat_id: int | None = None,
                 project: str | None = None, prefix: str = "tg",
                 override_mode: str | None = None) -> str:
    source = {"tg": "telegram", "web": "web"}.get(prefix, prefix)
    scope = source if source in ("web", "telegram") else ""
    proj = project or (current_project(scope)[0] if multi_mode() else None)
    pname = re.sub(r"[^a-z0-9_-]+", "-",
                   (proj or "job").lower()).strip("-") or "job"
    if scope == "web":
        author = _current_user()
    elif chat_id:
        author = kv_get(f"tg_user:{chat_id}") or WEB_ADMIN_USER
    else:
        author = WEB_ADMIN_USER
    aname = re.sub(r"[^a-z0-9_-]+", "-",
                   author.lower()).strip("-") or "user"
    stem = f"{prefix}-{pname}-{aname}-{time.strftime('%m%d-%H%M%S')}"
    model = pj_get(proj, "model") if proj else ""
    model = model or current_model(scope)
    if scope == "web":
        rmode = pj_get(proj, "reply_mode") if proj else ""
        rmode = rmode or reply_mode(scope)
    else:
        # телеграм: /mode — явный выбор юзера, важнее дефолта проекта
        rmode = us_get(author, "reply_mode") or             (pj_get(proj, "reply_mode") if proj else "")             or reply_mode(scope)
    if override_mode in ("ask", "code"):
        rmode = override_mode  # кнопка «Кодировать»/«Спросить» важнее настроек
    bot = getattr(_tg_tls, "token", "") or \
        (kv_get(f"tg_bot:{chat_id}") if chat_id else "")
    _insert_task(stem, text, source, proj, chat_id, time.time(), model,
                 rmode, author, bot, instr=_instr_block(author, proj))
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
    return f"{head}{entry['text']}"


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
    # «Кодировать» — задача в code-режиме, «Спросить» — ask-режим,
    # «Отмена» — выбросить. ok: оставлен для совместимости со старыми
    # сообщениями (дефолтный режим проекта/юзера).
    return {"inline_keyboard": [[
        {"text": "⚙️ Кодировать", "callback_data": f"cd:{pid}"},
        {"text": "❓ Спросить", "callback_data": f"ask:{pid}"},
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
    if scope == "web":
        name = kv_get(f"project_web:{_current_user()}")             or kv_get("project_web") or kv_get("project")
    else:
        name = kv_get("project")
    if name and (PROJECTS_ROOT / name).is_dir():
        return name, PROJECTS_ROOT / name
    return None, PROJECTS_ROOT


def set_project(name: str, scope: str = "telegram") -> None:
    kv_set(f"project_web:{_current_user()}" if scope == "web"
           else "project", name)
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
    actor = kv_get(f"tg_user:{chat_id}") or WEB_ADMIN_USER
    cur = us_get(actor, "reply_mode") or reply_mode()
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


def _git_clean_locks(workdir, min_age: int = 60) -> int:
    """Удаляет протухшие *.lock в .git (упавший/убитый git оставляет
    index.lock — без него любая git-операция падает). Свежие локи
    (< min_age сек) не трогаем — вдруг git реально работает."""
    gd = Path(workdir) / ".git"
    n = 0
    try:
        for f in gd.glob("*.lock") + gd.glob("**/*.lock"):
            try:
                if time.time() - f.stat().st_mtime > min_age:
                    f.unlink()
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def _git(workdir, *args) -> tuple:
    """git in workdir, direct connection (proxy vars stripped).
    Протухшие *.lock чистим и повторяем один раз."""
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}

    def run():
        res = subprocess.run(["git", "-C", str(workdir), *args],
                             capture_output=True, text=True,
                             timeout=120, env=env)
        return res.returncode, (res.stdout + res.stderr).strip()

    rc, out = run()
    if rc != 0 and "index.lock" in out or (rc != 0 and ".lock" in out):
        if _git_clean_locks(workdir):
            log(f"removed stale git lock(s) in {workdir}; retrying")
            rc, out = run()
    return rc, out


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
        # подпись коммита — git.name/git.email автора задачи
        tu = (row or {}).get("user") or WEB_ADMIN_USER
        gname = uset("git.name", tu, "GIT_USER_NAME", "") or "webdev"
        gemail = uset("git.email", tu, "GIT_USER_EMAIL", "") \
            or "webdev@local"
        for args in (("add", "-A"),
                     ("-c", f"user.name={gname}",
                      "-c", f"user.email={gemail}", "commit", "-m", msg)):
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
        n = kill_task()
        if n:
            tg_send(chat_id,
                    f"⛔ Остановлено задач: {n} — воркеры возьмут "
                    "следующие из очереди.")
        else:
            tg_send(chat_id, "Сейчас ничего не выполняется.")
    elif cmd == "mode":
        actor = kv_get(f"tg_user:{chat_id}") or WEB_ADMIN_USER
        if arg.strip() in ("ask", "code"):
            us_set(actor, "reply_mode", arg.strip())
            log(f"reply mode -> {arg.strip()} (user {actor})")
            tg_send(chat_id, f"Режим ответа: {arg.strip()}.")
        else:
            send_mode_menu(chat_id)
    elif cmd == "status":
        tg_send(chat_id, status_text())
    else:
        tg_send(chat_id,
                "Команды: /menu, /models, /model <name>, /mode, /status.\n"
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
        n = kill_task()
        if n:
            tg_api("answerCallbackQuery", callback_query_id=cb_id,
                   text="Остановлено")
            tg_send(chat_id,
                    f"⛔ Остановлено задач: {n} — воркеры возьмут "
                    "следующие из очереди.")
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
        actor = kv_get(f"tg_user:{chat_id}") or WEB_ADMIN_USER
        us_set(actor, "reply_mode", pid)
        log(f"reply mode -> {pid} (user {actor})")
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

    if action in ("ok", "cd", "ask"):
        rmode = {"cd": "code", "ask": "ask"}.get(action)
        name = enqueue_task(entry["text"], chat_id, override_mode=rmode)
        tag = {"cd": " — режим кода", "ask": " — вопрос"}.get(action, "")
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"{entry['text']}\n\n✅ Задача {name} в очереди{tag}.",
               reply_markup={"inline_keyboard": []})
    else:
        tg_api("editMessageText", chat_id=chat_id, message_id=msg_id,
               text=f"{entry['text']}\n\n❌ Отменено.",
               reply_markup={"inline_keyboard": []})
    tg_api("answerCallbackQuery", callback_query_id=cb_id)


def handle_update(upd: dict, actor: str | None = None) -> None:
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
    actor = actor or WEB_ADMIN_USER
    kv_set(f"tg_user:{chat_id}", actor)
    kv_set(f"tg_bot:{chat_id}", _tg_tls.token or TG_TOKEN)
    try:
        if voice := msg.get("voice"):
            log(f"voice from @{sender} chat={chat_id}, {voice.get('duration', '?')}s")
            chain = _stt_chain(actor)
            if not any(_stt_ready(p, actor) for p in chain):
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
                              on_status=_st, duration=dur, user=actor)
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
            pid = str(upd.get("update_id") or int(time.time() * 1000))
            res = tg_api("sendMessage", chat_id=chat_id,
                         text=_pending_text(
                             {"text": text, "project": project_label()}),
                         reply_markup=_confirm_keyboard(pid))
            _save_pending({"chat_id": chat_id, "text": text,
                           "project": project_label(),
                           "message_id": res["result"]["message_id"],
                           "id": pid})
            log(f"pending confirm {pid} -> chat {chat_id} (text)")
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
    tg_send(chat_id, response_text, token=row.get("bot") or None)


_BOT_COMMANDS = [
    {"command": "menu", "description": "меню бота"},
    {"command": "projects", "description": "выбор проекта"},
    {"command": "models", "description": "выбор модели"},
    {"command": "session", "description": "режим сессий"},
    {"command": "stop", "description": "убить текущую задачу"},
    {"command": "mode", "description": "код или ответ на вопрос"},
    {"command": "status", "description": "статус воркера"},
]


def _bot_secret(token: str) -> str:
    """Secret-token вебхука основного бота: env-секрет или хэш токена."""
    return TG_WEBHOOK_SECRET or hashlib.sha256(
        ("wh:" + token).encode()).hexdigest()[:24]


def _user_secret(token: str) -> str:
    """Secret-token вебхука юзер-бота — ВСЕГДА хэш его токена. Прокси может
    резать путь /bot/<uid>, поэтому маршрутизация идёт по secret_token."""
    return hashlib.sha256(("wh:" + token).encode()).hexdigest()[:24]


def _user_bots() -> dict:
    """{uid: token} — per-user TG-боты из настроек, кроме дубля основного."""
    out = {}
    try:
        users = [WEB_ADMIN_USER] + [r["username"] for r in db_query(
            "SELECT username FROM users")]
    except Exception:
        users = [WEB_ADMIN_USER]
    for u in users:
        tok = us_get(u, "telegram.bot_token")
        if tok and tok != TG_TOKEN:
            out[u] = tok
    return out


def register_bot_webhook(uid: str, token: str) -> bool:
    """setWebhook + setMyCommands для бота юзера на /bot/<uid>."""
    if not TG_WEBHOOK_URL:
        log("no TELEGRAM_WEBHOOK_URL — user bot webhooks skipped")
        return False
    try:
        tg_api("setWebhook", url=f"{TG_WEBHOOK_URL.rstrip('/')}/bot/{uid}",
               secret_token=_user_secret(token), _token=token)
        tg_api("setMyCommands", commands=_BOT_COMMANDS, _token=token)
        log(f"user bot webhook registered: {TG_WEBHOOK_URL}/bot/{uid}")
        return True
    except Exception as e:
        log(f"user bot webhook for {uid} failed: {e}")
        return False


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
    for uid, tok in _user_bots().items():
        register_bot_webhook(uid, tok)


def register_commands() -> None:
    """Native telegram Menu button next to the input field."""
    if not TG_TOKEN:
        return
    try:
        tg_api("setMyCommands", commands=_BOT_COMMANDS)
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
