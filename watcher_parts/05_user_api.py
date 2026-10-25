# --- настройки юзера (API-ключи и пр.) ----------------------------------

SETTING_FIELDS = [
    # (key, label, секрет?, подсказка, env-фолбэк)
    ("devin.api_key", "Devin API ключ", True,
     "ключ аккаунта Devin — им задачи кладутся в CLI", "WINDSURF_API_KEY"),
    ("stt.provider", "STT провайдер(ы)", False,
     "gemini / openai / yandex, через запятую — fallback-цепочка",
     "STT_PROVIDER"),
    ("stt.api_key", "STT API ключ", True,
     "openai-совместимый и yandex делят один ключ", "STT_API_KEY"),
    ("stt.base_url", "STT base URL", True,
     "напр. https://api.groq.com/openai/v1 или api.openai.com",
     "STT_BASE_URL"),
    ("stt.model", "STT модель", False,
     "whisper-1 / whisper-large-v3-turbo", "STT_MODEL"),
    ("gemini.api_key", "Gemini API ключ", True, "AIza…", "GEMINI_API_KEY"),
    ("gemini.model", "Gemini модель", False, "gemini-2.5-flash",
     "GEMINI_MODEL"),
    ("yandex.folder_id", "Yandex folder id", False, "b1g…",
     "YANDEX_FOLDER_ID"),
    ("yandex.lang", "Yandex язык", False, "ru-RU", "YANDEX_LANG"),
    ("telegram.bot_token", "Telegram bot token", True,
     "свой бот для задач — иначе общий (env)", "TELEGRAM_BOT_TOKEN"),
    ("gitlab.base_url", "GitLab base URL", True, "self-hosted домен",
     "GITLAB_BASE_URL"),
    ("git.name", "Git user.name", False, "подпись коммитов",
     "GIT_USER_NAME"),
    ("git.email", "Git user.email", False, "email коммитов",
     "GIT_USER_EMAIL"),
]


def _env_masked(env_name: str) -> str:
    """env-значение поля — маской, чтобы UI показывал фолбэк."""
    v = os.environ.get(env_name, "")
    return ("…" + v[-4:]) if len(v) > 4 else v


@app.get("/api/project/settings")
@login_required
def _api_project_settings_get():
    p = (request.args.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    try:
        panel = json.loads(us_get(_current_user(), f"panel:{p}") or "{}")
    except Exception:
        panel = {}
    return jsonify({"ok": True,
                    "model": pj_get(p, "model"),
                    "reply_mode": pj_get(p, "reply_mode"),
                    "auto_commit": pj_get(p, "auto_commit"),
                    "fast": pj_get(p, "fast"),
                    "main_branch": pj_get(p, "main_branch"),
                    "mcp": pj_get(p, "mcp"),
                    "eff_model": pj_get(p, "model") or current_model("web"),
                    "eff_mode": (pj_get(p, "reply_mode")
                                 or reply_mode("web")),
                    "panel": panel})


@app.post("/api/project/settings")
@login_required
def _api_project_settings_set():
    body = _req_json()
    p = (body.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    for k, ok in (("model", None),
                  ("reply_mode", ("", "ask", "code")),
                  ("auto_commit", ("", "0", "1")),
                  ("fast", ("", "0", "1")),
                  ("main_branch", None)):
        if k not in body:
            continue  # частичное обновление — не трогаем пропущенные ключи
        v = (body.get(k) or "").strip()
        if ok is None or v in ok:
            pj_set(p, k, v)
    if "mcp" in body:
        v = (body.get("mcp") or "").strip()
        try:  # JSON-объект name → def либо пусто
            if v and not isinstance(json.loads(v), dict):
                raise ValueError
            pj_set(p, "mcp", v)
        except ValueError:
            return jsonify({"ok": False,
                            "error": "mcp должен быть JSON-объектом"}), 400
    # раскрытые секции боковой панели — настройка юзера+проекта
    if isinstance(body.get("panel"), dict):
        us_set(_current_user(), f"panel:{p}", json.dumps(
            {k: bool(v) for k, v in body["panel"].items()
             if k in ("files", "changes", "builds", "hooks", "ws", "branches", "instr", "deploy")}))
    return jsonify({"ok": True})


@app.get("/api/settings")
@login_required
def _api_settings_get():
    """Настройки текущего юзера; секреты уходят маской …хвост.
    `env` — env-фолбэк каждого поля (маской), `effective` — итоговое
    значение, которое реально уйдёт в работу."""
    u = _current_user()
    # поля показывают реальные значения (запрос от юзера) — поэтому
    # отдаём расшифрованные; env тоже в открытом виде
    mine = {}
    for k, v in _us_raw(u).items():
        mine[k] = us_get(u, k) if isinstance(v, str) and             v.startswith("enc:v1:") else v
    fields, eff = [], {}
    for k, l, s, h, e in SETTING_FIELDS:
        ev = os.environ.get(e, "")
        fields.append({"key": k, "label": l, "secret": s, "hint": h,
                       "env": ev, "set": k in mine})
        eff[k] = mine.get(k) or ev
    return jsonify({"ok": True, "settings": mine, "effective": eff,
                    "fields": fields})


@app.post("/api/settings")
@login_required
def _api_settings_set():
    """Сохранить настройки: непустые значения пишутся (секреты
    шифруются), пустые пропускаются. Удаление — отдельным списком
    clear: [key…]."""
    body = _req_json()
    u = _current_user()
    if "all_projects" in body:   # чекбокс «все проекты» — сразу 0/1
        us_set(u, "all_projects",
               "1" if str(body["all_projects"]) in ("1", "true") else "0")
    old_tg = us_get(u, "telegram.bot_token")
    for k in body.get("clear") or []:
        us_set(u, k, "")
    for k, l, s, h, e in SETTING_FIELDS:
        if k in body and isinstance(body[k], str) and body[k] != "":
            us_set(u, k, body[k])
    new_tg = us_get(u, "telegram.bot_token")
    if new_tg != old_tg:
        if old_tg:
            try:    # снять вебхук со старого токена
                tg_api("deleteWebhook", _token=old_tg)
            except Exception as e:
                log(f"deleteWebhook for old bot of {u}: {e}")
        if new_tg:
            register_bot_webhook(u, new_tg)
    return jsonify({"ok": True})


@app.post("/api/ws/active")
@login_required
def _api_ws_active():
    wid = int((_req_json().get("id") or 0))
    u = _current_user()
    if wid not in [w["id"] for w in _user_ws(u)]:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    kv_set(f"ws:{u}", str(wid))
    return jsonify({"ok": True})


@app.post("/api/project/ws")
@login_required
def _api_project_ws():
    """Перенести проект в другое своё пространство (точка в селекте)."""
    body = _req_json()
    p = (body.get("project") or "").strip()
    wid = int(body.get("ws") or 0)
    u = _current_user()
    if not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    if wid not in [w["id"] for w in _user_ws(u)]:
        return jsonify({"ok": False, "error": "нет такого"}), 404
    db_exec("INSERT INTO project_ws(user, name, ws_id) VALUES(%s,%s,%s)"
            " ON DUPLICATE KEY UPDATE ws_id=VALUES(ws_id)", (u, p, wid))
    return jsonify({"ok": True})


@app.get("/api/status")
@login_required
def _api_status():
    return jsonify(api_status())


@app.get("/api/projects")
@login_required
def _api_projects():
    return jsonify(api_projects())


@app.get("/api/models")
@login_required
def _api_models():
    return jsonify(api_models(
        fresh=request.args.get("fresh") == "1"))


DISCUSS_PROMPT = """\
Ты — формализатор задач для AI-агента Devin. Пользователь набрасывает \
сырую идею (часто голосом, сбивчиво). Твоя работа — превратить её в \
чёткую постановку задачи для агента-программиста.

В КАЖДОМ ответе выводи ПОЛНУЮ обновлённую постановку (не дельту):
- ## Цель — что должно получиться;
- ## Что сделать — нумерованный план работ по шагам;
- ## Критерии приёмки — как проверить, что готово.

Отвечай по-русски, markdown, без воды. Если пользователь уточняет или \
спорит — учитывай и переписывай постановку целиком. Не задавай встречных \
вопросов простынёй: спорное отражай в плане как открытый пункт.

ВАЖНО: работай в режиме «только ответ» — ничего не пиши в файлы, не \
запускай команды; весь ответ — в финальном сообщении."""


def _devin_discuss(msgs: list, user: str | None = None) -> str:
    """Формализация черновика через сам Devin CLI: одноразовая read-only
    сессия во временном каталоге, вся история диалога — в промпте.
    Ответ — stdout сессии."""
    parts = [DISCUSS_PROMPT, "", "ДИАЛОГ:"]
    for m in msgs:
        who = "Пользователь" if m["role"] == "user" else "Постановка (твой прошлый ответ)"
        parts.append(f"{who}:\n{m['text']}")
    parts.append("Выдай актуальную полную постановку задачи.")
    prompt = "\n\n".join(parts)

    workdir = Path(tempfile.mkdtemp(prefix="discuss-", dir="/tmp"))
    env = dict(os.environ)
    key = uset("devin.api_key", user, "WINDSURF_API_KEY")
    if key:
        env["WINDSURF_API_KEY"] = key
    env["DEVIN_WORKDIR"] = str(workdir)
    env["DEVIN_CONTINUE"] = "false"
    try:
        p = subprocess.run(
            ["devin", "--model", current_model(),
             "--permission-mode", "auto",
             "--respect-workspace-trust", "false",
             "-p", prompt],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", timeout=600)
        out = (p.stdout or "").strip()
        if p.returncode != 0 and not out:
            raise RuntimeError(f"devin exit {p.returncode}")
        if not out:
            raise RuntimeError("пустой ответ devin")
        return out
    except subprocess.TimeoutExpired:
        raise RuntimeError("devin не ответил за 10 минут")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/discuss")
@login_required
def _api_discuss():
    """«Обсудить»: Devin формализует сырую идею в постановку задачи.
    Тело: {"history": [{"role":"user"|"assistant","text":...}]} —
    история диалога, последнее сообщение — от юзера."""
    hist = _req_json().get("history") or []
    msgs = []
    for m in hist[-20:]:
        t = (m.get("text") or "")[:8000]
        if t:
            msgs.append({"role": "assistant" if m.get("role") == "assistant"
                         else "user", "text": t})
    if not msgs or msgs[-1]["role"] != "user":
        return jsonify({"ok": False, "error": "пустой ввод"}), 400
    try:
        text = _devin_discuss(msgs, _current_user())
    except Exception as e:
        log(f"discuss: {e}")
        return jsonify({"ok": False, "error": str(e)[:300]})
    return jsonify({"ok": True, "text": text})


@app.get("/api/tasks")
@login_required
def _api_tasks():
    try:
        limit = int(request.args.get("limit", "5"))
    except ValueError:
        limit = 5
    proj = request.args.get("project")
    if proj and not _owns_project(proj):
        abort(403)
    return jsonify(api_tasks(proj,
                             min(max(limit, 1), 50),
                             request.args.get("before")))


@app.get("/api/files")
@login_required
def _api_files():
    """One directory level of the selected project's file tree. The web
    panel lazy-loads children on each expand — a full recursive listing
    of a big repo would hang the request (and the browser)."""
    proj = (request.args.get("project") or "").strip()
    rel = (request.args.get("path") or "").strip().strip("/")
    root = _proj_root(proj)
    try:
        base = root.resolve()
        target = (base / rel).resolve()
    except OSError:
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not target.is_relative_to(base):   # ../ traversal stays out
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not target.is_dir():
        return jsonify({"ok": False, "error": "not a dir"}), 404
    try:
        items = sorted(
            (p for p in target.iterdir() if p.name != ".git"),
            key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    entries = [{"name": it.name,
                "type": "dir" if it.is_dir() else "file"}
               for it in items[:500]]
    return jsonify({"ok": True, "path": rel, "entries": entries,
                    "truncated": len(items) > 500})


def _proj_root(proj: str) -> Path:
    if proj and PROJECTS_ROOT and (PROJECTS_ROOT / proj).is_dir():
        if not _owns_project(proj):
            abort(403)
        return PROJECTS_ROOT / proj
    return WORKDIR


def _main_branch(root: Path, proj: str) -> str:
    """Рабочая ветка проекта: pj:<proj>.main_branch, иначе remote HEAD,
    иначе main/master/первая."""
    mb = pj_get(proj, "main_branch") if proj else ""
    if mb:
        return mb
    rc, out = _git(root, "symbolic-ref", "--short",
                   "refs/remotes/origin/HEAD")
    if rc == 0 and out.strip():
        return out.strip().split("/", 1)[-1]
    for cand in ("main", "master", "develop"):
        rc, _ = _git(root, "rev-parse", "--verify", f"refs/heads/{cand}")
        if rc == 0:
            return cand
    rc, out = _git(root, "branch", "--show-current")
    return out.strip() or "main"


def _stash_count(root: Path, branch: str) -> int:
    """Автостэши воркера для ветки — маркер 'auto:<branch>' в stash list."""
    rc, out = _git(root, "stash", "list")
    if rc != 0:
        return 0
    return sum(1 for ln in out.splitlines()
               if f"auto:{branch}" in ln)


@app.post("/api/repo/commit")
@login_required
def _api_repo_commit():
    """Ручной коммит+пуш текущего состояния проекта — кнопка в баре
    ветки. Отдельно от /api/commit (тот привязан к задаче)."""
    proj = (_req_json().get("project") or "").strip()
    root = _proj_root(proj)
    if not (root / ".git").exists():
        return jsonify({"ok": False, "error": "нет репо"}), 400
    out = []
    u = _current_user()
    gname = uset("git.name", u, "GIT_USER_NAME", "") or "webdev"
    gemail = uset("git.email", u, "GIT_USER_EMAIL", "") or "webdev@local"
    _, st = _git(root, "status", "--porcelain")
    if st:
        for args in (("add", "-A"),
                     ("-c", f"user.name={gname}",
                      "-c", f"user.email={gemail}",
                      "commit", "-m", "web: ручной коммит")):
            rc, o = _git(root, *args)
            out.append(o)
            if rc != 0:
                return jsonify({"ok": False, "error": o[:300]})
    rc, o = _git(root, "push")
    if rc != 0 and "no upstream branch" in o:
        # у feature-ветки нет upstream — пушим с установкой -u
        _, br = _git(root, "branch", "--show-current")
        br = br.strip()
        if br:
            rc, o = _git(root, "push", "-u", "origin", br)
    out.append(o)
    return jsonify({"ok": rc == 0,
                    "result": "\n".join(out)[-1500:],
                    "error": None if rc == 0 else o[:300]})


@app.get("/api/branches")
@login_required
def _api_branches():
    """Секция «Ветки»: локальные ветки + признаки remote/ahead/behind/
    автостэшей/грязи текущей."""
    proj = (request.args.get("project") or "").strip()
    root = _proj_root(proj)
    res = {"ok": True, "branches": [], "main": "", "current": ""}
    if not (root / ".git").exists():
        return jsonify(res)
    rc, cur = _git(root, "branch", "--show-current")
    cur = cur.strip()
    rc, remotes = _git(root, "for-each-ref",
                       "--format=%(refname:short)", "refs/remotes/origin")
    remote_set = {ln.split("/", 1)[-1] for ln in remotes.splitlines()}
    rc, out = _git(root, "for-each-ref",
                   "--format=%(refname:short)|%(upstream:track)",
                   "refs/heads")
    rc2, dirty = _git(root, "status", "--porcelain")
    branches = []
    for ln in out.splitlines():
        name, _, track = ln.partition("|")
        ahead = behind = 0
        m = re.search(r"ahead (\d+)", track)
        if m:
            ahead = int(m.group(1))
        m = re.search(r"behind (\d+)", track)
        if m:
            behind = int(m.group(1))
        branches.append({
            "name": name, "current": name == cur,
            "remote": name in remote_set,
            "ahead": ahead, "behind": behind,
            "stash": _stash_count(root, name),
            "dirty": len(dirty.splitlines()) if name == cur else 0})
    res.update({"branches": branches, "current": cur,
                "main": _main_branch(root, proj)})
    return jsonify(res)


@app.post("/api/branch/switch")
@login_required
def _api_branch_switch():
    """Переключение ветки с автостэшем: грязное дерево уходит в
    'auto:<ветка>' stash, на целевой ветке её stash достаётся обратно."""
    body = _req_json()
    proj = (body.get("project") or "").strip()
    br = (body.get("branch") or "").strip()
    root = _proj_root(proj)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}", br):
        return jsonify({"ok": False, "error": "bad branch"}), 400
    if not (root / ".git").exists():
        return jsonify({"ok": False, "error": "нет репо"}), 400
    _, cur = _git(root, "branch", "--show-current")
    cur = cur.strip()
    _, dirty = _git(root, "status", "--porcelain")
    stashed = popped = False
    if dirty:
        rc, o = _git(root, "stash", "push", "-u",
                     "-m", f"auto:{cur}")
        if rc != 0:
            return jsonify({"ok": False, "error": f"stash: {o[:300]}"})
        stashed = True
    rc, o = _git(root, "checkout", br)
    if rc != 0:
        # откат: достаём стэш обратно
        if stashed:
            _git(root, "stash", "pop")
        return jsonify({"ok": False, "error": f"checkout: {o[:300]}"})
    # достаём автостэш целевой ветки
    _, lst = _git(root, "stash", "list")
    for i, ln in enumerate(lst.splitlines()):
        if f"auto:{br}" in ln:
            rc2, o2 = _git(root, "stash", "pop", f"stash@{{{i}}}")
            popped = rc2 == 0
            break
    log(f"branch switch {cur} -> {br} in {proj or 'wd'} "
        f"(stashed={stashed} popped={popped})")
    return jsonify({"ok": True, "current": br,
                    "stashed": stashed, "popped": popped})


@app.post("/api/branch/new")
@login_required
def _api_branch_new():
    """Создать ветку от текущей и сразу на неё перейти."""
    body = _req_json()
    proj = (body.get("project") or "").strip()
    br = (body.get("name") or "").strip()
    root = _proj_root(proj)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}", br):
        return jsonify({"ok": False, "error": "bad name"}), 400
    rc, o = _git(root, "checkout", "-b", br)
    if rc != 0:
        return jsonify({"ok": False, "error": o[:300]})
    log(f"branch new {br} in {proj or 'wd'}")
    return jsonify({"ok": True, "current": br})


@app.post("/api/branch/push")
@login_required
def _api_branch_push():
    """Запушить ветку в origin (ветки нет на репо)."""
    body = _req_json()
    proj = (body.get("project") or "").strip()
    br = (body.get("branch") or "").strip()
    root = _proj_root(proj)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}", br):
        return jsonify({"ok": False, "error": "bad branch"}), 400
    rc, o = _git(root, "push", "-u", "origin", br)
    if rc != 0:
        return jsonify({"ok": False, "error": o[:400]})
    return jsonify({"ok": True})


@app.post("/api/branch/merge")
@login_required
def _api_branch_merge():
    """Слить текущую ветку в рабочую (pj.main_branch): checkout main ->
    merge -> push; при конфликте — abort и назад."""
    body = _req_json()
    proj = (body.get("project") or "").strip()
    root = _proj_root(proj)
    main = _main_branch(root, proj)
    _, cur = _git(root, "branch", "--show-current")
    cur = cur.strip()
    if cur == main:
        return jsonify({"ok": False, "error": "уже на рабочей ветке"})
    _, dirty = _git(root, "status", "--porcelain")
    if dirty:
        return jsonify({"ok": False,
                        "error": "сначала закоммить или стэшнуть "
                                 "незакоммиченные изменения"})
    out = []
    rc, o = _git(root, "checkout", main)
    out.append(o)
    if rc != 0:
        return jsonify({"ok": False, "error": o[:300]})
    rc, o = _git(root, "merge", "--no-edit", cur)
    out.append(o)
    if rc != 0:
        _git(root, "merge", "--abort")
        _git(root, "checkout", cur)
        return jsonify({"ok": False,
                        "error": f"конфликт слияния: {o[:300]}"})
    rc, o = _git(root, "push")
    out.append(o)
    log(f"merged {cur} -> {main} in {proj or 'wd'}")
    return jsonify({"ok": True, "current": main,
                    "result": "\n".join(out)[-2000:]})


def _norm_repo_url(url: str) -> str:
    """URL репо -> 'host/group/repo' (без схемы, токена и .git)."""
    p = _parse_remote(url or "")
    return f"{p[0]}/{p[1]}" if p else ""


@app.get("/api/repos/browse")
@login_required
def _api_repos_browse():
    """«Обзор репозиториев» — список репо со всех git-хостов юзера
    (kv.git_creds + gitlab.base_url/env), added — по совпадению
    remote URL, а не имени папки."""
    u = _current_user()
    creds = _creds()  # с учётом legacy-глобальных ключей админа
    # remote-урлы всех локальных проектов -> 'host/group/repo'
    have = set()
    for d in (PROJECTS_ROOT.iterdir() if PROJECTS_ROOT else []):
        if d.is_dir() and (d / ".git").exists():
            rc, url = _git(d, "remote", "get-url", "origin")
            if rc == 0:
                have.add(_norm_repo_url(url))
    # gitlab: базовый URL из настроек + env-токен в дополнение к creds
    gl_base = urllib.parse.urlparse(uset(
        "gitlab.base_url", u, "GITLAB_BASE_URL",
        "https://gitlab.com")).hostname or "gitlab.com"
    hosts = dict(creds)
    hosts.setdefault("github.com", os.environ.get("GITHUB_TOKEN", ""))
    hosts.setdefault(gl_base, os.environ.get("GITLAB_TOKEN", ""))
    out, errors = [], {}
    for host, tok in hosts.items():
        if not tok:
            continue
        if host == "github.com":
            data, err = _http_json(
                "https://api.github.com/user/repos?per_page=100"
                "&sort=updated&affiliation=owner,collaborator",
                {"Authorization": f"Bearer {tok}"})
            for r in data or []:
                key = f"github.com/{r.get('full_name', '')}"
                out.append({"host": host, "name": r.get("full_name"),
                            "desc": r.get("description") or "",
                            "url": r.get("clone_url") or "",
                            "added": key in have})
        else:
            base = host if host.startswith("http") else "https://" + host
            # membership=true, если пусто — owned, если и тут пусто —
            # просто видимые проекты (self-hosted/админ-токены)
            data = err = None
            for q in ("membership=true&", "owned=true&", ""):
                data, err = _http_json(
                    f"{base}/api/v4/projects?{q}per_page=100"
                    "&order_by=last_activity_at",
                    {"PRIVATE-TOKEN": tok})
                if data:
                    break
            for r in data or []:
                key = _norm_repo_url(r.get("http_url_to_repo") or "")
                out.append({"host": host,
                            "name": r.get("path_with_namespace"),
                            "desc": r.get("description") or "",
                            "url": r.get("http_url_to_repo") or "",
                            "added": key in have})
        if err and not any(r["host"] == host for r in out):
            errors[host] = err
    return jsonify({"ok": True, "repos": out, "errors": errors,
                    "empty": not bool(creds)})


@app.get("/api/diff")
@login_required
def _api_diff():
    """Changed files of the project repo (git status --porcelain) — feeds
    the collapsible «Изменения» section under the web file tree."""
    proj = (request.args.get("project") or "").strip()
    root = _proj_root(proj)
    if not (root / ".git").exists():
        return jsonify({"ok": True, "entries": []})
    rc, out = _git(root, "status", "--porcelain")
    if rc != 0:
        return jsonify({"ok": False, "error": out[:200]}), 500
    entries = []
    for line in out.splitlines():
        # _git() strips stdout — the leading " " of " M file" is gone, so
        # fixed offsets won't do: split on the first whitespace run
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        status, path = parts
        if " -> " in path:           # rename: "old -> new"
            path = path.split(" -> ", 1)[1]
        entries.append({"path": path.strip(), "status": status.strip()})
    return jsonify({"ok": True, "entries": entries})


@app.get("/api/diff/file")
@login_required
def _api_diff_file():
    """Unified diff of one changed file (git diff HEAD — staged+unstaged);
    untracked files get an all-added diff via `git diff --no-index`."""
    proj = (request.args.get("project") or "").strip()
    rel = (request.args.get("path") or "").strip().strip("/")
    try:
        base = _proj_root(proj).resolve()
        target = (base / rel).resolve()
    except OSError:
        return jsonify({"ok": False, "error": "bad path"}), 400
    if not rel or not target.is_relative_to(base):
        return jsonify({"ok": False, "error": "bad path"}), 400
    rc, out = _git(base, "diff", "--no-color", "HEAD", "--", rel)
    if rc == 0 and out.strip():
        return jsonify({"ok": True, "path": rel,
                        "diff": out[:300_000]})
    if target.is_file():
        # untracked — exit code 1 means "differs", that's expected here
        rc, out = _git(base, "diff", "--no-index", "--no-color",
                       "--", "/dev/null", str(target))
        if out.strip():
            return jsonify({"ok": True, "path": rel,
                            "diff": out[:300_000]})
        return jsonify({"ok": True, "path": rel, "diff": "",
                        "error": (out[:200] or "not a file")})
    return jsonify({"ok": True, "path": rel, "diff": ""})


_BUILD_CACHE: dict = {}    # proj -> (timestamp, result) — CI APIs rate-limit
_BUILD_TTL = 60


def _http_json(url: str, headers: dict | None = None, timeout: int = 20,
               method: str = "GET"):
    """GET/POST JSON via TG_OPENER (proxy-aware — GitHub/GitLab may need it)."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "devin-worker",
        **(headers or {})}, method=method)
    try:
        with TG_OPENER.open(req, timeout=timeout) as r:
            body = r.read()
            # 201/204 на POST часто с пустым телом (GitHub rerun и т.п.)
            return (json.loads(body) if body.strip() else {}), None
    except urllib.error.HTTPError as e:
        # verbose for the UI popover — "404: repo not found / private"
        body = e.read().decode("utf-8", errors="replace")[:300]
        return None, f"HTTP {e.code} {e.reason}: {body.strip()}"
    except urllib.error.URLError as e:
        return None, f"сеть: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def _parse_remote(url: str):
    """git remote URL -> (host, 'group/repo', token|None). The token is
    the password part of https user:pass@ remotes (e.g. cloned with
    x-access-token:ghp_…@github.com — reuse it for the CI API)."""
    url = url.strip()
    m = re.match(r"^(?:https?|ssh)://(?:([^@/\s]+)@)?([^/:]+)(?::\d+)?/"
                 r"(.+?)(?:\.git)?/?$", url)
    if m:
        userinfo, host, path = m.groups()
        token = userinfo.split(":", 1)[1] \
            if userinfo and ":" in userinfo else None
        return host.lower(), path.strip("/"), token
    m = re.match(r"^[^@\s]+@([^:\s]+):(.+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip("/"), None


def _gha_run(r: dict) -> dict:
    if r.get("status") != "completed":
        st = "running"
    else:
        st = {"success": "success", "failure": "failed",
              "timed_out": "failed", "startup_failure": "failed",
              "cancelled": "canceled"}.get(r.get("conclusion"), "unknown")
    return {"status": st, "name": r.get("name") or "",
            "ref": r.get("head_branch") or "",
            "num": r.get("run_number"), "id": r.get("id"),
            "url": r.get("html_url"), "when": r.get("created_at") or ""}


def _gha_status(repo: str, token: str | None = None) -> dict:
    tk = token or GITHUB_TOKEN
    headers = {"Authorization": f"Bearer {tk}"} if tk else {}
    data, err = _http_json(
        f"https://api.github.com/repos/{repo}/actions/runs?per_page=6",
        headers)
    if err:
        if err.startswith("HTTP 404"):
            err += " — репо не найден или приватный; " + \
                ("токен из remote не подошёл" if tk
                 else "задай GITHUB_TOKEN в .env")
        return {"ok": False, "error": f"GitHub: {err}"}
    raw = (data or {}).get("workflow_runs") or []
    if not raw:
        return {"ok": True, "provider": "github", "status": "none",
                "runs": []}
    runs = [_gha_run(r) for r in raw]
    top = runs[0]
    return {"ok": True, "provider": "github", "status": top["status"],
            "url": top["url"], "ref": top["ref"], "name": top["name"],
            "runs": runs}


def _gitlab_status(host: str, path: str, token: str | None = None) -> dict:
    tk = token or GITLAB_TOKEN
    headers = {"PRIVATE-TOKEN": tk} if tk else {}
    enc = urllib.parse.quote(path, safe="")
    data, err = _http_json(
        f"https://{host}/api/v4/projects/{enc}/pipelines?per_page=1",
        headers)
    if err:
        if err.startswith("HTTP 404"):
            err += " — проект не найден или приватный; " + \
                ("токен из remote не подошёл" if tk
                 else "задай GITLAB_TOKEN в .env")
        return {"ok": False, "error": f"GitLab: {err}"}
    if not data:
        return {"ok": True, "provider": "gitlab", "status": "none",
                "runs": []}

    def _gl_run(p):
        raw = p.get("status", "")
        st = {"success": "success", "failed": "failed",
              "canceled": "canceled", "skipped": "canceled"}.get(raw)
        if raw == "manual":
            st = "manual"       # пайплайн ждёт ручного запуска джобы
        elif st is None:
            st = "running" if raw in (
                "running", "pending", "preparing", "created",
                "waiting_for_resource", "scheduled") \
                else "unknown"
        return {"status": st, "name": f"pipeline #{p.get('id', '')}",
                "ref": p.get("ref") or "", "num": p.get("id"),
                "id": p.get("id"),
                "url": p.get("web_url"),
                "when": p.get("updated_at") or p.get("created_at") or ""}

    runs = [_gl_run(p) for p in data[:6]]
    top = runs[0]
    return {"ok": True, "provider": "gitlab", "status": top["status"],
            "url": top["url"], "ref": top["ref"], "name": top["name"],
            "runs": runs}


def _build_status(root: Path) -> dict:
    """Last CI run of the project's origin — GitHub Actions or GitLab."""
    if not (root / ".git").exists():
        return {"ok": True, "status": "none"}
    rc, url = _git(root, "remote", "get-url", "origin")
    parsed = _parse_remote(url) if rc == 0 else None
    if not parsed:
        return {"ok": True, "status": "none"}
    host, path, token = parsed
    token = token or _cred_get(host)
    if host == "github.com":
        return _gha_status(path, token)
    gl_host = urllib.parse.urlparse(uset("gitlab.base_url", _current_user(), "GITLAB_BASE_URL", "https://gitlab.com")).hostname or ""
    if "gitlab" in host or host == gl_host:
        return _gitlab_status(host, path, token)
    return {"ok": True, "status": "none", "remote": host}


@app.get("/api/build")
@login_required
def _api_build():
    """CI status icon for the «Изменения» panel. Cached 60 s — the GHA
    rate limit is 60 req/h without a token, and pipeline state is slow."""
    proj = (request.args.get("project") or "").strip()
    hit = _BUILD_CACHE.get(proj)
    if hit and time.time() - hit[0] < _BUILD_TTL:
        return jsonify(hit[1])
    res = _build_status(_proj_root(proj))
    if res.get("ok"):
        _BUILD_CACHE[proj] = (time.time(), res)
    return jsonify(res)


@app.get("/api/build/jobs")
@login_required
def _api_build_jobs():
    """Джобы одного прогона CI — GitHub run jobs / GitLab pipeline jobs.
    project + id (run/pipeline). Кэш 60 с."""
    proj = (request.args.get("project") or "").strip()
    rid = (request.args.get("id") or "").strip()
    if not rid.isdigit():
        return jsonify({"ok": False, "error": "нет id прогона"}), 400
    key = f"{proj}:{rid}"
    hit = _JOBS_CACHE.get(key)
    if hit and time.time() - hit[0] < _BUILD_TTL:
        return jsonify(hit[1])
    root = _proj_root(proj)
    res = {"ok": True, "jobs": []}
    if (root / ".git").exists():
        rc, url = _git(root, "remote", "get-url", "origin")
        parsed = _parse_remote(url) if rc == 0 else None
        if parsed:
            host, path, token = parsed
            token = token or _cred_get(host)
            if host == "github.com":
                tk = token or GITHUB_TOKEN
                headers = {"Authorization": f"Bearer {tk}"} if tk else {}
                d, err = _http_json(
                    f"https://api.github.com/repos/{path}"
                    f"/actions/runs/{rid}/jobs?per_page=30", headers)
                if err:
                    res = {"ok": False, "error": f"GitHub: {err}"}
                else:
                    res["jobs"] = [
                        {"name": j.get("name") or "",
                         "status": {"success": "success",
                                    "failure": "failed",
                                    "cancelled": "canceled"}
                                   .get(j.get("conclusion") or "",
                                        "running"),
                         "job_id": j.get("id"),
                         "url": j.get("html_url"),
                         "when": j.get("started_at") or "",
                         "sec": _sec_between(j.get("started_at"),
                                             j.get("completed_at"))}
                        for j in (d or {}).get("jobs") or []]
            else:
                gl_host = urllib.parse.urlparse(uset(
                    "gitlab.base_url", _current_user(),
                    "GITLAB_BASE_URL", "https://gitlab.com")).hostname or ""
                if "gitlab" in host or host == gl_host:
                    tk = token or GITLAB_TOKEN
                    headers = {"PRIVATE-TOKEN": tk} if tk else {}
                    enc = urllib.parse.quote(path, safe="")
                    d, err = _http_json(
                        f"https://{host}/api/v4/projects/{enc}"
                        f"/pipelines/{rid}/jobs?per_page=30", headers)
                    if err:
                        res = {"ok": False, "error": f"GitLab: {err}"}
                    else:
                        res["jobs"] = [
                            {"name": (j.get("stage") or "") + ": "
                                     + (j.get("name") or ""),
                             "status": {"success": "success",
                                        "failed": "failed",
                                        "canceled": "canceled",
                                        "skipped": "canceled",
                                        "manual": "manual"}
                                       .get(j.get("status") or "",
                                            "running"),
                             "job_id": j.get("id"),
                             "url": j.get("web_url"),
                             "when": j.get("started_at") or "",
                             "sec": j.get("duration")}
                            for j in d or []]
    if res.get("ok"):
        _JOBS_CACHE[key] = (time.time(), res)
    return jsonify(res)


@app.post("/api/build/job/play")
@login_required
def _api_build_job_play():
    """Запуск ручной джобы GitLab — POST /projects/:id/jobs/<job_id>/play.
    Тело: {project, job_id, pid?} — pid = id пайплайна, чтобы сбросить
    кэш джоб и UI увидел свежий статус. GitHub такого не умеет."""
    b = _req_json()
    proj = (b.get("project") or "").strip()
    jid = str(b.get("job_id") or "")
    if not jid.isdigit():
        return jsonify({"ok": False, "error": "нет job_id"}), 400
    root = _proj_root(proj)
    rc, url = _git(root, "remote", "get-url", "origin") \
        if (root / ".git").exists() else (1, "")
    parsed = _parse_remote(url) if rc == 0 else None
    if not parsed:
        return jsonify({"ok": False, "error": "нет remote"}), 400
    host, path, token = parsed
    gl_host = urllib.parse.urlparse(uset(
        "gitlab.base_url", _current_user(),
        "GITLAB_BASE_URL", "https://gitlab.com")).hostname or ""
    if "gitlab" not in host and host != gl_host:
        return jsonify({"ok": False,
                        "error": "play поддержан только для GitLab"}), 400
    token = token or _cred_get(host) or GITLAB_TOKEN
    if not token:
        return jsonify({"ok": False, "error": "нет токена GitLab"}), 403
    enc = urllib.parse.quote(path, safe="")
    data, err = _http_json(
        f"https://{host}/api/v4/projects/{enc}/jobs/{jid}/play",
        headers={"PRIVATE-TOKEN": token}, method="POST")
    if err:
        return jsonify({"ok": False, "error": f"GitLab: {err}"})
    _JOBS_CACHE.pop(f"{proj}:{b.get('pid') or ''}", None)
    return jsonify({"ok": True, "status": (data or {}).get("status")})


@app.post("/api/build/job/retry")
@login_required
def _api_build_job_retry():
    """Перезапуск завершённой джобы: GitLab POST jobs/<id>/retry,
    GitHub POST actions/jobs/<id>/rerun. Тело: {project, job_id, pid?}."""
    b = _req_json()
    proj = (b.get("project") or "").strip()
    jid = str(b.get("job_id") or "")
    if not jid.isdigit():
        return jsonify({"ok": False, "error": "нет job_id"}), 400
    root = _proj_root(proj)
    rc, url = _git(root, "remote", "get-url", "origin") \
        if (root / ".git").exists() else (1, "")
    parsed = _parse_remote(url) if rc == 0 else None
    if not parsed:
        return jsonify({"ok": False, "error": "нет remote"}), 400
    host, path, token = parsed
    if host == "github.com":
        token = token or _cred_get(host) or GITHUB_TOKEN
        if not token:
            return jsonify({"ok": False, "error": "нет токена GitHub"}), 403
        data, err = _http_json(
            f"https://api.github.com/repos/{path}/actions/jobs"
            f"/{jid}/rerun",
            headers={"Authorization": f"Bearer {token}"}, method="POST")
        provider = "GitHub"
    else:
        gl_host = urllib.parse.urlparse(uset(
            "gitlab.base_url", _current_user(),
            "GITLAB_BASE_URL", "https://gitlab.com")).hostname or ""
        if "gitlab" not in host and host != gl_host:
            return jsonify({"ok": False,
                            "error": "не GitLab/GitHub remote"}), 400
        token = token or _cred_get(host) or GITLAB_TOKEN
        if not token:
            return jsonify({"ok": False, "error": "нет токена GitLab"}), 403
        enc = urllib.parse.quote(path, safe="")
        data, err = _http_json(
            f"https://{host}/api/v4/projects/{enc}/jobs/{jid}/retry",
            headers={"PRIVATE-TOKEN": token}, method="POST")
        provider = "GitLab"
    if err:
        return jsonify({"ok": False, "error": f"{provider}: {err}"})
    _JOBS_CACHE.pop(f"{proj}:{b.get('pid') or ''}", None)
    return jsonify({"ok": True,
                    "status": (data or {}).get("status") or "queued"})


def _sec_between(a: str | None, b: str | None):
    """ISO8601 -> секунды длительности (GitHub jobs)."""
    try:
        from datetime import datetime, timezone
        f = lambda s: datetime.fromisoformat(
            (s or "").replace("Z", "+00:00"))
        if a and b:
            return int((f(b) - f(a)).total_seconds())
    except Exception:
        pass
    return None


_JOBS_CACHE: dict = {}
