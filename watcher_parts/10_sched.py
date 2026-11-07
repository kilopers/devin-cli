# --- периодические задачи колонок (cron) --------------------------------
# Расписание живёт в task_schedules и привязано к колонке канбана
# (topic_id NULL = «главная»). Каждое срабатывание ставит НОВУЮ карточку
# обычной очередью (дефолты колонки: модель/режим/автокоммит/инструкции),
# связь карточка→расписание — tasks.sched_id. Опция autoclean: после
# завершения нового прогона карточки прошлых прогонов стираются — в
# колонке виден только последний запуск.

def _cron_fields(expr: str) -> list | None:
    """5-полевой cron «мин час дм мес дн» -> [(is_star, set), …] или None.
    Синтаксис: * */n a a-b a-b/n и списки через запятую; день недели
    0-7 (0 и 7 — воскресенье)."""
    parts = expr.split()
    if len(parts) != 5:
        return None
    out = []
    for i, (lo, hi) in enumerate(((0, 59), (0, 23), (1, 31), (1, 12),
                                  (0, 7))):
        vals = set()
        for tok in parts[i].split(","):
            m = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", tok)
            if not m:
                return None
            body, step = m.group(1), int(m.group(2) or 1)
            if body == "*":
                a, b = lo, hi
            else:
                ab = body.split("-", 1)
                a, b = int(ab[0]), int(ab[-1])
                # «n/step» без правого края — от n до максимума поля
                if len(ab) == 1 and step > 1:
                    b = hi
            if a < lo or b > hi or a > b:
                return None
            vals.update(range(a, b + 1, step))
        if i == 4 and 7 in vals:      # день недели: 7 = воскресенье
            vals.add(0)
            vals.discard(7)
        if not vals:
            return None
        out.append((parts[i] == "*", vals))
    return out


def _cron_next(expr: str, after: float) -> float | None:
    """Ближайший момент срабатывания строго позже `after` (unix ts,
    локальное время — как у системного cron). Если ограничены и «день
    месяца», и «день недели» — классическое ИЛИ; иначе И (поле «*»
    совпадает всегда). Горизонт ~2 года, дальше — None."""
    fs = _cron_fields(expr)
    if fs is None:
        return None
    (_, mins), (_, hours), (d_star, doms), (_, mons), (w_star, dows) = fs
    both = not d_star and not w_star
    t = time.localtime(after)
    day0 = time.mktime((t.tm_year, t.tm_mon, t.tm_mday,
                        0, 0, 0, -1, -1, -1))
    for _ in range(750):
        d = time.localtime(day0)
        dom_ok = d.tm_mday in doms
        dow_ok = ((d.tm_wday + 1) % 7) in dows    # вс=0 … сб=6
        if d.tm_mon in mons and ((dom_ok or dow_ok) if both
                                 else (dom_ok and dow_ok)):
            for hh in sorted(hours):
                for mm in sorted(mins):
                    ts = time.mktime((d.tm_year, d.tm_mon, d.tm_mday,
                                      hh, mm, 0, -1, -1, -1))
                    if ts > after:
                        return ts
        day0 += 86400
    return None


def _sched_fire(sc: dict) -> str:
    """Прогон расписания: ставит задачу в колонку обычной очередью со
    всеми дефолтами темы и привязывает её (tasks.sched_id прямо в
    INSERT). Стем задачи строится на секундах — два срабатывания в одну
    секунду на одном проекте/юзере слиплись бы в одну запись
    (ON DUPLICATE): проверяем победивший sched_id и при чужом ждём
    следующую секунду."""
    # карточка-якорь (v2.1.1): прогон ставится в колонку, где якорь
    # сейчас лежит, с его актуальным текстом; якоря нет (карточку
    # удалили — расписание стирается каскадом, это страховка) —
    # фолбэк на поля расписания
    anchor = task_row(sc["stem"]) if sc.get("stem") else None
    tid = anchor["topic_id"] if anchor else sc.get("topic_id")
    prompt = (anchor["prompt"] if anchor else "") or sc["prompt"]
    # дефолты колонки в скоупе «без юзера»: reply_mode задачи идёт
    # строго из настроек колонки → проекта → глобальных
    eff = _eff_topic_defaults(sc["project"], tid, scope="")
    mode = eff.get("reply_mode")
    stem = ""
    for _ in range(5):
        stem = enqueue_task(
            prompt, project=sc["project"], prefix="cron",
            topic_id=tid, user=sc.get("user") or None,
            sched_id=sc["id"],
            override_mode=mode if mode in ("ask", "code", "say")
                          else None).removesuffix(".txt")
        r = db_query("SELECT sched_id FROM tasks WHERE stem=%s", (stem,))
        if r and r[0].get("sched_id") == sc["id"]:
            break                        # наша запись
        stem = ""                        # стем занят чужой — ждём
        time.sleep(1.05)
    if stem:
        # якорь переползает на свежую карточку — колокольчик всегда
        # горит на последней, topic_id расписания следует за колонкой
        db_exec("UPDATE task_schedules SET last_run=%s, last_stem=%s,"
                " stem=%s, topic_id=%s WHERE id=%s",
                (time.time(), stem, stem, tid, sc["id"]))
        log(f"sched #{sc['id']} fired -> {stem}")
    else:
        log(f"sched #{sc['id']}: stem занят 5 раз подряд — пропуск")
    return stem


def _sched_autoclean(sched_id: int, keep_stem: str) -> None:
    """Опция «удалять предыдущую»: новый прогон завершился УСПЕШНО —
    стираем карточки прошлых прогонов этого расписания (done/note),
    в колонке остаётся только последний запуск. При падении нового
    прогона вызова нет — предыдущая хорошая карточка сохраняется.
    Вызов — из run_task."""
    sc = db_query("SELECT autoclean FROM task_schedules WHERE id=%s",
                  (sched_id,))
    if not sc or not sc[0]["autoclean"]:
        return
    rows = db_query("SELECT stem FROM tasks WHERE sched_id=%s"
                    " AND stem<>%s AND status IN ('done','note')",
                    (sched_id, keep_stem))
    for r in rows:
        drop_failed_task(r["stem"])
    if rows:
        log(f"sched #{sched_id} autoclean: убрано карточек "
            f"{len(rows)}")


def sched_cron(interval: int = 30) -> None:
    """Планировщик периодических задач (daemon-поток из main()): раз в
    `interval` секунд запускает просроченные расписания и пересчитывает
    next_run — пропущенные за простоем прогоны догоняются одним
    запуском, не серией."""
    while True:
        try:
            now = time.time()
            for sc in db_query(
                    "SELECT * FROM task_schedules WHERE enabled=1"
                    " AND next_run IS NOT NULL AND next_run<=%s"
                    " ORDER BY next_run LIMIT 20", (now,)):
                try:
                    _sched_fire(sc)
                except Exception as e:
                    log(f"sched #{sc['id']} fire: {e}")
                db_exec("UPDATE task_schedules SET next_run=%s"
                        " WHERE id=%s",
                        (_cron_next(sc["cron"], now), sc["id"]))
        except Exception as e:
            log(f"sched cron: {e}")
        time.sleep(interval)


# --- веб-API расписаний ---------------------------------------------------

@app.get("/api/sched")
@login_required
def _api_sched_get():
    """Расписания колонки: topic=main|id|all (фильтр как у задач)."""
    p = (request.args.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403
    tv = (request.args.get("topic") or "main").strip()
    sv = (request.args.get("stem") or "").strip()
    sql, params = ("SELECT * FROM task_schedules WHERE project=%s",
                   [p])
    if sv:
        sql += " AND stem=%s"
        params.append(sv)
    elif tv == "main":
        sql += " AND topic_id IS NULL"
    elif tv.isdigit():
        sql += " AND topic_id=%s"
        params.append(int(tv))
    rows = db_query(sql + " ORDER BY id", params)
    return jsonify({"ok": True, "schedules": [
        {"id": r["id"], "topic_id": r["topic_id"], "stem": r["stem"],
         "prompt": r["prompt"], "cron": r["cron"],
         "enabled": bool(r["enabled"]),
         "autoclean": bool(r["autoclean"]),
         "next_run": r["next_run"], "last_run": r["last_run"],
         "created": int(r["created"])} for r in rows]})


@app.post("/api/sched")
@login_required
def _api_sched_set():
    """create/update/delete/fire расписания. cron — 5 полей
    «мин час день мес дн», текст — промпт порождаемой задачи."""
    b = _req_json()
    u = _current_user()
    act = (b.get("action") or "").strip()
    p = (b.get("project") or "").strip()
    if not p or not _owns_project(p):
        return jsonify({"ok": False, "error": "нет доступа"}), 403

    def _cron_err():
        return jsonify({"ok": False,
                        "error": "не понимаю cron — нужны 5 полей: "
                                 "мин час день мес дн "
                                 "(напр. «*/15 * * * *»)"}), 400

    if act == "create":
        sv = (b.get("stem") or "").strip()
        anchor = None
        if sv:
            # расписание на карточке (v2.1.1): текст и колонка — из
            # карточки-якоря, она же метка «периодическая» в ленте
            anchor = task_row(sv)
            if not anchor:
                return jsonify({"ok": False,
                                "error": "нет такой задачи"}), 404
            if db_query("SELECT 1 FROM task_schedules WHERE stem=%s",
                        (sv,)):
                return jsonify({"ok": False,
                                "error": "у карточки уже есть "
                                         "расписание"}), 409
        text = ((anchor["prompt"] if anchor else "")
                or (b.get("prompt") or "")).strip()
        if not text:
            return jsonify({"ok": False, "error": "пустой текст"}), 400
        if len(text) > 20000:
            return jsonify({"ok": False, "error": "text too long"}), 400
        tv = str(b.get("topic") or "main").strip()
        tid = anchor["topic_id"] if anchor else (
            None if tv in ("", "main") else (
                int(tv) if tv.isdigit() else -1))
        if tid == -1 or (tid is not None and not db_query(
                "SELECT 1 FROM topics WHERE id=%s AND project=%s",
                (tid, p))):
            return jsonify({"ok": False, "error": "нет такой темы"}), 404
        cron = (b.get("cron") or "").strip()[:60]
        nr = _cron_next(cron, time.time())
        if nr is None:
            return _cron_err()
        db_exec("INSERT INTO task_schedules(project,topic_id,user,"
                "prompt,cron,enabled,autoclean,next_run,stem,created)"
                " VALUES(%s,%s,%s,%s,%s,1,%s,%s,%s,%s)",
                (p, tid, u, text, cron, 1 if b.get("autoclean") else 0,
                 nr, sv or None, time.time()))
        sid = db_query("SELECT LAST_INSERT_ID() AS i")[0]["i"]
        if anchor:
            # якорь — первая карточка серии: autoclean уберёт и её,
            # когда завершится первый прогон
            db_exec("UPDATE tasks SET sched_id=%s WHERE stem=%s",
                    (sid, sv))
        log(f"sched #{sid} created in {p} topic={tid or 'main'} "
            f"'{cron}'")
        return jsonify({"ok": True, "id": sid, "next_run": nr})
    sid = int(b.get("id") or 0)
    sv = (b.get("stem") or "").strip()
    if sv:
        row = db_query("SELECT * FROM task_schedules"
                       " WHERE stem=%s AND project=%s", (sv, p))
    else:
        row = db_query("SELECT * FROM task_schedules"
                       " WHERE id=%s AND project=%s", (sid, p))
    if not row:
        return jsonify({"ok": False,
                        "error": "нет такого расписания"}), 404
    sc = row[0]
    sid = sc["id"]
    if act == "update":
        sets, vals = [], []
        if "prompt" in b:
            t2 = (b.get("prompt") or "").strip()
            if not t2:
                return jsonify({"ok": False,
                                "error": "пустой текст"}), 400
            if len(t2) > 20000:
                return jsonify({"ok": False,
                                "error": "text too long"}), 400
            sets.append("prompt=%s")
            vals.append(t2)
        if "cron" in b:
            cron = (b.get("cron") or "").strip()[:60]
            nr = _cron_next(cron, time.time())
            if nr is None:
                return _cron_err()
            sets += ["cron=%s", "next_run=%s"]
            vals += [cron, nr]
        for k in ("enabled", "autoclean"):
            if k in b:
                sets.append(f"{k}=%s")
                vals.append(1 if b.get(k) else 0)
        # включили расписание — отсчёт заново от текущего момента
        # (старый next_run мог давно протухнуть и выстрелить догонкой)
        if b.get("enabled") and "next_run=%s" not in sets:
            sets.append("next_run=%s")
            vals.append(_cron_next(sc["cron"], time.time()))
        if not sets:
            return jsonify({"ok": True})
        vals.append(sid)
        db_exec(f"UPDATE task_schedules SET {', '.join(sets)}"
                " WHERE id=%s", vals)
        return jsonify({"ok": True})
    if act == "fire":
        # «запустить сейчас» — внеочередной прогон, ритм расписания
        # пересчитывается от текущего момента
        _sched_fire(dict(sc))
        db_exec("UPDATE task_schedules SET next_run=%s WHERE id=%s",
                (_cron_next(sc["cron"], time.time()), sid))
        return jsonify({"ok": True})
    if act == "delete":
        # карточки серии остаются обычными задачами — метку снимаем
        db_exec("UPDATE tasks SET sched_id=NULL WHERE sched_id=%s",
                (sid,))
        db_exec("DELETE FROM task_schedules WHERE id=%s", (sid,))
        log(f"sched #{sid} deleted ({p})")
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "bad action"}), 400
