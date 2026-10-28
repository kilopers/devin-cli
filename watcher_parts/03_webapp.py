# --- web UI / JSON API -------------------------------------------------------

def api_status() -> dict:
    # текущая ветка веб-проекта — тонкая строка под шапкой на мобильной
    branch = ""
    try:
        p = _web_current(_current_user())
        if p and PROJECTS_ROOT and (PROJECTS_ROOT / p / ".git").exists():
            rc, b = _git(PROJECTS_ROOT / p, "branch", "--show-current")
            branch = b.strip() if rc == 0 else ""
    except Exception:
        pass
    return {
        "uptime": int(time.time() - _started_at),
        "branch": branch,
        "queue": db_query(
            "SELECT COUNT(*) AS n FROM tasks WHERE status='queued'")[0]["n"],
        "current_task": STATE["current_task"],
        "running_tasks": STATE.get("running_tasks") or [],
        "last_task": STATE["last_task"],
        "last_status": STATE["last_status"],
        "tasks_done": STATE["tasks_done"],
        "model": current_model("web"),
        "project": project_label(),
        "mode": pj_get(_web_current(_current_user()) or "", "reply_mode")
                or reply_mode("web"),
        "fast": pj_get(_web_current(_current_user()) or "", "fast") or "0",
        "stt_status": STATE.get("stt") or "",
        "version": APP_VERSION,
        "user": _current_user() if _admin_hash() else "",
        "is_admin": _is_admin(),
    }


def _web_current(user: str) -> str | None:
    """Проект, реально показанный выбранным в вебе: сохранённый, если он в
    активном пространстве, иначе первый из списка (как в api_projects)."""
    wid = _active_ws(user)
    allp = us_get(user, "all_projects") == "1"
    visible = _user_projects(user)
    mine = list(visible) if allp else         [p for p in visible if _project_ws(user, p) == wid]
    cur = current_project("web")[0]
    return cur if cur in mine else (mine[0] if mine else None)


def api_projects() -> dict:
    u = _current_user()
    visible = _user_projects(u)
    wid = _active_ws(u)
    # по умолчанию — проекты активного пространства; опция юзера
    # all_projects=1 показывает все его проекты со всех пространств
    allp = us_get(u, "all_projects") == "1"
    mine = list(visible) if allp else         [p for p in visible if _project_ws(u, p) == wid]
    if allp:
        # группировка по пространствам (порядок ws), внутри — по имени
        order = {w["id"]: i for i, w in enumerate(_user_ws(u))}
        mine.sort(key=lambda p: (order.get(_project_ws(u, p), 999),
                                 p.lower()))
    cur = _web_current(u)
    # при смене ws поднимаем последний открытый в нём проект юзера
    last = us_get(u, f"ws_proj:{wid}")
    cur = cur if cur in mine else         (last if last in mine else (mine[0] if mine else None))
    return {"projects": mine,
            "wsmap": {p: _project_ws(u, p) for p in visible},
            "current": cur,
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
    with _run_lock:
        running = set(RUNNING_STEMS)
    sql, params = "SELECT * FROM tasks", []
    if project:
        sql += " WHERE project=%s"
        params.append(project)
    rows = db_query(sql + " ORDER BY created", params)
    items = []
    for r in rows:
        stem = r["stem"]
        st = "running" if stem in running else r["status"]
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
        try:
            o = json.loads(kv_get(f"opts:{stem}") or "{}")
        except ValueError:
            o = {}
        items.append({
            "name": _task_name(stem),
            "stem": stem,
            "project": r["project"] or "",
            "model": r["model"] or "",
            "mode": o.get("mode") or r["reply_mode"] or "",
            "ac": o.get("ac") if o.get("ac") is not None else
                  (pj_get(r["project"], "auto_commit")
                   if r["project"] else ""),
            "source": r["source"],
            "status": st,
            "task_status": r["task_status"] or "",
            "commit_offered": bool(r["commit_offered"]),
            "tag": kv_get(f"tag:{stem}"),
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


@app.errorhandler(Exception)
def _api_errors(e):
    """API всегда отвечает JSON — фронт парсит ответ как JSON, а дефолтная
    HTML-страница Flask на 500/404 ломала её («Unexpected token '<'»)."""
    from werkzeug.exceptions import HTTPException
    code = e.code if isinstance(e, HTTPException) else 500
    if request.path.startswith("/api/"):
        msg = getattr(e, "description", None) or f"{type(e).__name__}: {e}"
        if code >= 500:
            log(f"API {request.path} {code}: {e!r}")
        return jsonify({"ok": False, "error": str(msg)[:400]}), code
    return e
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
    """uid из сессии; вне request-ctx (телеграм, фон) — админ."""
    try:
        return session.get("uid") or WEB_ADMIN_USER
    except RuntimeError:
        return WEB_ADMIN_USER


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
