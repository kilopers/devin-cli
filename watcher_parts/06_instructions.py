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
    kv.tag:<stem>; stem — свой ($TASK_STEM). Фолбэк «текущая running»
    только когда бежит ровно одна задача — при параллельных прогонах
    разных проектов угадывание сажало тег на чужую карточку."""
    if not _internal_auth():
        abort(403)
    b = _req_json()
    stem = (b.get("stem") or "").strip()
    if not stem:
        with _run_lock:
            running = sorted(RUNNING_STEMS)
        if len(running) == 1:
            stem = running[0]
        elif len(running) == 0:
            stem = (Path(STATE["current_task"]).stem
                    if STATE["current_task"] else "")
        else:
            return jsonify({"ok": False,
                            "error": "идёт несколько задач — передай"
                                     ' stem явно ("stem":"$TASK_STEM")'}
                           ), 409
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
    if act in ("attach", "detach") and "topic" in b:
        # привязка к КОЛОНКЕ (instr_topic_attach): инструкция работает
        # только в задачах этой темы; 0/«main» — «главная» колонка
        tv = str(b.get("topic") or "main").strip()
        tid = 0 if tv in ("", "main") else (
            int(tv) if tv.isdigit() else -1)
        if tid == -1 or (tid and not db_query(
                "SELECT 1 FROM topics WHERE id=%s AND project=%s",
                (tid, p))):
            return jsonify({"ok": False, "error": "нет такой темы"}), 404
        if act == "attach":
            db_exec("INSERT IGNORE INTO instr_topic_attach"
                    "(user,project,topic_id,instr_id)"
                    " VALUES(%s,%s,%s,%s)", (u, p, tid, iid))
        else:
            db_exec("DELETE FROM instr_topic_attach WHERE user=%s"
                    " AND project=%s AND topic_id=%s AND instr_id=%s",
                    (u, p, tid, iid))
        return jsonify({"ok": True})
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
        db_exec("DELETE FROM instr_topic_attach WHERE instr_id=%s",
                (iid,))
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
        tv = b.get("topic")
        if tv is not None:
            # привязка к колонке (0/«main» — «главная»): инструкция
            # действует только в задачах этой темы — к проекту
            # подключена быть не обязана
            tv = str(tv).strip()
            tid = 0 if tv in ("", "main") else (
                int(tv) if tv.isdigit() else -1)
            if tid == -1 or (tid and not db_query(
                    "SELECT 1 FROM topics WHERE id=%s AND project=%s",
                    (tid, p))):
                return jsonify({"ok": False,
                                "error": "нет такой темы"}), 404
            if act == "attach":
                db_exec("INSERT IGNORE INTO instr_topic_attach"
                        "(user,project,topic_id,instr_id)"
                        " VALUES(%s,%s,%s,%s)", (u, p, tid, iid))
            else:
                db_exec("DELETE FROM instr_topic_attach WHERE user=%s"
                        " AND project=%s AND topic_id=%s"
                        " AND instr_id=%s", (u, p, tid, iid))
            return jsonify({"ok": True})
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
        db_exec("DELETE FROM instr_topic_attach WHERE instr_id=%s",
                (iid,))
        db_exec("DELETE FROM instructions WHERE id=%s", (iid,))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "bad action"}), 400


# --- темы проекта: именованные ветки работы со своей devin-сессией ----

def _topic_rows(project: str) -> list:
    return db_query("SELECT id, name, session_id, own_session,"
                    " session_topic_id, sort, user, created, updated,"
                    " color, model, reply_mode, auto_commit, fast, chat"
                    " FROM topics WHERE project=%s"
                    " ORDER BY sort, id", (project,))


def _topic_settings_from(b: dict) -> dict:
    """Присланные поля настроек темы с валидацией — пропущенные ключи
    не трогаем (частичное обновление)."""
    st = {}
    if "color" in b:
        c = (b.get("color") or "").strip()[:24]
        st["color"] = c if re.fullmatch(r"#[0-9a-fA-F]{6}", c) else ""
    if "model" in b:
        st["model"] = (b.get("model") or "").strip()[:80]
    if "reply_mode" in b and (b.get("reply_mode") or "") in ("", "code", "ask", "say"):
        st["reply_mode"] = (b.get("reply_mode") or "")
    for k in ("auto_commit", "fast"):
        if k in b and (b.get(k) or "") in ("", "0", "1"):
            st[k] = (b.get(k) or "")
    if "agent" in b and (b.get("agent") or "") in ("",) + tuple(AGENTS):
        st["agent"] = (b.get("agent") or "")
    return st


def _main_col_json(p: str) -> dict:
    """Сырой JSON настроек «главной» колонки (pj:<p>.tmain): ключи
    TOPIC_SET_KEYS + name + sort."""
    try:
        d = json.loads(pj_get(p, "tmain") or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def _main_col_name(p: str) -> str:
    """Своё имя «главной» колонки — ключ name в pj:<p>.tmain
    (переименовать можно, удалить нельзя)."""
    return (_main_col_json(p).get("name") or "").strip()


def _topic_append_sort(project: str) -> int:
    """sort новой темы — всегда ПОСЛЕДНЯЯ (справа) на доске:
    максимум по всем колонкам (темы + «главная» из pj:<p>.tmain) +10.
    Простой sort=id ломался после «сместить»: move нормализует
    порядок шагом 10, и id новой темы оказывался меньше — она
    вставала первой."""
    mx = int(_main_col_json(project).get("sort") or 0)
    r = db_query("SELECT MAX(sort) s FROM topics WHERE project=%s",
                 (project,))
    if r and r[0]["s"]:
        mx = max(mx, int(r[0]["s"]))
    return mx + 10


def _topic_instr_ids(b: dict, u: str) -> list | None:
    """instrs:[id…] из запроса → проверенные id СВОИХ custom-
    инструкций (чужие/неcustom отбрасываются). Ключа нет — None:
    привязки колонки не трогаем."""
    if "instrs" not in b:
        return None
    ids = b.get("instrs")
    if not isinstance(ids, list):
        return []
    out = []
    for i in ids[:30]:
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            pass
    if not out:
        return []
    rows = db_query(
        "SELECT id FROM instructions WHERE kind='custom' AND user=%s"
        " AND id IN (" + ",".join(["%s"] * len(out)) + ")",
        (u, *out))
    return [r["id"] for r in rows]


def _topic_instr_set(project: str, tid: int, u: str,
                     ids: list) -> None:
    """Полная замена набора инструкций колонки у юзера
    (tid 0 = «главная»); чужие привязки не трогаем."""
    db_exec("DELETE FROM instr_topic_attach"
            " WHERE project=%s AND topic_id=%s AND user=%s",
            (project, tid, u))
    for iid in ids:
        db_exec("INSERT IGNORE INTO instr_topic_attach"
                "(user,project,topic_id,instr_id) VALUES(%s,%s,%s,%s)",
                (u, project, tid, iid))


def _topic_tpls(p: str) -> dict:
    """Шаблоны задач колонок проекта: {None|topic_id: [{id,text}]},
    None = «главная». Ряд мини-кнопок в шапке колонки: клик ставит
    задачу текстом шаблона, ✕ удаляет его."""
    d = {}
    for r in db_query("SELECT id, topic_id, text FROM topic_templates"
                      " WHERE project=%s ORDER BY created, id", (p,)):
        d.setdefault(r["topic_id"], []).append(
            {"id": r["id"], "text": r["text"]})
    return d


@app.get("/api/topics")
@login_required
def _api_topics_get():
    p = (request.args.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    rows = _topic_rows(p)
    by_id = {r["id"]: r for r in rows}
    tpls = _topic_tpls(p)
    # инструкции, привязанные к колонкам (0 = «главная»), и число
    # cron-расписаний на колонку — чип ⏱N в шапке
    tattach: dict = {}
    for r in db_query("SELECT topic_id, instr_id"
                      " FROM instr_topic_attach WHERE project=%s", (p,)):
        tattach.setdefault(r["topic_id"], []).append(r["instr_id"])
    scheds = {r["topic_id"]: r["n"] for r in db_query(
        "SELECT topic_id, COUNT(*) n FROM task_schedules"
        " WHERE project=%s GROUP BY topic_id", (p,))}
    out = []
    for r in rows:
        at = r.get("session_topic_id") or None
        # 🔁: своя закреплённая сессия или сессия прицепленной темы;
        # у темы с общей сессией (без прицепки) пина нет никогда
        pin = (r["session_id"] if r["own_session"]
               else (by_id.get(at) or {}).get("session_id") if at
               else None)
        out.append(dict(r, has_session=bool(pin),
                        # имя темы, к чьей сессии прицеплены (для чипа)
                        attach_name=((by_id.get(at) or {}).get("name")
                                     if at else None),
                        tpls=tpls.get(r["id"]) or [],
                        instrs=tattach.get(r["id"]) or [],
                        scheds=scheds.get(r["id"]) or 0,
                        eff=_eff_topic_defaults(p, r["id"])))
    return jsonify({"ok": True,
                    # настройки «главной» колонки — pj:<p>.tmain;
                    # eff — итоговые дефолты (тема → проект → глобальные),
                    # их чипами рисует шапка колонки
                    "main": dict(_topic_defaults(p, None),
                                 name=_main_col_name(p),
                                 sort=(_main_col_json(p).get("sort")
                                       or 0),
                                 tpls=tpls.get(None) or [],
                                 instrs=tattach.get(0) or [],
                                 scheds=scheds.get(None) or 0,
                                 eff=_eff_topic_defaults(p, None)),
                    "topics": out})


@app.post("/api/topic/tpl")
@login_required
def _api_topic_tpl():
    """Шаблоны задач темы: create — сохранить текст в колонку
    (topic="main" или id темы проекта), delete — по id. Запуск
    шаблона — обычный POST /api/tasks с темой колонки, дефолты
    задачи берутся из её настроек."""
    b = _req_json()
    p = (b.get("project") or "").strip()
    act = (b.get("action") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    if act == "create":
        text = (b.get("text") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "пустой текст"}), 400
        if len(text) > 20000:
            return jsonify({"ok": False, "error": "text too long"}), 400
        tv = str(b.get("topic") or "main").strip()
        tid = None if tv in ("", "main") else (
            int(tv) if tv.isdigit() else -1)
        if tid == -1 or (tid is not None and not db_query(
                "SELECT 1 FROM topics WHERE id=%s AND project=%s",
                (tid, p))):
            return jsonify({"ok": False, "error": "нет такой темы"}), 404
        db_exec("INSERT INTO topic_templates(project,topic_id,text,"
                "created) VALUES(%s,%s,%s,%s)",
                (p, tid, text, time.time()))
        return jsonify({"ok": True})
    if act == "delete":
        tid = int(b.get("id") or 0)
        db_exec("DELETE FROM topic_templates"
                " WHERE id=%s AND project=%s", (tid, p))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "bad action"}), 400


@app.post("/api/topics")
@login_required
def _api_topics_set():
    """create/rename/delete темы проекта."""
    b = _req_json()
    u = _current_user()
    act = (b.get("action") or "").strip()
    p = (b.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    if act == "create":
        name = (b.get("name") or "").strip()[:190] or None
        if name and db_query("SELECT 1 FROM topics WHERE project=%s"
                             " AND name=%s", (p, name)):
            return jsonify({"ok": False,
                            "error": "тема с таким именем уже есть"}), 409
        st = _topic_settings_from(b)
        # own_session/session_topic_id — только при создании, полей
        # в настройках темы нет и через settings их не поменять;
        # чат-колонка (chat=1, диалог-пузыри) — тоже только при
        # создании, у неё всегда СВОЯ сессия
        chat = 1 if b.get("chat") else 0
        own = 0 if str(b.get("own_session") or "1") == "0" else 1
        if chat:
            own = 1
        attach = None
        if not own:
            # прицепка к сессии существующей темы — только к теме того
            # же проекта со своей сессией (own_session=1); иначе —
            # общая сессия проекта
            atid = int(b.get("session_topic_id") or 0)
            if atid:
                arow = db_query(
                    "SELECT own_session FROM topics WHERE id=%s"
                    " AND project=%s", (atid, p))
                if not arow or not arow[0]["own_session"]:
                    return jsonify(
                        {"ok": False,
                         "error": "прицепиться можно только к теме "
                                  "со своей сессией"}), 400
                attach = atid
        db_exec("INSERT INTO topics(project,user,name,color,model,"
                "reply_mode,auto_commit,fast,own_session,"
                "session_topic_id,chat,created,updated)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (p, u, name, st.get("color") or None,
                 st.get("model") or None, st.get("reply_mode") or None,
                 st.get("auto_commit") or None, st.get("fast") or None,
                 own, attach, chat, time.time(), time.time()))
        new_id = db_query("SELECT LAST_INSERT_ID() AS i")[0]["i"]
        # новая тема — последняя (справа); бессортовые старые добиваем
        db_exec("UPDATE topics SET sort=id WHERE sort=0 AND id<>%s",
                (new_id,))
        db_exec("UPDATE topics SET sort=%s WHERE id=%s",
                (_topic_append_sort(p), new_id))
        # инструкции колонки — instrs:[id…] из диалога создания
        ids = _topic_instr_ids(b, u)
        if ids:
            _topic_instr_set(p, new_id, u, ids)
        return jsonify({"ok": True, "id": new_id})
    if act == "settings" and b.get("main"):
        # «главная» колонка — не строка topics: настройки лежат
        # JSON-объектом в pj:<p>.tmain (ключи колонок + name — её
        # переименование); читаем сырой JSON, чтобы не затирать
        # лишние ключи при обычном сохранении
        try:
            cur = json.loads(pj_get(p, "tmain") or "{}")
        except ValueError:
            cur = {}
        if not isinstance(cur, dict):
            cur = {}
        cur.update(_topic_settings_from(b))
        if "name" in b:
            nm = (b.get("name") or "").strip()[:190]
            if nm:
                cur["name"] = nm
            else:
                cur.pop("name", None)
        pj_set(p, "tmain", json.dumps(cur, ensure_ascii=False))
        ids = _topic_instr_ids(b, u)
        if ids is not None:
            _topic_instr_set(p, 0, u, ids)   # 0 = «главная» колонка
        return jsonify({"ok": True})
    if act == "move":
        # сдвиг колонки на доске влево/вправо — обмен местом с соседом;
        # «главная» — такая же колонка (id="main", её sort лежит
        # ключом sort в pj:<p>.tmain), удалить её нельзя, а двигать
        # можно. Заодно нормализуем sort всей доски шагом 10.
        dirn = (b.get("dir") or "").strip()
        cols = ([("main", _main_col_json(p).get("sort") or 0)]
                + [(r["id"], r["sort"])
                   for r in db_query(
                       "SELECT id, sort FROM topics WHERE project=%s",
                       (p,))])
        cols.sort(key=lambda kv: (kv[1], str(kv[0])))
        keys = [c[0] for c in cols]
        tgt = ("main" if str(b.get("id")) == "main"
               else int(b.get("id") or 0))
        if tgt not in keys:
            return jsonify({"ok": False,
                            "error": "нет такой темы"}), 404
        i = keys.index(tgt)
        j = i - 1 if dirn == "left" else (
            i + 1 if dirn == "right" else -1)
        if not (0 <= j < len(keys)):
            return jsonify({"ok": False,
                            "error": "некуда двигать"}), 400
        keys[i], keys[j] = keys[j], keys[i]
        tmj = _main_col_json(p)
        for k, kk in enumerate(keys):
            s = (k + 1) * 10
            if kk == "main":
                tmj["sort"] = s
            else:
                db_exec("UPDATE topics SET sort=%s WHERE id=%s",
                        (s, kk))
        pj_set(p, "tmain", json.dumps(tmj, ensure_ascii=False))
        return jsonify({"ok": True})
    tid = int(b.get("id") or 0)
    if not db_query("SELECT 1 FROM topics WHERE id=%s AND project=%s",
                    (tid, p)):
        return jsonify({"ok": False, "error": "нет такой темы"}), 404
    if act == "rename":
        name = (b.get("name") or "").strip()[:190]
        if not name:
            return jsonify({"ok": False, "error": "пустое имя"}), 400
        db_exec("UPDATE topics SET name=%s, updated=%s WHERE id=%s",
                (name, time.time(), tid))
        return jsonify({"ok": True})
    if act == "settings":
        # настройки именованной темы: имя (необяз.) + цвет + дефолты
        # задач колонки; неприсланные ключи не трогаем
        sets, vals = [], []
        new_name = (b.get("name") or "").strip()[:190]
        if new_name and db_query(
                "SELECT 1 FROM topics WHERE project=%s AND name=%s"
                " AND id!=%s", (p, new_name, tid)):
            return jsonify({"ok": False,
                            "error": "тема с таким именем уже есть"}), 409
        if new_name:
            sets.append("name=%s")
            vals.append(new_name)
        st = _topic_settings_from(b)
        for k in TOPIC_SET_KEYS:
            if k in st:
                sets.append(f"{k}=%s")
                vals.append(st[k] or None)
        if sets:
            sets.append("updated=%s")
            vals += [time.time(), tid]
            db_exec(f"UPDATE topics SET {', '.join(sets)} WHERE id=%s",
                    vals)
        ids = _topic_instr_ids(b, u)
        if ids is not None:
            _topic_instr_set(p, tid, u, ids)
        return jsonify({"ok": True})
    if act == "delete":
        # активные задачи блокируют удаление темы целиком — сообщение
        # с именем карточки, повторить после её завершения
        act_rows = db_query(
            "SELECT stem FROM tasks WHERE topic_id=%s"
            " AND status IN ('queued','running') LIMIT 4", (tid,))
        if act_rows:
            names = ", ".join(_task_name(r["stem"])
                              for r in act_rows[:3])
            more = (f" и ещё {len(act_rows) - 3}"
                    if len(act_rows) > 3 else "")
            return jsonify({"ok": False,
                            "error": "удалить нельзя — в теме "
                                     "выполняется или ждёт очереди "
                                     f"задача: {names}{more}. "
                                     "Повторите после её завершения"}), 409
        # остальные карточки темы (note/done) стираются каскадом
        # вместе с ней; прицепленные темы отвязываются — на общую
        # сессию
        for r in db_query("SELECT stem FROM tasks WHERE topic_id=%s",
                          (tid,)):
            drop_failed_task(r["stem"])
        db_exec("UPDATE topics SET session_topic_id=NULL"
                " WHERE session_topic_id=%s", (tid,))
        db_exec("DELETE FROM topic_templates"
                " WHERE project=%s AND topic_id=%s", (p, tid))
        # каскад: привязки инструкций колонки и её cron-расписания
        # (карточки прошлых прогонов уже стёрты выше вместе с темой)
        db_exec("DELETE FROM instr_topic_attach"
                " WHERE project=%s AND topic_id=%s", (p, tid))
        db_exec("DELETE FROM task_schedules"
                " WHERE project=%s AND topic_id=%s", (p, tid))
        db_exec("DELETE FROM topics WHERE id=%s", (tid,))
        return jsonify({"ok": True})
    if act == "reset":
        # «сбросить сессию» чат-колонки «💬 Диалог»: все сообщения
        # темы стираются (как при удалении, но сама колонка живёт)
        # и пин session_id снимается — следующее сообщение стартует
        # новую сессию в том же диалоге
        if not db_query("SELECT 1 FROM topics WHERE id=%s AND chat=1",
                        (tid,)):
            return jsonify({"ok": False,
                            "error": "сброс есть только "
                                     "у чат-колонок"}), 409
        act_rows = db_query(
            "SELECT stem FROM tasks WHERE topic_id=%s"
            " AND status IN ('queued','running') LIMIT 4", (tid,))
        if act_rows:
            names = ", ".join(_task_name(r["stem"])
                              for r in act_rows[:3])
            more = (f" и ещё {len(act_rows) - 3}"
                    if len(act_rows) > 3 else "")
            return jsonify({"ok": False,
                            "error": "сбросить нельзя — в теме "
                                     "выполняется или ждёт очереди "
                                     f"задача: {names}{more}. "
                                     "Повторите после "
                                     "её завершения"}), 409
        for r in db_query("SELECT stem FROM tasks WHERE topic_id=%s",
                          (tid,)):
            drop_failed_task(r["stem"])
        db_exec("UPDATE topics SET session_id=NULL, updated=%s"
                " WHERE id=%s", (time.time(), tid))
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "bad action"}), 400


@app.post("/api/internal/topic")
def _api_topic_int():
    """Агент из задачи: переименовать свою новую тему / создать тему.
    Та же схема авторизации, что у /api/internal/instr."""
    if not _internal_auth():
        abort(403)
    b = _req_json()
    act = (b.get("action") or "").strip()
    if act == "rename":
        tid = int(b.get("id") or 0)
        name = (b.get("name") or "").strip()[:190]
        if not name:
            return jsonify({"ok": False, "error": "пустое имя"}), 400
        if not db_exec("UPDATE topics SET name=%s, updated=%s"
                       " WHERE id=%s", (name, time.time(), tid)):
            return jsonify({"ok": False,
                            "error": "нет такой темы"}), 404
        return jsonify({"ok": True})
    if act == "create":
        u = (b.get("user") or "").strip()
        p = (b.get("project") or "").strip()
        name = (b.get("name") or "").strip()[:190]
        if not p or not name:
            return jsonify({"ok": False,
                            "error": "нужны project и name"}), 400
        db_exec("INSERT INTO topics(project,user,name,created,updated)"
                " VALUES(%s,%s,%s,%s,%s)",
                (p, u, name, time.time(), time.time()))
        new_id = db_query("SELECT LAST_INSERT_ID() AS i")[0]["i"]
        db_exec("UPDATE topics SET sort=id WHERE sort=0 AND id<>%s",
                (new_id,))
        db_exec("UPDATE topics SET sort=%s WHERE id=%s",
                (_topic_append_sort(p), new_id))
        return jsonify({"ok": True, "id": new_id})
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


def drop_failed_task(stem: str) -> None:
    """Стирание упавшей done-задачи (условия проверяет вызывающий):
    запись tasks, kv-метки (tag/opts) и прогресс-файлы."""
    db_exec("DELETE FROM tasks WHERE stem=%s", (stem,))
    for k in (f"tag:{stem}", f"opts:{stem}"):
        db_exec("DELETE FROM kv WHERE k=%s", (k,))
    prog = TASKS_DIR / ".progress"
    for p in ([prog / f"{stem}.out", prog / f"{stem}.json"]
              + list(prog.glob(f"{stem}.attach*"))):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def is_failed_task(row: dict | None) -> bool:
    """Карточка показывает 🔁/🗑 только у done-задачи с ошибкой."""
    return bool(row) and row["status"] == "done" and \
        bool(row["task_status"]) and \
        "exit code: 0" not in (row["task_status"] or "")


@app.post("/api/task/append")
@login_required
def _api_task_append():
    """Дописать текст в карточку-заметку («сказать»): выбранная
    карточка + ввод в композере → POST {stem, text} дописывает
    к tasks.prompt, статус остаётся 'note'."""
    body = _req_json()
    stem = (body.get("stem") or "").strip()
    text = (body.get("text") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "note":
        return jsonify({"ok": False,
                        "error": "дописывать можно только заметку"}), 409
    if not text:
        return jsonify({"ok": False, "error": "пустой текст"}), 400
    if len(text) > 20000:
        return jsonify({"ok": False, "error": "text too long"}), 400
    db_exec("UPDATE tasks SET prompt=CONCAT(prompt,'\\n\\n',%s)"
            " WHERE stem=%s", (text, stem))
    log(f"note {stem} appended +{len(text)} chars")
    return jsonify({"ok": True, "stem": stem})


def _opts_for_column(stem: str, eff: dict) -> None:
    """Заметка уходит в работу со свежими дефолтами ЦЕЛЕВОЙ колонки:
    разовые оверрайды opts.mode/model смываем (не притащить say/
    старую модель), автокоммит ставим из дефолта колонки."""
    try:
        o = json.loads(kv_get(f"opts:{stem}") or "{}")
    except ValueError:
        o = {}
    o.pop("mode", None)
    o.pop("model", None)
    if eff.get("auto_commit") in ("0", "1"):
        o["ac"] = eff["auto_commit"]
    if o:
        kv_set(f"opts:{stem}", json.dumps(o, ensure_ascii=False))
    else:
        db_exec("DELETE FROM kv WHERE k=%s", (f"opts:{stem}",))


@app.post("/api/task/run")
@login_required
def _api_task_run():
    """«▶ начать выполнение» на карточке-заметке: переводит её из
    'note' в 'queued' — дальше её забирает обычная очередь.
    Настройки берутся СВЕЖИЕ из дефолтов её колонки (тема → проект →
    юзерские): разовые оверрайды заметки (opts.mode/model/ac) смываем,
    чтобы не притащить say/старую модель в запуск."""
    stem = (_req_json().get("stem") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "note":
        return jsonify({"ok": False,
                        "error": "запускать можно только заметку"}), 409
    eff = _eff_topic_defaults(row["project"], row["topic_id"])
    rmode = eff.get("reply_mode") if eff.get("reply_mode") in ("ask", "code") \
        else "code"
    db_exec("UPDATE tasks SET status='queued', reply_mode=%s, model=%s"
            " WHERE stem=%s", (rmode, eff.get("model") or None, stem))
    _opts_for_column(stem, eff)
    log(f"note {stem} -> queued (mode={rmode}, "
        f"model={eff.get('model')}, ac={eff.get('auto_commit')})")
    return jsonify({"ok": True, "stem": stem})


@app.post("/api/task/continue")
@login_required
def _api_task_continue():
    """«↻ продолжить» на done-карточке: доделка в той же записи —
    текст дописывается в prompt, задача уходит в queued и резюмит
    ту же сессию темы (--resume по её пину). Старый output не
    трогаем: при записи результата run_task делает CONCAT — новый
    кусок ложится под разделитель, который мы ставим здесь."""
    body = _req_json()
    stem = (body.get("stem") or "").strip()
    text = (body.get("text") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "done":
        return jsonify({"ok": False,
                        "error": "продолжать можно только завершённую"}), 409
    if not text:
        return jsonify({"ok": False, "error": "пустой текст"}), 400
    if len(text) > 20000:
        return jsonify({"ok": False, "error": "text too long"}), 400
    db_exec("UPDATE tasks SET status='queued',"
            " prompt=CONCAT(prompt,'\\n\\n',%s),"
            " output=CONCAT(IFNULL(output,''),'\\n\\n---\\n\\n'),"
            " task_status=NULL, commit_offered=0,"
            " started=NULL, finished=NULL"
            " WHERE stem=%s", (text, stem))
    log(f"task {stem} continued (+{len(text)} chars)")
    return jsonify({"ok": True, "stem": stem})


def _ask_to_work(row: dict) -> None:
    """done-задача «вопрос» → queued code той же записью (условия
    проверил вызывающий): ответ Devin прячем в instr, к промпту
    приписываем «реализуй предложение», вывод копится под
    разделителем, сессия темы резюмится."""
    stem = row["stem"]
    instr = (((row.get("instr") or "")
              + "\n\n## Результат предыдущего ответа Devin\n"
              + (row.get("output") or "").strip()[:6000])
             .strip()[:8000])
    # разовый оверрайд opts.mode='ask' перекрыл бы новый reply_mode —
    # смываем только его (model/ac/attach — те же, что были)
    try:
        o = json.loads(kv_get(f"opts:{stem}") or "{}")
    except ValueError:
        o = {}
    if o.pop("mode", None) is not None:
        if o:
            kv_set(f"opts:{stem}", json.dumps(o, ensure_ascii=False))
        else:
            db_exec("DELETE FROM kv WHERE k=%s", (f"opts:{stem}",))
    db_exec("UPDATE tasks SET status='queued', reply_mode='code',"
            " prompt=CONCAT(%s, prompt), instr=%s,"
            " output=CONCAT(IFNULL(output,''),'\\n\\n---\\n\\n'),"
            " task_status=NULL, commit_offered=0,"
            " started=NULL, finished=NULL WHERE stem=%s",
            ("Давай сделаем по твоему предложению из предыдущего "
             "ответа — реализуй его.\n\nИсходный вопрос: ",
             instr, stem))


@app.post("/api/task/towork")
@login_required
def _api_task_towork():
    """«▶ в работу» на done-задаче-вопросе: та же запись уходит в
    queued уже code-задачей (механика «↻ продолжить») — сессия темы
    резюмится, контекст не теряется, карточек не плодится. Ответ
    Devin копим в instr (скрыто от юзера), перед prompt добавляем
    «реализуй предложение», вывод копится под разделителем."""
    stem = (_req_json().get("stem") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "done":
        return jsonify({"ok": False,
                        "error": "в работу — только завершённую"}), 409
    if (row.get("reply_mode") or "") != "ask":
        return jsonify({"ok": False,
                        "error": "в работу — только из «вопроса»"}), 409
    _ask_to_work(row)
    log(f"task {stem} sent to work (ask -> code)")
    return jsonify({"ok": True, "stem": stem})


@app.post("/api/task/move")
@login_required
def _api_task_move():
    """Перенос карточки по канбану (dnd / «переместить»): смена темы
    и/или места в колонке. Уровни карточек заметка<вопрос<код
    (0/1/2), уровень колонки = её эффективный reply_mode
    (say/ask/code). Повышение уровня = запуск: заметка → queued с
    режимом целевой колонки и её свежими дефолтами; done-вопрос →
    code-колонка — переход «▶ в работу». Равный или понижение —
    просто перестановка (уже идущие задачи тоже только едут).
    Упавшая карточка (done+ошибка), переехавшая в другую тему,
    перенимает её дефолты: model/reply_mode/opts подгоняются под
    колонку — «повторить» потом ставит задачу с настройками новой
    темы, а не теми, с которыми она когда-то запускалась.
    Позиция: above/below — stem соседа, ПОСЛЕ которого / ПЕРЕД
    которым по экрану встаём (sort DESC — свежие сверху); без них —
    наверх колонки."""
    b = _req_json()
    stem = (b.get("stem") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    tkey = str(b.get("topic") if b.get("topic") is not None else "main")
    if tkey in ("", "main"):
        new_tid = None
    elif tkey.isdigit():
        new_tid = int(tkey)
        if not db_query("SELECT 1 FROM topics WHERE id=%s AND project<=>%s",
                        (new_tid, row["project"])):
            return jsonify({"ok": False, "error": "нет такой темы"}), 404
    else:
        return jsonify({"ok": False, "error": "bad topic"}), 400
    proj = row["project"]
    # чат-колонки (topics.chat) — закрытые диалоги: карточки ни в,
    # ни из них не переносятся (v1.8.93)
    chat_ids = {r["id"] for r in db_query(
        "SELECT id FROM topics WHERE project<=>%s AND chat=1",
        (proj,))}
    if new_tid in chat_ids or row["topic_id"] in chat_ids:
        return jsonify({"ok": False,
                        "error": "диалог-колонка закрытая — карточки "
                                 "туда не переносятся"}), 409
    w = "project<=>%s AND topic_id<=>%s AND stem<>%s"
    wp = (proj, new_tid, stem)
    new_sort = None
    above = (b.get("above") or "").strip()
    if above:
        ar = db_query(f"SELECT sort FROM tasks WHERE stem=%s AND {w}",
                      (above,) + wp)
        if ar:
            s_a = float(ar[0]["sort"])
            dn = db_query(f"SELECT MAX(sort) s FROM tasks WHERE {w}"
                          " AND sort<%s", wp + (s_a,))
            s_dn = dn[0]["s"] if dn and dn[0]["s"] is not None else None
            new_sort = s_a - 1 if s_dn is None else (s_a + s_dn) / 2
    below = (b.get("below") or "").strip()
    if new_sort is None and below:
        br = db_query(f"SELECT sort FROM tasks WHERE stem=%s AND {w}",
                      (below,) + wp)
        if br:
            s_b = float(br[0]["sort"])
            up = db_query(f"SELECT MIN(sort) s FROM tasks WHERE {w}"
                          " AND sort>%s", wp + (s_b,))
            s_up = up[0]["s"] if up and up[0]["s"] is not None else None
            new_sort = s_b + 1 if s_up is None else (s_b + s_up) / 2
    if new_sort is None:
        top = db_query(f"SELECT MAX(sort) s FROM tasks WHERE {w}", wp)
        new_sort = (float(top[0]["s"] or 0) + 1) \
            if top and top[0]["s"] is not None else 1.0
    cl = 0 if row["status"] == "note" else \
        (1 if (row.get("reply_mode") or "") == "ask" else 2)
    eff = _eff_topic_defaults(proj, new_tid)
    erm = eff.get("reply_mode") or "code"
    tl = 0 if erm == "say" else (1 if erm == "ask" else 2)
    started = False
    if tl > cl and cl == 0:
        # заметка поднялась уровнем — сразу в работу с режимом и
        # свежими дефолтами целевой колонки (как «▶ начать выполнение»)
        db_exec("UPDATE tasks SET status='queued', reply_mode=%s,"
                " model=%s WHERE stem=%s",
                ("ask" if tl == 1 else "code",
                 eff.get("model") or None, stem))
        _opts_for_column(stem, eff)
        started = True
    elif tl > cl and cl == 1 and row["status"] == "done":
        # done-вопрос в code-колонку — переход «▶ в работу»
        _ask_to_work(row)
        started = True
    if not started and is_failed_task(row) \
            and new_tid != row["topic_id"]:
        # упавшая карточка переехала в другую тему — её «повторить»
        # ставит задачу новой записью в ЭТУ колонку, поэтому она
        # должна унаследовать настройки новой темы, а не старые:
        # подгоняем model/reply_mode под дефолты колонки и смываем
        # разовые оверрайды (ov станет пустым — retry пошлёт чистый
        # topic). В say-колонку задача не перезапускается вообще —
        # там reply_mode оставляем как был
        db_exec("UPDATE tasks SET model=%s, reply_mode=%s WHERE stem=%s",
                (eff.get("model") or None,
                 erm if erm in ("ask", "code")
                 else (row.get("reply_mode") or "code"),
                 stem))
        _opts_for_column(stem, eff)
    db_exec("UPDATE tasks SET topic_id=%s, sort=%s WHERE stem=%s",
            (new_tid, new_sort, stem))
    log(f"task {stem} moved -> topic={new_tid} sort={new_sort} "
        f"(lvl {cl}->{tl}, started={started})")
    return jsonify({"ok": True, "stem": stem, "started": started,
                    "mode": ("ask" if tl == 1 else "code") if started
                            else None})


FMT_INSTR = ("Переоформи текст ниже в аккуратный markdown: заголовки, "
             "списки, таблицы, код-блоки — где уместно. Заодно исправь "
             "орфографические, синтаксические и лексические ошибки, "
             "непонятные слова приведи к нормальному виду. Смысл и язык "
             "не меняй, ничего не додумывай и не дополняй. Верни "
             "ТОЛЬКО markdown — без пояснений и без ограждения ```.\n\n")


def _fmt_run(text: str, workdir: Path, task_user: str, tag: str,
             task_ref: dict | None = None,
             timeout: int | None = None) -> dict:
    """Один синхронный прогон «✨ оформить» агентом — общий
    env-контракт launcher'а задачи (свежая сессия — пин темы и
    --continue не нужны). Прогресс — .progress/<tag>.out, метрики —
    <tag>.json. Возвращает {body, rc, started, finished, export} —
    body уже очищен _clean_task_output."""
    progress_dir = TASKS_DIR / ".progress"
    progress_dir.mkdir(exist_ok=True)
    task_file = progress_dir / f"{tag}.task.txt"
    out_path = progress_dir / f"{tag}.out"
    export = progress_dir / f"{tag}.json"
    task_file.write_text(FMT_INSTR + text, encoding="utf-8")
    env = dict(os.environ, DEVIN_TASK_FILE=str(task_file),
               TASK_STEM=tag,
               DEVIN_MODEL=current_model(),
               DEVIN_WORKDIR=str(workdir),
               DEVIN_CONTINUE="false",
               REPLY_MODE="ask",
               DEVIN_PERMISSION_MODE=(
                   os.environ.get("DEVIN_PERMISSION_MODE")
                   or "dangerous"),
               DEVIN_EXPORT_FILE=str(export),
               GIT_AUTO_COMMIT="false",
               WINDSURF_API_KEY=uset("devin.api_key", task_user,
                                     "WINDSURF_API_KEY"),
               ANTHROPIC_API_KEY=uset("claude.api_key", task_user,
                                      "ANTHROPIC_API_KEY"))
    out_f = open(out_path, "w", errors="replace")
    started_ts = time.time()
    proc = subprocess.Popen(
        [agent_def(task_ref or {"user": task_user})["bin"]], env=env,
        stdout=out_f, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    with _procs_lock:
        _task_procs[tag] = proc
    try:
        proc.wait(timeout=timeout or TASK_TIMEOUT)
        body = (out_path.read_text(errors="replace")
                if out_path.exists() else "")
    except subprocess.TimeoutExpired:
        kill_task(tag)
        proc.wait()
        body = "Ошибка оформления: таймаут"
    finally:
        with _procs_lock:
            _task_procs.pop(tag, None)
        out_f.close()
    return {"body": _clean_task_output(body).strip(),
            "rc": proc.returncode, "started": started_ts,
            "finished": time.time(), "export": export}


def _fmt_worker(stem: str) -> None:
    """Фоновый прогон «✨ оформить»: отдельный devin-task (свежая
    сессия — пин темы и --continue не нужны) переоформляет текст
    заметки в markdown. Результат кладём в tasks.output (status
    остаётся note) — фронт ловит его поллингом и показывает
    превью-диалог. Падения — тоже в output с префиксом «Ошибка
    оформления:», apply их отвергает."""
    fstem = stem + ".fmt"
    try:
        row = task_row(stem) or {}
        tproj = row.get("project")
        task_user = (row.get("user") or _project_owner(tproj)
                     or WEB_ADMIN_USER)
        if tproj and PROJECTS_ROOT and (PROJECTS_ROOT / tproj).is_dir():
            workdir = PROJECTS_ROOT / tproj
        else:
            _, workdir = current_project()
        res = _fmt_run(row.get("prompt") or "", workdir, task_user,
                       fstem, task_ref=row)
        body = res["body"]
        # «✨ Оформить» — тоже прогон Devin: его токены и стоимость
        # считаем в статистику темы заметки (row['topic_id'])
        try:
            fst = agent_def(row)["stats"](
                res["export"], res["started"], res["finished"])
            if fst:
                db_exec("INSERT INTO topic_stats"
                        " (project, topic_id, stem, created, model,"
                        " prompt_tok, cached_tok, completion_tok, cost,"
                        " duration)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (row.get("project"), row.get("topic_id"),
                         fstem, time.time(), fst.get("model"),
                         fst.get("prompt_tokens"),
                         fst.get("cached_tokens"),
                         fst.get("completion_tokens"),
                         _task_cost(fst), fst.get("duration")))
        except Exception as e:
            log(f"topic_stats fmt: {e}")
        if not body:
            body = ("Ошибка оформления: пустой ответ"
                    if res["rc"] == 0
                    else f"Ошибка оформления: exit {res['rc']}")
        elif res["rc"] != 0:
            body = "Ошибка оформления: " + body[:500]
        db_exec("UPDATE tasks SET output=%s WHERE stem=%s"
                " AND status='note'", (body, stem))
    except Exception as e:
        log(f"format {stem} failed: {e}")
        try:
            db_exec("UPDATE tasks SET output=%s WHERE stem=%s"
                    " AND status='note'",
                    (f"Ошибка оформления: {e}", stem))
        except Exception:
            pass
    finally:
        db_exec("DELETE FROM kv WHERE k=%s", (f"fmt:{stem}",))


@app.post("/api/task/edit")
@login_required
def _api_task_edit():
    """Инлайн-редактирование заметки: заменяет её prompt целиком
    (дописывание — отдельный /api/task/append). Только status='note'."""
    body = _req_json()
    stem = (body.get("stem") or "").strip()
    text = (body.get("text") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "note":
        return jsonify({"ok": False,
                        "error": "править можно только заметку"}), 409
    if not text:
        return jsonify({"ok": False, "error": "пустой текст"}), 400
    if len(text) > 20000:
        return jsonify({"ok": False, "error": "text too long"}), 400
    db_exec("UPDATE tasks SET prompt=%s WHERE stem=%s", (text, stem))
    log(f"task {stem} edited ({len(text)} chars)")
    return jsonify({"ok": True})


@app.post("/api/task/format")
@login_required
def _api_task_format():
    """«✨ Оформить» на заметке: фоновый devin-task переоформляет её
    текст в markdown → tasks.output; фронт показывает превью
    «применить/отменить». status остаётся note."""
    stem = (_req_json().get("stem") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "note":
        return jsonify({"ok": False,
                        "error": "оформлять можно только заметку"}), 409
    if kv_get(f"fmt:{stem}"):
        return jsonify({"ok": False, "error": "уже оформляется"}), 409
    kv_set(f"fmt:{stem}", "1")
    threading.Thread(target=_fmt_worker, args=(stem,),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/text/format")
@login_required
def _api_text_format():
    """«✨ оформить» произвольный текст (модалка шаблона): синхронный
    прогон агента в режиме ask — ответ сразу возвращается оформленным
    markdown'ом. В статистику темы не пишется — задачи-строки нет."""
    b = _req_json()
    p = (b.get("project") or "").strip()
    text = (b.get("text") or "").strip()
    if p and not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    if not text:
        return jsonify({"ok": False, "error": "пустой текст"}), 400
    if len(text) > 20000:
        return jsonify({"ok": False, "error": "text too long"}), 400
    u = _current_user()
    if p and PROJECTS_ROOT and (PROJECTS_ROOT / p).is_dir():
        workdir = PROJECTS_ROOT / p
    else:
        _, workdir = current_project()
    tag = f"tplfmt-{int(time.time())}-{secrets.token_hex(3)}"
    try:
        res = _fmt_run(text, workdir, u, tag,
                       task_ref={"project": p or None, "user": u},
                       timeout=300)
    except Exception as e:
        log(f"text format failed: {e}")
        return jsonify({"ok": False, "error": str(e)[:300]}), 502
    body = res["body"]
    if (not body or res["rc"] != 0
            or body.startswith("Ошибка оформления")):
        return jsonify({"ok": False,
                        "error": ("Ошибка оформления: "
                                  + (body or f"exit {res['rc']}"))[:400]}), 502
    return jsonify({"ok": True, "text": body})


@app.post("/api/task/apply")
@login_required
def _api_task_apply():
    """«Применить» оформленный вариант: меняет местами prompt и
    output — оформленное становится текстом заметки, исходник уходит
    в output (повторный apply возвращает его обратно)."""
    stem = (_req_json().get("stem") or "").strip()
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    if row["project"] and not _owns_project(row["project"]):
        abort(403)
    if row["status"] != "note":
        return jsonify({"ok": False,
                        "error": "применять можно к заметке"}), 409
    out = (row["output"] or "").strip()
    if not out or out.startswith("Ошибка оформления"):
        return jsonify({"ok": False,
                        "error": "нет оформленного варианта"}), 409
    db_exec("UPDATE tasks SET prompt=%s, output=%s WHERE stem=%s",
            (out, row["prompt"], stem))
    log(f"task {stem} formatted variant applied")
    return jsonify({"ok": True})


@app.post("/api/task/delete")
@login_required
def _api_task_delete():
    """Web «удалить» на карточке заметки или завершённой задачи
    (успешной или упавшей): стирает запись вместе с прогресс-
    файлами и kv-метками. Активные (queued/running) — только с
    флагом stop (крестик «✕» на пузыре чат-колонки): queued
    стирается как cancel, running — SIGKILL + стирание записи
    сразу (финализатор run_task потом пишет UPDATE в пустоту)."""
    body = _req_json()
    stem = (body.get("stem") or "").strip()
    stop = bool(body.get("stop"))
    row = task_row(stem)
    if not row:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    st = row["status"]
    if st == "queued":
        if not stop:
            return jsonify({"ok": False,
                            "error": "задача в очереди — снимите её "
                                     "или передайте stop"}), 409
        drop_failed_task(stem)
        log(f"web delete removed queued {stem}")
        return jsonify({"ok": True, "stem": stem})
    if st == "running":
        if not stop:
            return jsonify({"ok": False,
                            "error": "задача выполняется — остановите "
                                     "или передайте stop"}), 409
        kill_task(stem)
        drop_failed_task(stem)
        log(f"web delete killed+removed running {stem}")
        return jsonify({"ok": True, "stem": stem})
    if st not in ("note", "done"):
        return jsonify({"ok": False,
                        "error": "удалять можно только заметку или "
                                 "завершённую"}), 409
    drop_failed_task(stem)
    log(f"web delete removed {st} {stem}")
    return jsonify({"ok": True, "stem": stem})


@app.post("/api/task/merge")
@login_required
def _api_task_merge():
    """Заметка на заметку (карточку перетащили прямо на другую
    note-карточку): текст источника дописывается в prompt цели
    новым абзацем, источник стирается. Обе должны быть
    status='note'."""
    body = _req_json()
    src = (body.get("from") or "").strip()
    dst = (body.get("to") or "").strip()
    if not src or not dst or src == dst:
        return jsonify({"ok": False,
                        "error": "нужны две разные заметки"}), 400
    a, b = task_row(src), task_row(dst)
    if not a or not b:
        return jsonify({"ok": False, "error": "нет такой задачи"}), 404
    for r in (a, b):
        if r["project"] and not _owns_project(r["project"]):
            abort(403)
        if r["status"] != "note":
            return jsonify({"ok": False,
                            "error": "объединять можно только "
                                     "заметки"}), 409
    text = (a.get("prompt") or "").strip()
    if text:
        db_exec("UPDATE tasks SET prompt=CONCAT(prompt,'\\n\\n',%s)"
                " WHERE stem=%s", (text, dst))
    drop_failed_task(src)
    log(f"note {src} merged into {dst} (+{len(text)} chars)")
    return jsonify({"ok": True, "stem": dst, "from": src})


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
    local = bool(body.get("local"))
    if not re.fullmatch(r"[A-Za-z0-9._-]+", folder or ""):
        return jsonify({"ok": False, "error":
                        "имя папки: только a-z, 0-9, точка, _ и -"}), 400
    if not PROJECTS_ROOT or not PROJECTS_ROOT.is_dir():
        return jsonify({"ok": False, "error":
                        "мультирежим не настроен (DEVIN_PROJECTS_DIR)"}), 400
    if (PROJECTS_ROOT / folder).exists():
        return jsonify({"ok": False,
                        "error": f"папка {folder} уже существует"}), 409
    dest = PROJECTS_ROOT / folder
    if local:
        # «локальный репозиторий» (v1.8.92): без клона — просто
        # папка + git init и пустой первый коммит, чтобы бар ветки
        # сразу видел main и HEAD существовал
        dest.mkdir()
        out_lines, ok = [], True
        for args in (("init", "-b", "main"),
                     ("-c", "user.name=devin",
                      "-c", "user.email=devin@local",
                      "commit", "--allow-empty", "-m", "init")):
            rc, o = _git(dest, *args)
            out_lines.append(o)
            if rc != 0:
                ok = False
                break
        out = "\n".join(x for x in out_lines if x)
        if not ok:
            shutil.rmtree(dest, ignore_errors=True)
            return jsonify({"ok": False,
                            "error": out[-4000:]
                                     or "git init failed"}), 500
        db_exec("INSERT IGNORE INTO project_owner(name, owner)"
                " VALUES(%s,%s)", (folder, _current_user()))
        wsel = int(body.get("ws") or 0)
        if wsel in [w["id"] for w in _user_ws(_current_user())]:
            db_exec("INSERT IGNORE INTO project_ws(user, name, ws_id)"
                    " VALUES(%s,%s,%s)",
                    (_current_user(), folder, wsel))
        log(f"web added LOCAL project {folder} "
            f"(owner {_current_user()})")
        return jsonify({"ok": True, "folder": folder,
                        "output": out[-4000:]})
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
