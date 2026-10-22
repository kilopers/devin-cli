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


# --- MCP servers (user scope) -------------------------------------------
# Конфиг Devin CLI: ~/.config/devin/mcp_config.json, секция mcpServers.
# Диалог «MCP серверы» в веб-панели читает/пишет этот файл напрямую.

_MCP_CFG = os.path.expanduser("~/.config/devin/mcp_config.json")


def _mcp_cfg_read() -> dict:
    try:
        with open(_MCP_CFG, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _mcp_cfg_write(cfg: dict) -> None:
    os.makedirs(os.path.dirname(_MCP_CFG), exist_ok=True)
    tmp = _MCP_CFG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _MCP_CFG)


def _mcp_apply(proj: str):
    """Подмешать проектные MCP-серверы (pj:<proj>.mcp, JSON-объект
    name → def, формат как в mcp_config.json) в mcpServers на время
    задачи. Возвращает restore(), откатывающий конфиг."""
    if not proj:
        return lambda: None
    try:
        extra = json.loads(pj_get(proj, "mcp") or "{}")
    except ValueError:
        log(f"{proj}: pj.mcp — битый JSON, пропускаю")
        extra = {}
    if not isinstance(extra, dict) or not extra:
        return lambda: None
    cfg = _mcp_cfg_read()
    backup = json.dumps(cfg, ensure_ascii=False)
    srvs = cfg.setdefault("mcpServers", {})
    srvs.update(extra)
    _mcp_cfg_write(cfg)
    log(f"{proj}: применено {len(extra)} проектных MCP-сервер(а)")

    def restore():
        try:
            _mcp_cfg_write(json.loads(backup))
        except Exception as e:
            log(f"{proj}: не смог откатить mcp_config: {e}")
    return restore


def _kv_dict(v):
    """env/headers из формы: dict либо мультистрока 'KEY=VALUE'."""
    if isinstance(v, dict):
        return {str(k): str(val) for k, val in v.items() if str(k).strip()}
    out = {}
    for line in str(v or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, val = line.split("=", 1)
            out[k.strip()] = val
    return out


@app.get("/api/mcp/servers")
@login_required
def _api_mcp_list():
    cfg = _mcp_cfg_read()
    out = []
    for name, s in sorted((cfg.get("mcpServers") or {}).items()):
        out.append({"name": name,
                    "kind": "http" if s.get("url") else "stdio",
                    "command": s.get("command") or "",
                    "args": " ".join(s.get("args") or []),
                    "url": s.get("url") or "",
                    "transport": s.get("transport") or "",
                    "env": s.get("env") or {},
                    "headers": s.get("headers") or {},
                    "disabled": bool(s.get("disabled"))})
    return jsonify({"ok": True, "servers": out, "file": _MCP_CFG})


@app.post("/api/mcp/servers")
@login_required
def _api_mcp_save():
    body = _req_json()
    action = (body.get("action") or "save").strip()
    name = (body.get("name") or "").strip()
    cfg = _mcp_cfg_read()
    srvs = cfg.setdefault("mcpServers", {})

    if action == "delete":
        if srvs.pop(name, None) is not None:
            _mcp_cfg_write(cfg)
        return jsonify({"ok": True})

    if action == "toggle":
        s = srvs.get(name)
        if s is None:
            return jsonify({"ok": False, "error": "нет такого сервера"}), 404
        s["disabled"] = not bool(s.get("disabled"))
        _mcp_cfg_write(cfg)
        return jsonify({"ok": True, "disabled": s["disabled"]})

    # action == "save"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return jsonify({"ok": False,
                        "error": "имя: только a-z, 0-9, _ и -"}), 400
    s = body.get("server") or {}
    entry = {}
    if s.get("kind") == "http":
        url = (s.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return jsonify({"ok": False,
                            "error": "url должен начинаться с http(s)://"}), 400
        entry["url"] = url
        if s.get("transport") in ("http", "sse"):
            entry["transport"] = s["transport"]
        hdrs = _kv_dict(s.get("headers"))
        if hdrs:
            entry["headers"] = hdrs
    else:
        cmd = (s.get("command") or "").strip()
        if not cmd:
            return jsonify({"ok": False, "error": "укажи command"}), 400
        entry["command"] = cmd
        args = (s.get("args") or "").strip()
        if args:
            entry["args"] = shlex.split(args)
        env = _kv_dict(s.get("env"))
        if env:
            entry["env"] = env
    if s.get("disabled"):
        entry["disabled"] = True
    srvs[name] = entry
    _mcp_cfg_write(cfg)
    log(f"web saved mcp server {name}")
    return jsonify({"ok": True, "name": name})


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
    mode = body.get("mode") if body.get("mode") in ("ask", "code") else None
    name = enqueue_task(text, project=project, prefix="web",
                        override_mode=mode)
    o = {}
    if (body.get("model") or "").strip():
        o["model"] = body["model"].strip()[:60]
    if body.get("auto_commit") in ("0", "1"):
        o["ac"] = body["auto_commit"]
    if mode:
        o["mode"] = mode
    if o:
        stem = name.removesuffix(".txt")
        kv_set(f"opts:{stem}", json.dumps(o))
        if o.get("model"):  # карточка показывает реальную модель задачи
            db_exec("UPDATE tasks SET model=%s WHERE stem=%s",
                    (o["model"], stem))
    return jsonify({"ok": True, "name": name}), 201


@app.get("/")
@app.get("/index.html")
@login_required
def _index():
    return render_template("webui.html")




@app.post("/api/extkey")
@login_required
def _api_extkey():
    """Управление ключом внешнего API текущего юзера:
    {"action":"gen"|"revoke"}. Ключ хранится us:<uid>.ext_key,
    обратный индекс kv ext_key:<key> -> uid."""
    u = _current_user()
    act = (_req_json().get("action") or "").strip()
    old = us_get(u, "ext_key")
    if act == "revoke":
        if old:
            us_set(u, "ext_key", "")
            kv_set(f"ext_key:{old}", "")
        return jsonify({"ok": True, "key": ""})
    if act != "gen":
        return jsonify({"ok": False, "error": "action: gen|revoke"}), 400
    key = "ext_" + secrets.token_urlsafe(24)
    if old:
        kv_set(f"ext_key:{old}", "")
    us_set(u, "ext_key", key)
    kv_set(f"ext_key:{key}", u)
    return jsonify({"ok": True, "key": key})


@app.get("/api/extkey")
@login_required
def _api_extkey_get():
    """Есть ли у юзера ext-ключ (маской)."""
    k = us_get(_current_user(), "ext_key")
    return jsonify({"ok": True, "set": bool(k),
                    "key": (k[:7] + "…" + k[-4:]) if k else ""})


def _ext_auth() -> str:
    """Аутентификация внешнего API: Bearer/X-Api-Key -> uid юзера."""
    k = request.headers.get("X-Api-Key", "")
    ah = request.headers.get("Authorization", "")
    if not k and ah.startswith("Bearer "):
        k = ah[7:]
    return kv_get(f"ext_key:{k.strip()}") if k else ""


@app.post("/api/ext/task")
def _api_ext_task():
    """Внешняя постановка задачи Devin по ключу (см. «Внешний API» в
    README). Обезличенная сессия в каталоге tasks/ext/<label>; сессия
    продолжается между задачами одного label."""
    uid = _ext_auth()
    if not uid:
        return jsonify({"ok": False, "error": "неверный api-ключ"}), 401
    b = _req_json()
    text = (b.get("task") or b.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "пустой task"}), 400
    if len(text) > 20000:
        return jsonify({"ok": False, "error": "task слишком длинный"}), 400
    label = re.sub(r"[^a-z0-9_-]+", "-",
                   (b.get("project") or "").lower()).strip("-") or "default"
    mode = b.get("mode") if b.get("mode") in ("ask", "code") else "ask"
    hook = (b.get("hook") or "").strip()
    if hook and not hook.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "hook: только http(s)"}), 400
    instr_extra = (b.get("instructions") or "").strip()
    stem = (f"ext-{label}-{re.sub(r'[^a-z0-9_-]+', '-', uid.lower())}-"
            f"{time.strftime('%m%d-%H%M%S')}")
    instr = _instr_block(uid, None)
    if instr_extra:
        instr += "\n\n## Инструкции вызова\n" + instr_extra
    _insert_task(stem, text, "ext", None, None, time.time(),
                 reply_mode=mode, user=uid, instr=instr)
    kv_set(f"ext:{stem}", json.dumps({"label": label, "hook": hook},
                                     ensure_ascii=False))
    name = _task_name(stem)
    log(f"ext task {name} queued, label={label}, user={uid}, mode={mode}")
    return jsonify({"ok": True, "name": name, "project": label}), 201


@app.post("/")
@app.post("/<path:_any>")
def _webhook(_any: str = ""):
    # any POST to a non-/api path is the telegram webhook — robust against
    # whatever path prefix the reverse proxy preserves. Юзерские боты приходят
    # на <TG_WEBHOOK_URL>/bot/<uid>; токен бота — из настроек этого юзера.
    if re.fullmatch(r"(?:.*/)?deploy/?", _any or ""):
        return _deploy_hook()
    uid = None
    token = TG_TOKEN
    hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    m = re.search(r"(?:^|/)bot/([A-Za-z0-9_-]+)/?$", _any)
    if m:
        uid = m.group(1)
        token = us_get(uid, "telegram.bot_token")
        if not token:
            log(f"POST /{_any}: no bot token for {uid}, ignored")
            return "", 200
    elif hdr:
        # прокси мог срезать /bot/<uid> — находим бота по secret_token
        for u, tok in _user_bots().items():
            if hdr == _user_secret(tok):
                uid, token = u, tok
                break
    if uid:
        expected = _user_secret(token)
    elif TG_WEBHOOK_SECRET:
        expected = _bot_secret(token)
    else:
        expected = ""
    if expected and hdr != expected:
        log(f"POST /{_any}: bad webhook secret — 403")
        return "", 403
    body = request.get_data()
    try:
        upd = json.loads(body)
    except ValueError:
        log(f"POST /{_any}: bad JSON ({len(body)} bytes), ignored")
        return "", 200
    log(f"POST /{_any}: update_id={upd.get('update_id')}, "
        f"{len(body)} bytes" + (f", bot of {uid}" if uid else ""))
    threading.Thread(target=_handle_ctx, args=(upd, uid, token),
                     daemon=True).start()
    return "", 200


def _deploy_hook():
    """POST /deploy (Bearer DEPLOY_TOKEN) → POST watchtower /v1/update."""
    if not DEPLOY_TOKEN:
        return "", 404
    if request.headers.get("Authorization") != f"Bearer {DEPLOY_TOKEN}":
        log(f"POST /deploy: bad token — 403")
        return "", 403
    # в фоне: watchtower пересоздаст ЭТОТ контейнер — ответить надо до смерти
    threading.Thread(target=_wt_update, daemon=True).start()
    return jsonify({"ok": True, "update": "triggered"}), 202


def _wt_update() -> None:
    """Проброс в watchtower /v1/update с ретраями (он может быть занят
    пересозданием другого контейнера или самого себя)."""
    # пауза — ответ 202 должен уйти до того, как watchtower начнёт
    # пересоздавать этот контейнер, иначе клиент видит 502
    time.sleep(4)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(1, 4):
        try:
            r = urllib.request.Request(
                f"{WATCHTOWER_API_URL}/v1/update", data=b"", method="POST",
                headers={"Authorization": f"Bearer {DEPLOY_TOKEN}"})
            with opener.open(r, timeout=60):
                pass
            log("deploy hook: watchtower update triggered")
            return
        except Exception as e:
            log(f"deploy hook attempt {attempt}: {e}")
            time.sleep(5)


def _handle_ctx(upd: dict, uid: str | None, token: str) -> None:
    """Контекст треда вебхука: токен бота в TLS (все tg_* ответы пойдут
    от него) + привязка чата к юзеру/боту в kv для асинхронных ответов."""
    _tg_tls.token = token or ""
    handle_update(upd, actor=uid)


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
