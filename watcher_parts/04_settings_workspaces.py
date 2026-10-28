# --- per-user settings & secrets (kv.us:<uid> = JSON) -------------------

_SECRET_KEYS = {"stt.api_key", "gemini.api_key", "devin.api_key",
                "telegram.bot_token", "stt.base_url", "gitlab.base_url",
                "ext_key"}


def _fernet():
    """Fernet шифрование секретов в kv; ключ — kv.secret_key (сидится один
    раз). cryptography идёт в образе."""
    from cryptography.fernet import Fernet
    k = kv_get("secret_key")
    if not k:
        k = Fernet.generate_key().decode()
        kv_set("secret_key", k)
    return Fernet(k.encode())


def _us_raw(u: str) -> dict:
    try:
        return json.loads(kv_get(f"us:{u}", "{}"))
    except Exception:
        return {}


def us_get(u: str, key: str, default: str = "") -> str:
    """Декриптованное значение настройки юзера."""
    v = _us_raw(u).get(key, "")
    if isinstance(v, str) and v.startswith("enc:v1:"):
        try:
            return _fernet().decrypt(v[7:].encode()).decode()
        except Exception:
            return ""
    return v if isinstance(v, str) else default


def us_set(u: str, key: str, val: str) -> None:
    """Секретные ключи хранятся зашифрованными (enc:v1:…), остальное —
    plain. Пустое значение удаляет ключ."""
    d = _us_raw(u)
    if val == "":
        d.pop(key, None)
    else:
        d[key] = ("enc:v1:" + _fernet().encrypt(val.encode()).decode()
                  if key in _SECRET_KEYS else val)
    kv_set(f"us:{u}", json.dumps(d, ensure_ascii=False))


def us_all(u: str, mask: bool = True) -> dict:
    """Все настройки юзера; mask=True — секреты отдаются как …хвост."""
    out = {}
    for k, v in _us_raw(u).items():
        if isinstance(v, str) and v.startswith("enc:v1:"):
            p = us_get(u, k)
            out[k] = ("…" + p[-4:]) if (mask and len(p) > 4) else                      ("set" if p else "")
        else:
            out[k] = v
    return out


def uset(key: str, user: str | None = None,
         env: str | None = None, default: str = "") -> str:
    """Настройка: значение юзера → env → дефолт."""
    u = user or _current_user()
    return us_get(u, key) or os.environ.get(
        env or key.upper().replace(".", "_"), default)


def migrate_env_secrets() -> None:
    """Разово: env-креды сливаются в настройки админа (зашифрованные).
    Остальные юзеры получают пустые и видят env-фолбэк."""
    if kv_get("secrets_migrated"):
        return
    kv_set("secrets_migrated", "1")
    try:
        env_map = {
            "stt.provider": "STT_PROVIDER", "stt.api_key": "STT_API_KEY",
            "stt.base_url": "STT_BASE_URL", "stt.model": "STT_MODEL",
            "gemini.api_key": "GEMINI_API_KEY",
            "gemini.model": "GEMINI_MODEL",
            "yandex.folder_id": "YANDEX_FOLDER_ID",
            "yandex.lang": "YANDEX_LANG",
            "devin.api_key": "WINDSURF_API_KEY",
            "telegram.bot_token": "TELEGRAM_BOT_TOKEN",
            "gitlab.base_url": "GITLAB_BASE_URL",
            "git.name": "GIT_USER_NAME", "git.email": "GIT_USER_EMAIL",
        }
        a = WEB_ADMIN_USER
        for k, e in env_map.items():
            v = os.environ.get(e)
            if v and not us_get(a, k):
                us_set(a, k, v)
        # git-токены env → git_creds админа
        gh, gl = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITLAB_TOKEN")
        d = json.loads(kv_get(f"git_creds:{a}") or "{}") or {}
        if gh and "github.com" not in d:
            d["github.com"] = gh
        if gl:
            h = urllib.parse.urlparse(
                os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")
            ).hostname or "gitlab.com"
            d.setdefault(h, gl)
        if gh or gl:
            kv_set(f"git_creds:{a}", json.dumps(d))
        log(f"env secrets migrated to user settings ({a})")
    except Exception as e:
        kv_set("secrets_migrated", "")
        log(f"env->user secrets migration failed (retry): {e}")


# --- настройки проекта (kv.pj:<name> = JSON) -----------------------------
# model / reply_mode / auto_commit — задаются в шестерёнке селекта
# проектов; пустое = наследовать (модель — юзера, режим — юзера,
# auto_commit — по умолчанию ВЫКЛ).

def pj_get(name: str, key: str, default: str = "") -> str:
    try:
        v = json.loads(kv_get(f"pj:{name}", "{}")).get(key, "")
        return v if isinstance(v, str) else default
    except Exception:
        return default


def pj_set(name: str, key: str, val: str) -> None:
    try:
        d = json.loads(kv_get(f"pj:{name}", "{}"))
    except Exception:
        d = {}
    if val == "":
        d.pop(key, None)
    else:
        d[key] = val
    kv_set(f"pj:{name}", json.dumps(d, ensure_ascii=False))


# --- рабочие пространства (per-user) ------------------------------------

def _ensure_default_ws(user: str) -> int:
    """«По умолчанию» — создаётся каждому юзеру один раз, удалить нельзя
    (только переименовать/перекрасить)."""
    r = db_query("SELECT id FROM workspaces"
                 " WHERE owner=%s AND is_default=1", (user,))
    if r:
        return r[0]["id"]
    db_exec("INSERT INTO workspaces(owner, name, color, is_default)"
            " VALUES(%s,'По умолчанию','#1565c0',1)", (user,))
    return db_query("SELECT id FROM workspaces"
                    " WHERE owner=%s AND is_default=1", (user,))[0]["id"]


def _user_ws(user: str) -> list:
    _ensure_default_ws(user)
    return db_query("SELECT id, name, color, is_default"
                    " FROM workspaces WHERE owner=%s ORDER BY id", (user,))


def _active_ws(user: str) -> int:
    """Активное пространство юзера (kv.ws:<uid>), невалидное → дефолтное."""
    ws = _user_ws(user)
    wid = int(kv_get(f"ws:{user}") or 0)
    if not any(w["id"] == wid for w in ws):
        wid = next(w["id"] for w in ws if w["is_default"])
        kv_set(f"ws:{user}", str(wid))
    return wid


def _project_ws(user: str, name: str) -> int:
    """Пространство проекта для юзера; без записи → дефолтное
    (новые/зашаренные сюда и попадают)."""
    r = db_query("SELECT ws_id FROM project_ws WHERE user=%s AND name=%s",
                 (user, name))
    if r:
        return r[0]["ws_id"]
    wid = _ensure_default_ws(user)
    db_exec("INSERT IGNORE INTO project_ws(user, name, ws_id)"
            " VALUES(%s,%s,%s)", (user, name, wid))
    return wid


def _migrate_workspaces() -> None:
    """Одноразово: дефолтное пространство каждому юзеру + все существующие
    проекты в дефолт их владельцев/получателей."""
    users = {WEB_ADMIN_USER} | {
        r["username"] for r in db_query("SELECT username FROM users")}
    for u in users:
        _ensure_default_ws(u)
    for r in db_query("SELECT name, owner FROM project_owner"):
        _project_ws(r["owner"], r["name"])
    for r in db_query("SELECT name, user FROM project_acl"):
        _project_ws(r["user"], r["name"])


def login_required(fn):
    """Session gate: 401 JSON for /api/*, redirect to /login for pages.
    Disabled entirely when no admin password is configured."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if _admin_hash() and not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "auth required"}), 401
            nxt = request.full_path.rstrip("?")
            return redirect("/login?next=" +
                            urllib.parse.quote(nxt, safe=""))
        return fn(*a, **kw)
    return wrapper


def _req_json() -> dict:
    return request.get_json(silent=True) or {}


@app.route("/login", methods=["GET", "POST"])
def _login():
    if not _admin_hash():          # no password configured → auth off
        return redirect("/")
    # куда вернуться после входа (?next=/…?project=X) — только
    # внутренние пути, open-redirect исключён
    nxt = (request.form.get("next") or request.args.get("next") or "")
    if not (nxt.startswith("/") and not nxt.startswith("//")):
        nxt = ""
    if request.method == "POST":
        user = request.form.get("user", "")
        pw = request.form.get("password", "")
        if _user_hash(user) and \
                check_password_hash(_user_hash(user), pw):
            session["uid"] = user
            log(f"web login ok: {user}")
            return redirect(nxt or "/")
        log(f"web login failed: {user!r}")
        return redirect("/login?err=1" +
                        ("&next=" + urllib.parse.quote(nxt, safe="")
                         if nxt else ""))
    if session.get("uid"):
        return redirect(nxt or "/")
    return render_template("login.html",
                           error=bool(request.args.get("err")))


@app.post("/logout")
def _logout():
    session.clear()
    return redirect("/login")


@app.post("/api/password")
@login_required
def _api_password():
    global _admin_pw_hash
    body = _req_json()
    u = _current_user()
    if not check_password_hash(_user_hash(u), body.get("current") or ""):
        return jsonify({"ok": False,
                        "error": "неверный текущий пароль"}), 403
    new = body.get("new") or ""
    if len(new) < 6:
        return jsonify({"ok": False,
                        "error": "новый пароль короче 6 символов"}), 400
    h = generate_password_hash(new)
    if u == WEB_ADMIN_USER:
        _admin_pw_hash = h
        kv_set("admin_password_hash", h)
    else:
        db_exec("UPDATE users SET pw_hash=%s WHERE username=%s", (h, u))
    log(f"web password changed ({u})")
    return jsonify({"ok": True})


# --- управление пользователями (только админ) ---------------------------

def _admin_only() -> bool:
    return _admin_hash() and _is_admin()


@app.get("/api/users")
@login_required
def _api_users():
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    out = [{"user": WEB_ADMIN_USER, "admin": True}]
    for r in db_query("SELECT username, is_admin FROM users"
                      " ORDER BY created"):
        out.append({"user": r["username"], "admin": bool(r["is_admin"])})
    return jsonify({"ok": True, "users": out})


@app.post("/api/users")
@login_required
def _api_users_add():
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    body = _req_json()
    u = (body.get("user") or "").strip()
    pw = body.get("password") or ""
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,64}", u):
        return jsonify({"ok": False, "error":
                        "логин: 2-64 символа, a-z, 0-9, точка, _ -"}), 400
    if u == WEB_ADMIN_USER or \
            db_query("SELECT 1 FROM users WHERE username=%s", (u,)):
        return jsonify({"ok": False,
                        "error": "такой пользователь уже есть"}), 409
    if len(pw) < 6:
        return jsonify({"ok": False,
                        "error": "пароль короче 6 символов"}), 400
    db_exec("INSERT INTO users(username, pw_hash, is_admin, created)"
            " VALUES(%s,%s,%s,%s)",
            (u, generate_password_hash(pw), 0, time.time()))
    _ensure_default_ws(u)   # «По умолчанию» — у каждого с рождения
    _ensure_user_instr(u)   # и пустая общая инструкция
    log(f"web user created: {u}")
    return jsonify({"ok": True, "user": u})


@app.post("/api/users/delete")
@login_required
def _api_users_del():
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    u = (_req_json().get("user") or "").strip()
    if u == WEB_ADMIN_USER:
        return jsonify({"ok": False, "error": "админа нельзя"}), 400
    db_exec("DELETE FROM users WHERE username=%s", (u,))
    # проекты ушедшего юзера переходят админу — иначе «осиротеют»
    db_exec("UPDATE project_owner SET owner=%s WHERE owner=%s",
            (WEB_ADMIN_USER, u))
    db_exec("DELETE FROM project_acl WHERE user=%s", (u,))
    log(f"web user deleted: {u}")
    return jsonify({"ok": True})


@app.get("/api/users/perms")
@login_required
def _api_users_perms_get():
    """Выданные юзеру проекты — для модалки прав (клик по юзеру)."""
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    u = (request.args.get("user") or "").strip()
    return jsonify({"ok": True, "user": u,
                    "granted": sorted(_granted_projects(u))})


@app.post("/api/users/perms")
@login_required
def _api_users_perms_set():
    """Заменить список выданных проектов юзера целиком."""
    if not _admin_only():
        return jsonify({"ok": False, "error": "только для админа"}), 403
    body = _req_json()
    u = (body.get("user") or "").strip()
    if u == WEB_ADMIN_USER:
        return jsonify({"ok": False,
                        "error": "админу права не нужны"}), 400
    projs = [p for p in (body.get("projects") or [])
             if p in list_projects()]
    db_exec("DELETE FROM project_acl WHERE user=%s", (u,))
    for p in projs:
        db_exec("INSERT INTO project_acl(name, user) VALUES(%s,%s)",
                (p, u))
        _project_ws(u, p)   # зашаренный проект → дефолт юзера
    log(f"web perms for {u}: {projs}")
    return jsonify({"ok": True, "granted": projs})


# --- API рабочих пространств ---------------------------------------------

@app.get("/api/ws")
@login_required
def _api_ws_list():
    u = _current_user()
    return jsonify({"ok": True, "active": _active_ws(u),
                    "ws": [{"id": w["id"], "name": w["name"],
                            "color": w["color"],
                            "default": bool(w["is_default"])}
                           for w in _user_ws(u)]})


@app.post("/api/ws")
@login_required
def _api_ws_new():
    body = _req_json()
    name = (body.get("name") or "").strip()[:64]
    color = (body.get("color") or "#1565c0").strip()[:16]
    if not name:
        return jsonify({"ok": False, "error": "имя пустое"}), 400
    db_exec("INSERT INTO workspaces(owner, name, color, is_default)"
            " VALUES(%s,%s,%s,0)", (_current_user(), name, color))
    return jsonify({"ok": True})


@app.post("/api/ws/update")
@login_required
def _api_ws_update():
    """Переименовать/перекрасить своё пространство (дефолтное — можно)."""
    body = _req_json()
    wid = int(body.get("id") or 0)
    u = _current_user()
    ws = [w for w in _user_ws(u) if w["id"] == wid]
    if not ws:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    name = (body.get("name") or ws[0]["name"]).strip()[:64]
    color = (body.get("color") or ws[0]["color"]).strip()[:16]
    db_exec("UPDATE workspaces SET name=%s, color=%s WHERE id=%s",
            (name, color, wid))
    return jsonify({"ok": True})


@app.post("/api/ws/delete")
@login_required
def _api_ws_del():
    body = _req_json()
    wid = int(body.get("id") or 0)
    u = _current_user()
    ws = [w for w in _user_ws(u) if w["id"] == wid]
    if not ws:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    if ws[0]["is_default"]:
        return jsonify({"ok": False,
                        "error": "дефолтное нельзя удалить"}), 400
    dw = _ensure_default_ws(u)
    db_exec("UPDATE project_ws SET ws_id=%s WHERE user=%s AND ws_id=%s",
            (dw, u, wid))
    db_exec("DELETE FROM workspaces WHERE id=%s", (wid,))
    if _active_ws(u) == wid:
        kv_set(f"ws:{u}", str(dw))
    return jsonify({"ok": True})
