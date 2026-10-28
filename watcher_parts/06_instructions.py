# --- инструкции: внутренний API для агентов + пользовательский API ----

def _internal_auth() -> bool:
    """Эндпоинты агентов — только localhost + токен из env задачи."""
    return request.remote_addr in ("127.0.0.1", "::1") and \
        request.headers.get("X-Internal-Token") == INTERNAL_TOKEN


def _instr_rows(user: str, project: str | None = None) -> list:
    """Системная + общая юзера + custom с флагом attached к проекту."""
    rows = db_query(
        "SELECT i.id, i.kind, i.name, i.body, i.user,"
        "       (a.instr_id IS NOT NULL) AS attached"
        " FROM instructions i"
        " LEFT JOIN instr_attach a ON a.instr_id=i.id"
        "   AND a.project=%s"
        " WHERE i.kind='system' OR i.user=%s"
        "    OR (i.kind='project' AND i.project=%s)"
        "    OR (i.kind='custom' AND a.instr_id IS NOT NULL)"
        " ORDER BY i.kind='system' DESC, i.kind='user' DESC,"
        "         i.kind='project' DESC, i.id",
        (project or "", user, project or ""))
    return [dict(r, attached=bool(r["attached"]),
                 mine=(r["user"] == user)) for r in rows]


@app.post("/api/task/tag")
def _api_task_tag():
    """«Тег задачи» — агент шлёт произвольную инфу (версия, прогресс,
    что делает), она рисуется бейджем на карточке задачи в веб-фиде.
    kv.tag:<stem>; stem — свой ($TASK_STEM) или текущая running."""
    if not _internal_auth():
        abort(403)
    b = _req_json()
    stem = (b.get("stem") or "").strip() or (
        Path(STATE["current_task"]).stem if STATE["current_task"] else "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", stem):
        return jsonify({"ok": False, "error": "bad stem"}), 400
    kv_set(f"tag:{stem}", (b.get("tag") or "")[:200])
    return jsonify({"ok": True})


@app.get("/api/internal/instr")
def _api_instr_int_list():
    if not _internal_auth():
        abort(403)
    u = request.args.get("user", "")
    p = request.args.get("project", "")
    if p:
        _ensure_project_instr(p)
    return jsonify({"ok": True, "instructions": _instr_rows(u, p)})


@app.post("/api/internal/instr")
def _api_instr_int():
    """Агент из задачи: create/update/attach/detach/delete инструкций.
    system/user — неизменяемы; own-only."""
    if not _internal_auth():
        abort(403)
    b = _req_json()
    u, act = (b.get("user") or "").strip(), (b.get("action") or "").strip()
    iid = int(b.get("id") or 0)
    p = (b.get("project") or "").strip()
    row = db_query("SELECT * FROM instructions WHERE id=%s", (iid,))
    row = row[0] if row else None
    if act == "create":
        name = (b.get("name") or "").strip()[:120]
        body = (b.get("body") or "")[:60000]
        if not u or not name:
            return jsonify({"ok": False, "error": "нужны user и name"})
        db_exec("INSERT INTO instructions(user,kind,name,body,created,"
                "updated) VALUES(%s,'custom',%s,%s,%s,%s)",
                (u, name, body, time.time(), time.time()))
        new_id = db_query("SELECT LAST_INSERT_ID() AS i")[0]["i"]
        if p:  # создал в задаче проекта → сразу подключена к нему
            db_exec("INSERT IGNORE INTO instr_attach(user,project,"
                    "instr_id) VALUES(%s,%s,%s)", (u, p, new_id))
        log(f"instr created #{new_id} '{name}' for {u}@{p}")
        return jsonify({"ok": True, "id": new_id})
    if not row:
        return jsonify({"ok": False, "error": "нет такой инструкции"}), 404
    if row["kind"] == "system" and act != "update":
        return jsonify({"ok": False,
                        "error": "системную инструкцию менять нельзя"}), 403
    if row["kind"] in ("custom", "user") and row["user"] != u:
        return jsonify({"ok": False, "error": "чужая инструкция"}), 403
    if act == "update":
        # проектную и системную можно дописывать — имя фиксированное,
        # delete/attach всё равно ниже не пройдут для kind != custom
        db_exec("UPDATE instructions SET name=%s, body=%s, updated=%s"
                " WHERE id=%s",
                (row["name"] if row["kind"] in ("user", "project", "system")
                 else (b.get("name") or row["name"]).strip()[:120],
                 (b.get("body") if b.get("body") is not None
                  else row["body"]), time.time(), iid))
        return jsonify({"ok": True})
    if row["kind"] != "custom":
        return jsonify({"ok": False,
                        "error": "эту инструкцию удалять и "
                                 "отцеплять нельзя"}), 403
    if act == "attach":
        if not p:
            return jsonify({"ok": False, "error": "нет project"}), 400
        db_exec("INSERT IGNORE INTO instr_attach(user,project,instr_id)"
                " VALUES(%s,%s,%s)", (u, p, iid))
        return jsonify({"ok": True})
    if act == "detach":
        db_exec("DELETE FROM instr_attach WHERE user=%s AND project=%s"
                " AND instr_id=%s", (u, p, iid))
        return jsonify({"ok": True})
    if act == "delete":
        db_exec("DELETE FROM instr_attach WHERE instr_id=%s", (iid,))
        db_exec("DELETE FROM instructions WHERE id=%s", (iid,))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "bad action"}), 400


@app.get("/api/instr")
@login_required
def _api_instr_get():
    u = _current_user()
    p = (request.args.get("project") or "").strip()
    if p and not _owns_project(p):
        abort(403)
    if p:
        _ensure_project_instr(p)
    return jsonify({"ok": True, "instructions": _instr_rows(u, p)})


@app.post("/api/instr")
@login_required
def _api_instr_set():
    """Веб: update body/name, attach/detach к проекту, delete custom."""
    b = _req_json()
    u = _current_user()
    act = (b.get("action") or "").strip()
    iid = int(b.get("id") or 0)
    p = (b.get("project") or "").strip()
    if p and not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    row = db_query("SELECT * FROM instructions WHERE id=%s", (iid,))
    row = row[0] if row else None
    if not row:
        return jsonify({"ok": False, "error": "нет такой"}), 404
    if row["kind"] == "project":
        if not _owns_project(row["project"] or ""):
            return jsonify({"ok": False, "error": "нет доступа"}), 403
    elif row["user"] != u:
        return jsonify({"ok": False, "error": "чужая инструкция"}), 403
    if act == "update":
        db_exec("UPDATE instructions SET name=%s, body=%s, updated=%s"
                " WHERE id=%s",
                (row["name"] if row["kind"] in ("user", "project", "system")
                 else (b.get("name") or row["name"]).strip()[:120],
                 b.get("body") if b.get("body") is not None
                 else row["body"], time.time(), iid))
        return jsonify({"ok": True})
    if act in ("attach", "detach"):
        if row["kind"] != "custom":
            return jsonify({"ok": False,
                            "error": "подключаются только свои "
                                     "инструкции"}), 403
        if not p:
            return jsonify({"ok": False, "error": "нет project"}), 400
        if act == "attach":
            db_exec("INSERT IGNORE INTO instr_attach(user,project,"
                    "instr_id) VALUES(%s,%s,%s)", (u, p, iid))
        else:
            db_exec("DELETE FROM instr_attach WHERE user=%s"
                    " AND project=%s AND instr_id=%s", (u, p, iid))
        return jsonify({"ok": True})
    if act == "delete":
        if row["kind"] != "custom":
            return jsonify({"ok": False,
                            "error": "общую инструкцию удалить нельзя"}), 403
        db_exec("DELETE FROM instr_attach WHERE instr_id=%s", (iid,))
        db_exec("DELETE FROM instructions WHERE id=%s", (iid,))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "bad action"}), 400


def _deploy_auth() -> bool:
    """POST статусов деплоя: localhost+internal token (агенты из задач)
    или Bearer DEPLOY_TOKEN/WATCHTOWER_TOKEN (внешние скрипты/CI)."""
    if _internal_auth():
        return True
    tok = request.headers.get("Authorization", "")
    tok = tok.removeprefix("Bearer ").strip()
    return bool(tok) and tok in (
        os.environ.get("DEPLOY_TOKEN", ""),
        os.environ.get("WATCHTOWER_TOKEN", ""))


@app.post("/api/deploy/status")
def _api_deploy_status_post():
    """Приёмник статусов деплоев: {project,status,data?} -> kv.deploy:<p>
    + история (последние 10) в kv.deploy_hist:<p>. Открытый эндпоинт —
    записывается только последнее значение и короткая история,
    накопления мусора в базе нет. Авторизация не требуется:
    если прислали Bearer/X-Internal-Token — они просто игнорируются."""
    b = _req_json()
    p = (b.get("project") or "").strip()
    st = (b.get("status") or "").strip()
    if not p or st not in ("success", "failed", "running"):
        return jsonify({"ok": False, "error": "project/status?"}), 400
    rec = {"status": st, "ts": b.get("ts") or time.time(),
           "data": (b.get("data") or "")[:4000]}
    kv_set(f"deploy:{p}", json.dumps(rec, ensure_ascii=False))
    try:
        hist = json.loads(kv_get(f"deploy_hist:{p}") or "[]")
    except Exception:
        hist = []
    hist.append(rec)
    kv_set(f"deploy_hist:{p}", json.dumps(hist[-10:], ensure_ascii=False))
    log(f"deploy status {p}: {st}")
    return jsonify({"ok": True})


@app.get("/api/deploy/status")
@login_required
def _api_deploy_status_get():
    """Секция «Контроль деплоя»: последний статус + история проекта."""
    p = (request.args.get("project") or "").strip()
    if p and not _owns_project(p):
        abort(403)
    try:
        last = json.loads(kv_get(f"deploy:{p}") or "null")
        hist = json.loads(kv_get(f"deploy_hist:{p}") or "[]")
    except Exception:
        last, hist = None, []
    return jsonify({"ok": True, "last": last, "items": hist[::-1]})


_HOOK_CACHE: dict = {}   # proj -> (ts, result) — тот же TTL, что у сборок


def _gh_hooks(repo: str, token: str | None) -> dict:
    """Вебхуки GitHub-репо + последние 7 доставок каждого."""
    tk = token or GITHUB_TOKEN
    headers = {"Authorization": f"Bearer {tk}"} if tk else {}
    hooks, err = _http_json(
        f"https://api.github.com/repos/{repo}/hooks?per_page=10", headers)
    if err:
        return {"ok": False, "error": f"GitHub: {err}"}
    out = []
    for h in hooks or []:
        delivs, _ = _http_json(
            f"https://api.github.com/repos/{repo}/hooks/{h['id']}"
            "/deliveries?per_page=7", headers)
        items = [{"event": d.get("event") or "",
                  "code": d.get("status_code"),
                  "ok": bool(d.get("status_code")) and
                        200 <= int(d["status_code"]) < 300,
                  "when": d.get("delivered_at") or "",
                  "ms": round((d.get("duration") or 0) * 1000)}
                 for d in delivs or []]
        cfg = h.get("config") or {}
        out.append({"id": h.get("id"),
                    "name": cfg.get("url") or h.get("name") or "web",
                    "active": h.get("active"), "deliveries": items})
    return {"ok": True, "provider": "github", "hooks": out}


def _gl_hooks(host: str, path: str, token: str | None) -> dict:
    """Вебхуки GitLab-проекта + последние 7 доставок (events — GitLab ≥16,
    где API нет — показываем только сами хуки)."""
    tk = token or GITLAB_TOKEN
    headers = {"PRIVATE-TOKEN": tk} if tk else {}
    enc = urllib.parse.quote(path, safe="")
    base = f"https://{host}/api/v4/projects/{enc}"
    hooks, err = _http_json(f"{base}/hooks?per_page=10", headers)
    if err:
        return {"ok": False, "error": f"GitLab: {err}"}
    out = []
    for h in hooks or []:
        delivs, _ = _http_json(
            f"{base}/hooks/{h['id']}/events?per_page=7", headers)
        items = [{"event": d.get("trigger") or "",
                  "code": d.get("response_status"),
                  "ok": str(d.get("response_status") or "")
                        .startswith("2"),
                  "when": d.get("created_at") or "",
                  "ms": round((d.get("execution_duration") or 0) * 1000)}
                 for d in delivs or []]
        out.append({"id": h.get("id"),
                    "name": h.get("url") or "hook",
                    "active": not h.get("disabled_until"),
                    "deliveries": items})
    return {"ok": True, "provider": "gitlab", "hooks": out}


@app.get("/api/webhooks")
@login_required
def _api_webhooks():
    """Вебхуки origin-репо проекта (GitHub/GitLab) + последние доставки.
    Кэш 60 с; hooks пуст → фронт секцию «Вебхуки» не рисует."""
    proj = (request.args.get("project") or "").strip()
    hit = _HOOK_CACHE.get(proj)
    if hit and time.time() - hit[0] < _BUILD_TTL:
        return jsonify(hit[1])
    root = _proj_root(proj)
    res = {"ok": True, "provider": None, "hooks": []}
    if (root / ".git").exists():
        rc, url = _git(root, "remote", "get-url", "origin")
        parsed = _parse_remote(url) if rc == 0 else None
        if parsed:
            host, path, token = parsed
            token = token or _cred_get(host)
            if host == "github.com":
                res = _gh_hooks(path, token)
            else:
                gl_host = urllib.parse.urlparse(uset(
                    "gitlab.base_url", _current_user(),
                    "GITLAB_BASE_URL", "https://gitlab.com")).hostname or ""
                if "gitlab" in host or host == gl_host:
                    res = _gl_hooks(host, path, token)
    if res.get("ok"):
        _HOOK_CACHE[proj] = (time.time(), res)
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
    u = _current_user()
    # последний открытый проект этого пространства — его поднимем
    # при следующем переключении ws
    us_set(u, f"ws_proj:{_project_ws(u, p)}", p)
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
    if action == "branch":
        name = re.sub(r"[^A-Za-z0-9._/-]+", "-",
                      (body.get("name") or "").strip())[:60].strip("-.")
        if not name:
            return jsonify({"ok": False, "error": "пустое имя ветки"})
        rc, o = _git(cworkdir, "checkout", "-b", name)
        if rc != 0:
            return jsonify({"ok": False, "error": o[:300]})
        result = do_commit(stem, cworkdir)
        log(f"web commit on new branch {name} for {stem}")
        return jsonify({"ok": True, "result": result, "branch": name})
    if action == "commit":
        result = do_commit(stem, cworkdir)
        log(f"web commit accepted for {stem}")
        return jsonify({"ok": True, "result": result})
    log(f"web commit skipped for {stem}")
    return jsonify({"ok": True, "skipped": True})


@app.post("/api/stop")
@login_required
def _api_stop():
    """Web «Стоп»: гасит задачу по stem (карточка) или все запущенные,
    если stem не передан."""
    stem = (_req_json().get("stem") or "").strip()
    if stem and stem not in RUNNING_STEMS:
        return jsonify({"ok": False,
                        "error": "задача не выполняется"}), 409
    n = kill_task(stem or None)
    if n:
        log(f"web stop killed {stem or 'all'}")
        return jsonify({"ok": True, "stopped": stem or "all"})
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
