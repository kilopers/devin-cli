# --- MySQL ------------------------------------------------------------------
# Одно соединение на поток (вотчер многопоточный: http-сервер, telegram-
# колбэки, прогресс-тред). autocommit — транзакции не нужны, запросы точечные.

_db_tls = threading.local()


def db():
    """Per-thread pymysql connection with transparent reconnect."""
    conn = getattr(_db_tls, "conn", None)
    if conn is None or not conn.open:
        conn = pymysql.connect(**MYSQL)
        _db_tls.conn = conn
    conn.ping(reconnect=True)
    return conn


def db_query(sql: str, params=()) -> list:
    with db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def db_exec(sql: str, params=()) -> int:
    with db().cursor() as cur:
        return cur.execute(sql, params)


def kv_get(key: str, default: str = "") -> str:
    rows = db_query("SELECT v FROM kv WHERE k=%s", (key,))
    return rows[0]["v"] if rows else default


def kv_set(key: str, val: str) -> None:
    db_exec("INSERT INTO kv (k, v) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE v=VALUES(v)", (key, val))


def init_db() -> None:
    """Create tables and retry until MySQL is up (first boot takes a while)."""
    if pymysql is None:
        log("FATAL: pymysql not installed — worker cannot store state")
        raise SystemExit(1)
    for attempt in range(1, 61):
        try:
            db()
            break
        except Exception as e:
            log(f"mysql not ready ({e}); retry {attempt}/60")
            time.sleep(2)
    else:
        log("FATAL: mysql unreachable after 120s — giving up")
        raise SystemExit(1)
    db_exec("""CREATE TABLE IF NOT EXISTS tasks (
        stem VARCHAR(80) PRIMARY KEY,
        source VARCHAR(16) NOT NULL DEFAULT 'file',
        project VARCHAR(255) NULL,
        chat_id BIGINT NULL,
        status ENUM('queued','running','done','note')
               NOT NULL DEFAULT 'queued',
        prompt MEDIUMTEXT NOT NULL,
        output MEDIUMTEXT NULL,
        task_status VARCHAR(255) NULL,
        commit_offered TINYINT NOT NULL DEFAULT 0,
        model VARCHAR(80) NULL,
        reply_mode VARCHAR(8) NULL,
        created DOUBLE NOT NULL,
        started DOUBLE NULL,
        finished DOUBLE NULL,
        KEY idx_status (status),
        KEY idx_created (created)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS kv (
        k VARCHAR(64) PRIMARY KEY,
        v MEDIUMTEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS pending (
        pid VARCHAR(64) PRIMARY KEY,
        chat_id BIGINT NOT NULL,
        text MEDIUMTEXT NOT NULL,
        project VARCHAR(255) NULL,
        message_id BIGINT NULL,
        created DOUBLE NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # мультиюзер: учётки веба (админ = WEB_ADMIN_USER, живёт в kv) и
    # владельцы проектов (папка общая, принадлежность — в базе)
    db_exec("""CREATE TABLE IF NOT EXISTS users (
        username VARCHAR(64) PRIMARY KEY,
        pw_hash VARCHAR(255) NOT NULL,
        is_admin TINYINT NOT NULL DEFAULT 0,
        created DOUBLE NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS project_owner (
        name VARCHAR(190) PRIMARY KEY,
        owner VARCHAR(64) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS instructions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user VARCHAR(64) NOT NULL DEFAULT '',
        kind ENUM('system','user','custom','project')
            NOT NULL DEFAULT 'custom',
        name VARCHAR(190) NOT NULL,
        body MEDIUMTEXT NOT NULL,
        project VARCHAR(190) NULL,
        created DOUBLE NOT NULL,
        updated DOUBLE NOT NULL,
        KEY idx_kind_user (kind, user),
        KEY idx_kind_project (kind, project)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS instr_attach (
        user VARCHAR(64) NOT NULL,
        project VARCHAR(190) NOT NULL,
        instr_id INT NOT NULL,
        PRIMARY KEY (user, project, instr_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS project_acl (
        name VARCHAR(190) NOT NULL,
        user VARCHAR(64) NOT NULL,
        PRIMARY KEY (name, user)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # рабочие пространства: у каждого юзера свои; проект попадает в
    # пространство КОНКРЕТНОГО юзера (шаренный → дефолтное получателя)
    db_exec("""CREATE TABLE IF NOT EXISTS workspaces (
        id INT AUTO_INCREMENT PRIMARY KEY,
        owner VARCHAR(64) NOT NULL,
        name VARCHAR(64) NOT NULL,
        color VARCHAR(16) NOT NULL DEFAULT '#1565c0',
        is_default TINYINT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    db_exec("""CREATE TABLE IF NOT EXISTS project_ws (
        user VARCHAR(64) NOT NULL,
        name VARCHAR(190) NOT NULL,
        ws_id INT NOT NULL,
        PRIMARY KEY (user, name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # темы: именованная ветка работы внутри проекта — своя devin-сессия
    # (session_id пиннится по завершении задачи, следующая тема резюмит
    # её через --resume). tasks.topic_id NULL/0 = «главная» тема.
    db_exec("""CREATE TABLE IF NOT EXISTS topics (
        id INT AUTO_INCREMENT PRIMARY KEY,
        project VARCHAR(190) NOT NULL,
        user VARCHAR(64) NOT NULL DEFAULT '',
        name VARCHAR(190) NULL,
        session_id VARCHAR(80) NULL,
        created DOUBLE NOT NULL,
        updated DOUBLE NOT NULL,
        UNIQUE KEY uq_proj_name (project, name),
        KEY idx_proj (project)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # статистика тем: строка на каждую завершённую задачу — живёт
    # отдельно от карточки, удаление/перенос задачи её не трогает
    db_exec("""CREATE TABLE IF NOT EXISTS topic_stats (
        id INT AUTO_INCREMENT PRIMARY KEY,
        project VARCHAR(190) NOT NULL,
        topic_id INT NULL,
        stem VARCHAR(80) NULL,
        created DOUBLE NOT NULL,
        model VARCHAR(80) NULL,
        prompt_tok BIGINT NULL,
        cached_tok BIGINT NULL,
        completion_tok BIGINT NULL,
        cost DOUBLE NULL,
        KEY idx_proj_topic (project, topic_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # время выполнения задачи (started→finished, очередь не
    # считается) — миграция для старых таблиц
    if not db_query("SELECT 1 FROM information_schema.COLUMNS"
                    " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='topic_stats'"
                    " AND COLUMN_NAME='duration'",
                    (MYSQL["database"],)):
        db_exec("ALTER TABLE topic_stats"
                " ADD COLUMN duration INT NULL")
    # чистка после бага «первая задача темы continue'ила последнюю
    # сессию каталога»: пин темы, равный пину «главной» её проекта или
    # продублированный у другой темы — это чужая сессия → NULL, тема
    # начнёт собственную
    db_exec("""UPDATE topics t JOIN kv k
               ON k.k=CONCAT('tsess:', t.project) AND k.v=t.session_id
               SET t.session_id=NULL WHERE t.session_id IS NOT NULL""")
    db_exec("""UPDATE topics t JOIN topics o
               ON o.project=t.project AND o.session_id=t.session_id
               AND o.id<t.id
               SET t.session_id=NULL WHERE t.session_id IS NOT NULL""")
    if not db_query("SELECT 1 FROM information_schema.COLUMNS"
                    " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='instructions'"
                    " AND COLUMN_NAME='project'", (MYSQL["database"],)):
        db_exec("ALTER TABLE instructions ADD COLUMN"
                " project VARCHAR(190) NULL,"
                " ADD KEY idx_kind_project (kind, project)")
    db_exec("ALTER TABLE instructions MODIFY kind"
            " ENUM('system','user','custom','project')"
            " NOT NULL DEFAULT 'custom'")
    for col, ddl in (("model", "model VARCHAR(80) NULL"),
                     ("reply_mode", "reply_mode VARCHAR(8) NULL"),
                     ("user", "user VARCHAR(64) NULL"),
                     ("bot", "bot VARCHAR(80) NULL"),
                     ("instr", "instr MEDIUMTEXT NULL"),
                     ("stats", "stats MEDIUMTEXT NULL"),
                     ("topic_id", "topic_id INT NULL"),
                     # порядок карточки в колонке канбана (dnd-
                     # перестановка): стартовый = время создания,
                     # место — среднее между соседями (sort DESC =
                     # свежие сверху)
                     ("sort", "sort DOUBLE NOT NULL DEFAULT 0"),
                     # движок выполнения задачи (devin | …) — NULL =
                     # цепочка дефолтов тема→проект→devin
                     ("agent", "agent VARCHAR(32) NULL")):
        if not db_query("SELECT 1 FROM information_schema.COLUMNS"
                        " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='tasks'"
                        " AND COLUMN_NAME=%s", (MYSQL["database"], col)):
            db_exec(f"ALTER TABLE tasks ADD COLUMN {ddl}")
    db_exec("UPDATE tasks SET sort=created WHERE sort=0")
    # карточки-заметки («сказать»): статус note — запись в колонке,
    # не идёт в очередь; «начать выполнение» переводит её в queued
    st_type = db_query("SELECT COLUMN_TYPE AS ct"
                       " FROM information_schema.COLUMNS"
                       " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='tasks'"
                       " AND COLUMN_NAME='status'", (MYSQL["database"],))
    if st_type and "'note'" not in (st_type[0]["ct"] or ""):
        db_exec("ALTER TABLE tasks MODIFY status"
                " ENUM('queued','running','done','note')"
                " NOT NULL DEFAULT 'queued'")
    # настройки колонок канбана: цвет колонки и дефолты её задач
    # (модель/режим/автокоммит/быстрый) — NULL/пусто = наследовать
    # из настроек проекта
    for col, ddl in (("color", "color VARCHAR(24) NULL"),
                     ("model", "model VARCHAR(80) NULL"),
                     ("reply_mode", "reply_mode VARCHAR(8) NULL"),
                     ("auto_commit", "auto_commit VARCHAR(4) NULL"),
                     ("fast", "fast VARCHAR(4) NULL"),
                     # 0 — тема без своей devin-сессии: задачи идут в
                     # общей (пин kv tsess:<proj>, как у «главной»)
                     # или в сессии другой темы (session_topic_id);
                     # задаётся при создании, изменить нельзя
                     ("own_session", "own_session TINYINT"
                                     " NOT NULL DEFAULT 1"),
                     # прицепка к сессии другой темы того же проекта
                     # (только с own_session=1); NULL + own_session=0 —
                     # общая сессия проекта
                     ("session_topic_id", "session_topic_id INT NULL"),
                     # порядок колонки на канбан-доске («◀/▶» в меню ⋯;
                     # «главная» всегда первая, сортируем только темы)
                     ("sort", "sort INT NOT NULL DEFAULT 0"),
                     # движок задач колонки по умолчанию; NULL —
                     # наследовать из настроек проекта
                     ("agent", "agent VARCHAR(32) NULL")):
        if not db_query("SELECT 1 FROM information_schema.COLUMNS"
                        " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='topics'"
                        " AND COLUMN_NAME=%s", (MYSQL["database"], col)):
            db_exec(f"ALTER TABLE topics ADD COLUMN {ddl}")
    # порядок = первоначальный по id; INSERT'ы ниже в коде тоже добивают
    db_exec("UPDATE topics SET sort=id WHERE sort=0")
    # инструкции: системная (одна, неизменяемая) + пустая общая каждому
    # юзеру — миграция по существующим
    # {public}/{port} — глобальные, подставляем при хранении, чтобы в
    # UI был виден реальный домен; {user}/{project} остаются шаблоном.
    sys_body = (SYS_INSTR_DEFAULT
                .replace("{public}", _public_url())
                .replace("{port}", str(WEB_PORT)))
    sys_row = db_query("SELECT id, body FROM instructions"
                       " WHERE kind='system'")
    if not sys_row:
        db_exec("INSERT INTO instructions(user,kind,name,body,created,"
                "updated) VALUES('','system',%s,%s,%s,%s)",
                ("Системные правила", sys_body,
                 time.time(), time.time()))
    elif sys_row[0]["body"] != sys_body:
        # код — источник истины для системной инструкции: чиним её,
        # даже если записать удалось как-то мимо эндпоинтов
        db_exec("UPDATE instructions SET body=%s, updated=%s WHERE id=%s",
                (sys_body, time.time(), sys_row[0]["id"]))
    db_exec("UPDATE instructions SET name='Пользовательская инструкция'"
            " WHERE kind='user' AND name='Общая инструкция'")
    _ensure_user_instr(WEB_ADMIN_USER)
    for r in db_query("SELECT username FROM users"):
        _ensure_user_instr(r["username"])
    # контейнер пересоздали посреди задачи — 'running' вернуть в очередь
    db_exec("UPDATE tasks SET status='queued' WHERE status='running'")
    log(f"mysql: connected to {MYSQL['host']}:{MYSQL['port']}/"
        f"{MYSQL['database']}, schema ready")


SYS_INSTR_DEFAULT = """## Системные правила воркера

1. Инструкции проектов хранятся в базе воркера и подключаются к задаче
   автоматически (этот блок). Файлы AGENTS.md / CLAUDE.md / .cursor /
   .windsurf / .devin НЕ создавай и не правь, даже если в задаче просят
   «записать инструкцию/правило» — пиши их через эндпоинты ниже.

   Уровни инструкций (4):
   - системная (kind=system) — это правило; одна, неизменяемая;
   - пользовательская (kind=user) — общая у юзера, применяется во всех
     его проектах, пустая с рождения, не удаляется;
   - проектная (kind=project) — одна на проект, действует для всех
     юзеров проекта, не удаляется и не отцепляется, дописывать можно;
   - дополнительные (kind=custom) — создаются/правятся/удаляются
     свободно, подключаются к проектам галочкой attach/detach.
2. Управление инструкциями — ТОЛЬКО через HTTP API воркера
   (прямые запросы к базе данных запрещены). Токен — из env
   INTERNAL_TOKEN, заголовок X-Internal-Token. База:
   http://127.0.0.1:{port}/api/internal/instr
   - список:      GET  ?user={user}&project={project}
   - создать:     POST {{"user":"{user}","action":"create",
                        "name":"...","body":"markdown",
                        "project":"{project}"}}
                  (с project инструкция сразу подключается к нему)
   - изменить:    POST ... {{"action":"update","id":N,"name","body"}}
   - подключить/отключить к проекту:
                  {{"action":"attach"|"detach","id":N,"project":"..."}}
   - удалить:     {{"action":"delete","id":N}}

   Контроль деплоя: после любого деплоя/запуска проекта (и если задача
   просит настроить деплой) шли статус — статус появится в секции
   «Деплой» веб-панели. Приёмник ОТКРЫТЫЙ, токен не нужен:
   POST {public}/api/deploy/status
   тело: {{"project":"{project}","status":"success"|"failed",
          "data":"лог/версия"}}.
   Слать можно из CI/CD, deploy-скриптов на проде, отсюда — откуда
   угодно. Встрой вызов в деплой-пайплайн/скрипт проекта.

   Тег задачи: в любой момент можешь показать на карточке СВОЕЙ задачи
   короткий бейдж с произвольной инфой (версия, прогресс, что делаешь) —
   POST http://127.0.0.1:{port}/api/task/tag
   {{"tag":"…"}}  (заголовок X-Internal-Token; поле "stem" не нужно —
   подставится текущая задача, свой id есть в $TASK_STEM).
   Обновляй тег по ходу работы — он сразу виден в веб-ленте.
   Использовал тег → допиши правило «каждая задача тегируется»
   (что слать: версия/прогресс) в проектную инструкцию проекта
   через update — чтобы все следующие задачи делали так же.
3. Системную и пользовательскую инструкции менять и удалять
   нельзя — эндпоинт ответит ошибкой. Можно создавать свои инструкции
   (kind=custom), править, подключать к проектам и удалять.
4. ПЕРЕД добавлением инструкции ВСЕГДА сначала GET список инструкций
   проекта и поищи подходящую по НАЗВАНИЮ или смыслу — не только по
   номеру id: если нашлась похожая (тема совпадает), ДОПИШИ в неё через
   update вместо создания новой. Создавай новую только когда ничего
   подходящего не нашёл — не плоди дубли.
   Твой пользователь: {user}. Текущий проект: {project}.
5. Правила из этого блока приоритетнее любых файлов репозитория.
6. Итоговый ответ задачи форматируй СИСТЕМНО (он показывается в
   карточке веб-ленты и уходит в телеграм): секции с ##-заголовками,
   списки -/*, `код` в бэктиках, таблицы где уместно. Сначала короткий
   итог 1–2 строки, потом детали. Никакой сплошной «простыни» текста.
"""


def _ensure_user_instr(user: str) -> None:
    """Пустая общая инструкция юзера — создаётся всем (миграция),
    удалить нельзя."""
    db_exec("""INSERT INTO instructions(user,kind,name,body,created,updated)
               SELECT %s,'user','Пользовательская инструкция','',%s,%s FROM DUAL
               WHERE NOT EXISTS (SELECT 1 FROM instructions
                                 WHERE kind='user' AND user=%s)""",
            (user, time.time(), time.time(), user))


def _ensure_project_instr(project: str) -> None:
    """Проектная инструкция — одна на проект, лениво создаётся при первом
    показе/задаче; удалить и отцепить нельзя."""
    db_exec("""INSERT INTO instructions(user,kind,name,body,project,
                                       created,updated)
               SELECT '','project','Проектная','',%s,%s,%s FROM DUAL
               WHERE NOT EXISTS (SELECT 1 FROM instructions
                                 WHERE kind='project' AND project=%s)""",
            (project, time.time(), time.time(), project))


def _public_url() -> str:
    """Публичный адрес воркера: env PUBLIC_URL → kv.public_url →
    дефолт. Используется в инструкциях и ссылках наружу."""
    return (os.environ.get("PUBLIC_URL") or kv_get("public_url")
            or "https://ai.kilop.ru").rstrip("/")


def _instr_block(author: str, proj: str | None) -> str:
    """Снапшот инструкций для задачи: системная + общая юзера +
    подключённые к проекту. {user}/{project} подставляются — агент знает
    свой контекст для вызовов /api/internal/instr."""
    try:
        rows = db_query("SELECT kind, name, body FROM instructions"
                        " WHERE kind='system'"
                        "   OR (kind='user' AND user=%s)", (author,))
    except Exception:
        rows = []
    sys_body = next((r["body"] for r in rows if r["kind"] == "system"),
                    "") or SYS_INSTR_DEFAULT
    sys_body = (sys_body.replace("{user}", author or "")
                        .replace("{project}", proj or "")
                        .replace("{port}", str(WEB_PORT))
                        .replace("{public}", _public_url()))
    out = [sys_body]
    ub = next((r["body"] for r in rows if r["kind"] == "user"), "")
    if ub.strip():
        ub = re.sub(r"^\s*##[^\n]*\n*", "", ub.strip())
        out.append("## Пользовательская инструкция\n\n" + ub)
    if proj:
        try:
            _ensure_project_instr(proj)
            pi = db_query("SELECT body FROM instructions"
                          " WHERE kind='project' AND project=%s", (proj,))
            pb = (pi[0]["body"] if pi else "") or ""
            if pb.strip():
                pb = re.sub(r"^\s*##[^\n]*\n*", "", pb.strip())
                out.append("## Проектная инструкция\n\n" + pb)
            customs = db_query(
                "SELECT i.name, i.body FROM instructions i"
                " JOIN instr_attach a ON a.instr_id=i.id"
                " WHERE a.project=%s ORDER BY i.id",
                (proj,))
            for r in customs:
                b = (r["body"] or "").strip()
                if b:
                    b = re.sub(r"^\s*##[^\n]*\n*", "", b)
                    out.append(f"## Инструкция «{r['name']}»"
                               f"\n\n{b}")
        except Exception:
            pass
    return "\n\n---\n\n".join(out)


def _task_name(stem: str) -> str:
    return f"{stem}.txt"


def _insert_task(stem: str, prompt: str, source: str,
                 project: str | None, chat_id, created: float,
                 model: str | None = None,
                 reply_mode: str | None = None,
                 user: str | None = None,
                 bot: str | None = None,
                 instr: str | None = None,
                 topic_id: int | None = None) -> None:
    db_exec("INSERT INTO tasks (stem, source, project, chat_id, prompt,"
            " model, reply_mode, user, bot, instr, topic_id, created,"
            " sort) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE prompt=VALUES(prompt)",
            (stem, source, project, chat_id, prompt, model, reply_mode,
             user, bot, instr, topic_id, created, created))


def task_row(stem: str) -> dict | None:
    rows = db_query("SELECT * FROM tasks WHERE stem=%s", (stem,))
    return rows[0] if rows else None


TOPIC_SET_KEYS = ("color", "model", "reply_mode", "auto_commit", "fast",
                  "agent")


def _topic_defaults(project: str, topic_id: int | None) -> dict:
    """Дефолты колонки канбана (color/model/reply_mode/auto_commit/fast):
    именованная тема — колонки topics.*; «главная» — JSON в pj:<p>.tmain.
    Пустые значения = наследовать из настроек проекта."""
    if not project:
        return {}
    if topic_id:
        r = db_query("SELECT color, model, reply_mode, auto_commit, fast,"
                     " agent FROM topics WHERE id=%s AND project=%s",
                     (topic_id, project))
        if not r:
            return {}
        return {k: (r[0][k] or "") for k in TOPIC_SET_KEYS}
    try:
        d = json.loads(pj_get(project, "tmain") or "{}")
    except ValueError:
        d = {}
    if not isinstance(d, dict):
        return {}
    return {k: (d.get(k) or "") for k in TOPIC_SET_KEYS}


def _eff_topic_defaults(project: str | None, topic_id: int | None,
                      scope: str = "web") -> dict:
    """Итоговые дефолты колонки канбана по цепочке
    тема → проект (pj:<p>) → юзерские/глобальные настройки."""
    td = _topic_defaults(project, topic_id) if project else {}

    def pj(k: str) -> str:
        return pj_get(project, k) if project else ""

    return {
        "model": td.get("model") or pj("model") or current_model(scope),
        "reply_mode": td.get("reply_mode") or pj("reply_mode")
                      or reply_mode(scope),
        "auto_commit": td.get("auto_commit") or pj("auto_commit") or "0",
        "fast": td.get("fast") or pj("fast") or "0",
        "color": td.get("color") or "",
        # движок задач колонки: пусто = дефолтный (devin)
        "agent": td.get("agent") or pj("agent") or "",
    }


def ingest_inbox_files() -> None:
    """Externally dropped *.txt files still work: import into the tasks
    table, then remove the file (queue itself lives in MySQL now)."""
    for f in sorted(INBOX.glob("*.txt"), key=lambda p: p.stat().st_mtime):
        try:
            stem = f.stem
            src = {"tg": "telegram", "web": "web"}.get(
                stem.split("-", 1)[0], "file")
            proj = current_project()[0] if multi_mode() else None
            _insert_task(stem, f.read_text(errors="replace"), src,
                         proj, None, f.stat().st_mtime)
            f.unlink()
            log(f"inbox file {f.name} imported into mysql")
        except Exception as e:
            log(f"inbox import of {f.name} failed: {e}")


def migrate_files_to_db() -> None:
    """One-time import of the old file-based state (guarded by a kv flag):
    inbox/done/outbox + task-projects, tg-chats, pending and the small
    *.txt settings. Old files are left on disk untouched."""
    if kv_get("files_migrated"):
        return
    kv_set("files_migrated", "1")
    try:
        chats = _load_json(TASKS_DIR / "tg-chats.json")
        projs = _load_json(TASKS_DIR / "task-projects.json")
        seen = set()
        for d, st in ((INBOX, "queued"), (DONE, "done")):
            for f in sorted(d.glob("*.txt"),
                            key=lambda p: p.stat().st_mtime):
                stem = f.stem
                seen.add(stem)
                src = {"tg": "telegram", "web": "web"}.get(
                    stem.split("-", 1)[0], "file")
                out = status = None
                if st == "done":
                    resp = OUTBOX / f"{stem}.response.txt"
                    if resp.exists():
                        raw = resp.read_text(errors="replace")
                        for line in raw[:400].splitlines():
                            if line.startswith("status:"):
                                status = line.split(":", 1)[1].strip()
                        out = (raw.split("=" * 60, 1)[1].strip()
                               if "=" * 60 in raw else raw)
                db_exec("INSERT INTO tasks (stem, source, project, chat_id,"
                        " status, prompt, output, task_status, created,"
                        " sort)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        " ON DUPLICATE KEY UPDATE stem=stem",
                        (stem, src, projs.get(stem), chats.get(stem), st,
                         f.read_text(errors="replace"), out, status,
                         f.stat().st_mtime, f.stat().st_mtime))
        # .processing files were running when the container died — requeue
        for f in INBOX.glob("*.txt.processing"):
            db_exec("UPDATE tasks SET status='queued' WHERE stem=%s",
                    (f.name[:-len(".txt.processing")],))
        for pid, e in _load_json(TASKS_DIR / "tg-pending.json").items():
            db_exec("INSERT INTO pending (pid, chat_id, text, project,"
                    " message_id, created) VALUES (%s,%s,%s,%s,%s,%s)"
                    " ON DUPLICATE KEY UPDATE text=VALUES(text)",
                    (str(pid), e.get("chat_id") or 0, e.get("text") or "",
                     e.get("project"), e.get("message_id"),
                     float(e.get("id") or time.time())))
        for fname, key in (("model.txt", "model"),
                           ("project.txt", "project"),
                           ("session-mode.txt", "session_mode"),
                           ("reply-mode.txt", "reply_mode")):
            p = TASKS_DIR / fname
            if p.exists():
                kv_set(key, p.read_text().strip())
        p = TASKS_DIR / "devin-models.json"
        if p.exists():
            kv_set("models_cache", p.read_text())
        log(f"file state migrated into mysql ({len(seen)} tasks)")
    except Exception as e:
        kv_set("files_migrated", "")
        log(f"file->mysql migration failed (will retry): {e}")


def cleanup_legacy_files() -> None:
    """Удаляет старые файловые хвосты, если миграция в MySQL прошла:
    done/*.txt, outbox/*.txt и мелкие state-файлы (их содержимое уже в
    kv/tasks). inbox/ и .progress/ не трогаем — они живые."""
    if not kv_get("files_migrated") or not TASKS_DIR.is_dir():
        return
    n = 0
    for d in (TASKS_DIR / "done", TASKS_DIR / "outbox"):
        for f in d.glob("*.txt") if d.is_dir() else []:
            f.unlink(); n += 1
    for f in ("model.txt", "project.txt", "reply-mode.txt",
              "session-mode.txt", "task-projects.json", "tg-chats.json",
              "tg-commits.json", "tg-pending.json", "devin-models.json"):
        p = TASKS_DIR / f
        if p.exists():
            p.unlink(); n += 1
    if n:
        log(f"legacy task files cleaned: {n}")


def _tool_line(tc: dict) -> str:
    """One human-readable line for a transcript tool call."""
    fn = tc.get("function_name", "?")
    a = tc.get("arguments") or {}
    base = lambda p: Path(p or "").name or p
    if fn == "exec":
        return f"$ {(a.get('command') or '')[:80]}"
    if fn == "read":
        return f"читает {base(a.get('file_path'))}"
    if fn in ("edit", "write"):
        return f"правит {base(a.get('file_path'))}"
    if fn == "find_file_by_name":
        return f"ищет файлы: {a.get('pattern', '')}"
    if fn == "grep":
        return f"grep: {str(a.get('pattern', ''))[:40]}"
    if fn == "code_search":
        return f"поиск: {str(a.get('search_term', ''))[:60]}"
    if fn == "run_subagent":
        return f"субагент: {a.get('title', '')}"
    if fn in ("web_search", "webfetch"):
        return f"web: {str(a.get('query') or a.get('url') or '')[:60]}"
    if fn.startswith("mcp"):
        return f"mcp: {a.get('tool_name', fn)}"
    if fn == "todo_write":
        return "обновляет план"
    if fn == "skill":
        return f"skill: {a.get('skill', '')}"
    return fn


def _load_transcript_docs(path: Path) -> list:
    """Parse the devin --export file tolerantly: whole JSON, NDJSON lines,
    or concatenated JSON objects."""
    try:
        raw = path.read_text()
    except Exception:
        return []
    try:
        return [json.loads(raw)]
    except ValueError:
        pass
    docs = []
    for line in raw.splitlines():
        try:
            docs.append(json.loads(line))
        except ValueError:
            pass
    if docs:
        return docs
    dec, i, n = json.JSONDecoder(), 0, len(raw)
    while i < n:
        while i < n and raw[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        try:
            obj, j = dec.raw_decode(raw, i)
            docs.append(obj)
            i = j
        except ValueError:
            break
    return docs


def _digest_new_steps(path: Path, last_id: int) -> tuple:
    """Digest lines for transcript steps after last_id; (lines, new last_id)."""
    steps = []
    for d in _load_transcript_docs(path):
        if isinstance(d, dict):
            steps += d.get("steps") or ([d] if "step_id" in d else [])
    lines = []
    for s in steps:
        sid = s.get("step_id") or 0
        if sid <= last_id or s.get("source") != "agent":
            continue
        last_id = max(last_id, sid)
        lines += [_tool_line(tc) for tc in s.get("tool_calls") or []]
        msg = (s.get("message") or "").strip()
        if msg:
            lines.append("💬 " + msg[:150].replace("\n", " "))
    return [l for l in lines if l], last_id


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _collect_task_stats(export_path: Path, started: float,
                        finished: float) -> dict:
    """Метрики завершённой задачи для кнопки «инфо» на карточке и
    телеграм-сообщения: длительность + final_metrics сессии. Источник —
    export-файл ЭТОЙ задачи (точнее, чем поиск транскрипта по mtime),
    фолбэк — session_stats(started)."""
    st = {}
    try:
        for d in _load_transcript_docs(export_path):
            fm = d.get("final_metrics") if isinstance(d, dict) else None
            if fm:
                st = {"session": d.get("session_id"),
                      "model": (d.get("agent") or {}).get("model_name"),
                      "prompt_tokens": fm.get("total_prompt_tokens"),
                      "completion_tokens":
                          fm.get("total_completion_tokens"),
                      "cached_tokens": fm.get("total_cached_tokens"),
                      "steps": fm.get("total_steps")}
    except Exception:
        pass
    if not st and started:
        try:
            st = session_stats(started) or {}
        except Exception:
            st = {}
    if started and finished:
        st["duration"] = max(0, int(finished - started))
    # agent.model_name в экспорте — лейбл («Claude Opus 5.5 Low»);
    # рядом кладём uid каталога — тарифы и потребители работают по uid
    uid = _model_uid(st.get("model") or "")
    if uid:
        st["model_uid"] = uid
    return st


def _norm_model(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _model_cache() -> list:
    try:
        return json.loads(kv_get("models_cache") or "[]")
    except Exception:
        return []


def _model_uid(model: str) -> str | None:
    """uid модели в models_cache по uid ИЛИ по лейблу: в экспорте
    сессии model_name человекочитаемый («Claude Opus 5.5 Low»),
    а id каталога — «claude-opus-5-5-low». Сначала точный матч
    по id/description (нужен для лейблов вида «Fusion (…)», которые
    в uid не нормализуются), затем нормализованный."""
    if not model:
        return None
    models = _model_cache()
    def names(m):
        return (m.get("id"), m.get("description"),
                (m.get("info") or {}).get("label"),
                (m.get("info") or {}).get("display_name"))
    for m in models:
        if model in names(m):
            return m.get("id")
    norm = _norm_model(model)
    for m in models:
        if norm and norm in [_norm_model(x) for x in names(m)]:
            return m.get("id")
    return None


def _model_costs(model: str) -> dict | None:
    """$/1M {input, cached, output} по каталогу models_cache
    (info.cost_summary вида «$0.5 / 1M Input · $0.1 / 1M Cached
    input · $2 / 1M Output») или None — у бесплатной модели
    summary нет, неизвестная модель тоже. Аргумент — uid или
    лейбл, резолвится через _model_uid."""
    uid = _model_uid(model)
    if not uid:
        return None
    for m in _model_cache():
        if m.get("id") != uid:
            continue
        cs = (m.get("info") or {}).get("cost_summary") or ""
        out = {}
        for kind, key in (("Input", "input"),
                          ("Cached input", "cached"),
                          ("Output", "output")):
            mm = re.search(r"\$([\d.]+)\s*/\s*1M\s+" + kind, cs)
            if mm:
                out[key] = float(mm.group(1))
        return out or None
    return None


def _task_cost(st: dict) -> float | None:
    """Примерная стоимость задачи по тарифу её модели:
    (prompt−cached)·input + cached·cached + completion·output."""
    p = _model_costs(st.get("model") or "")
    if not p:
        return None
    return round(max((st.get("prompt_tokens") or 0)
                     - (st.get("cached_tokens") or 0), 0)
                 * p.get("input", 0) / 1e6
                 + (st.get("cached_tokens") or 0)
                 * p.get("cached", 0) / 1e6
                 + (st.get("completion_tokens") or 0)
                 * p.get("output", 0) / 1e6, 6)


def progress_loop(chat_id, export_path: Path, out_path: Path,
                  proc: subprocess.Popen, since: float,
                  transcripts: Path) -> None:
    """While the task runs, send live progress to telegram.

    Primary source: the launcher's stdout/stderr captured to out_path
    (tail). Bonus source: the export file, or the live session
    transcript if the export only lands at session end — parsed into
    step digests.
    """
    last_id, last_sent, tick = 0, 0.0, 0
    offset, buf, seen_sizes = 0, [], {}
    live_transcript = None
    while proc.poll() is None:
        time.sleep(10)
        tick += 1
        try:
            if out_path.exists():
                with out_path.open(errors="replace") as f:
                    f.seek(offset)
                    chunk = ANSI.sub("", f.read()).strip()
                    offset = f.tell()
                if chunk:
                    buf.append(chunk)
        except Exception:
            pass
        src = export_path if export_path.exists() else None
        if src is None:
            if live_transcript is None:
                try:
                    cand = [f for f in transcripts.glob("*.json")
                            if f.stat().st_mtime >= since]
                    if cand:
                        live_transcript = max(
                            cand, key=lambda f: f.stat().st_mtime)
                        log(f"progress: no export, tailing transcript "
                            f"{live_transcript.name}")
                except Exception:
                    pass
            src = live_transcript
        if src is not None:
            try:
                sz = src.stat().st_size
                if sz != seen_sizes.get(src):
                    log(f"progress: {src.name} {sz} bytes")
                    seen_sizes[src] = sz
            except Exception:
                pass
            try:
                lines, last_id = _digest_new_steps(src, last_id)
                buf += lines
            except Exception:
                pass
        elif tick % 6 == 0:
            log("progress: no export file / live transcript yet")
        if buf and time.time() - last_sent >= 20:
            text = "\n".join(buf)
            buf.clear()
            tg_send(chat_id, "🛠 " + text[-3500:])
            last_sent = time.time()


def kill_task(stem: str | None = None) -> int:
    """SIGKILL devin-task по stem; без stem — все запущенные
    (telegram /stop). Возвращает число убитых процессов."""
    with _procs_lock:
        procs = ([(stem, _task_procs[stem])]
                 if stem and stem in _task_procs else
                 list(_task_procs.items()) if not stem else [])
        n = 0
        for st, p in procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
                log(f"task process group {p.pid} ({st}) killed")
            except Exception as e:
                log(f"killpg {st} failed ({e}), falling back to kill()")
                try:
                    p.kill()
                except Exception:
                    pass
            n += 1
        return n


def claim_task() -> dict | None:
    """Атомарно забрать из очереди задачу проекта, который сейчас не
    выполняется. UPDATE-first: второй воркер ту же задачу не ухватит.
    None — очередь пуста или все взятые проекты заняты."""
    ingest_inbox_files()
    rows = db_query("SELECT stem, project FROM tasks"
                    " WHERE status='queued' ORDER BY created LIMIT 20")
    for r in rows:
        proj = r.get("project") or ""
        with _run_lock:
            if proj in RUNNING_PROJS:
                continue                    # этот проект уже в работе
        got = db_exec("UPDATE tasks SET status='running', started=%s"
                      " WHERE stem=%s AND status='queued'",
                      (time.time(), r["stem"]))
        if not got:                         # ухватил другой воркер
            continue
        with _run_lock:
            RUNNING_PROJS.add(proj)
            RUNNING_STEMS.add(r["stem"])
        t = task_row(r["stem"])
        if t:
            STATE["running_tasks"] = sorted(
                _task_name(s) for s in RUNNING_STEMS)
            return t
        # строка пропала (cancel между SELECT и UPDATE) — отпускаем
        with _run_lock:
            RUNNING_PROJS.discard(proj)
            RUNNING_STEMS.discard(r["stem"])
    return None


def _clean_task_output(text: str) -> str:
    """Срезает тех-обвязку вывода по краям: строки [devin-task]
    (кроме WARNING/ERROR — это реальные предупреждения проекта),
    шум git pull/push и баннер `devin auth`. В модалке 📄 и в tg
    нужен только результат агента."""
    if not text:
        return text
    lines = ANSI.sub("", text).splitlines()
    def noise(s: str) -> bool:
        s = s.strip()
        if not s:
            return True
        if s.startswith("[devin-task]"):
            return "WARNING:" not in s and "ERROR:" not in s
        if s.startswith(("✓ ", "Already up to date", "From http",
                         "Fetching ", "Updating ", "Fast-forward",
                         "remote: ", "To http", "Branch '")):
            return True
        if re.match(r"(create|delete|rename) mode \d+ ", s):
            return True
        if re.match(r"\d+ (insertions?|deletions?|files? changed)", s):
            return True
        if re.match(r"\S+\s*\|\s*\d+", s):       # diffstat " file | N +-"
            return True
        if re.match(r"[MADRCU?! ]{1,2}\s+\S", s):  # git status --short
            return True
        return False
    i = 0
    while i < len(lines) and noise(lines[i]):
        i += 1
    j = len(lines)
    while j > i and noise(lines[j - 1]):
        j -= 1
    return "\n".join(lines[i:j]).strip()


def run_task(task: dict) -> None:
    stem, name = task["stem"], _task_name(task["stem"])
    log(f"processing {name}")
    STATE["current_task"] = name   # последняя стартовавшая (инфо)

    started_ts = time.time()
    tproj = task.get("project")
    # владелец проекта = чьи креды/настройки идут в задачу
    task_user = task.get("user") or _project_owner(tproj) \
        or WEB_ADMIN_USER
    ext = None
    if task.get("source") == "ext":
        try:
            ext = json.loads(kv_get(f"ext:{stem}") or "{}")
        except ValueError:
            ext = {}
    if ext:
        workdir = TASKS_DIR / "ext" / (ext.get("label") or "default")
        workdir.mkdir(parents=True, exist_ok=True)
    elif tproj and PROJECTS_ROOT and (PROJECTS_ROOT / tproj).is_dir():
        workdir = PROJECTS_ROOT / tproj
    else:
        _, workdir = current_project()
    progress_dir = TASKS_DIR / ".progress"
    progress_dir.mkdir(exist_ok=True)
    export_path = progress_dir / f"{stem}.json"
    # devin-task reads the prompt from a file — keep that contract via a
    # transient file in .progress/
    task_file = progress_dir / f"{stem}.task.txt"
    try:
        opts = json.loads(kv_get(f"opts:{stem}") or "{}")
    except ValueError:
        opts = {}
    ag = agent_def(task, opts)
    instr = (task.get("instr") or "").strip()
    body_txt = (instr + "\n\n---\n\n" + task["prompt"]) if instr \
        else task["prompt"]
    # прикреплённые файлы (из /api/attach): кладём рядом с промптом и
    # указываем пути в задаче — Devin прочтёт и учтёт их
    att = opts.get("attach")
    atts = att if isinstance(att, list) else ([att] if att else [])
    paths = []
    for i, a in enumerate(atts):
        a = (a or "").strip()
        if not a or "/" in a:
            continue
        src = ATTACH_DIR / a
        if src.is_file():
            dest = progress_dir / (f"{stem}.attach" if i == 0
                                   else f"{stem}.attach.{i+1}")
            shutil.copy2(src, dest)
            src.unlink(missing_ok=True)
            paths.append(str(dest))
    if paths:
        body_txt += ("\n\n---\n\nПрикреплённые файлы — прочти "
                     "и учитывай в задаче:\n"
                     + "\n".join("- " + p for p in paths))
    task_file.write_text(body_txt, errors="replace")
    # сессия темы: у именованной темы — свой session_id (резюмим её
    # всегда — в этом смысл темы); у «главной» — пин в kv tsess:<proj>,
    # только в режиме «продолжать». Оверрайд модели → новая сессия.
    tid = task.get("topic_id")
    # own_session=0 при создании темы → не своя сессия: общая, как у
    # «главной» (пин kv tsess:<proj> в режиме «продолжать»), либо
    # прицепка к session_topic_id — сессии другой темы проекта
    own_sess = True
    attach_id = None
    tr = None
    if tid:
        tr = db_query("SELECT session_id, own_session, session_topic_id"
                      " FROM topics WHERE id=%s", (tid,))
        own_sess = not tr or bool(tr[0]["own_session"])
        attach_id = ((tr[0]["session_topic_id"] or None)
                     if tr and not own_sess else None)
    # тема, к чьему session_id пиннется задача; None — общий пин
    pin_tid = tid if own_sess else attach_id
    resume_id = ""
    if not opts.get("model"):
        if pin_tid:
            if not own_sess or not tr:
                tr = db_query("SELECT session_id FROM topics"
                              " WHERE id=%s", (pin_tid,))
            resume_id = (tr[0]["session_id"] if tr else "") or ""
        elif continue_mode():
            resume_id = kv_get(f"tsess:{tproj or ''}")
    resume_id = re.sub(r"[^A-Za-z0-9_-]+", "", resume_id or "")
    env = dict(os.environ, DEVIN_TASK_FILE=str(task_file),
               TASK_STEM=stem,
               DEVIN_MODEL=(opts.get("model") or task.get("model")
                            or current_model()),
               DEVIN_WORKDIR=str(workdir),
               # оверрайд модели → новая сессия: resume игнорит --model;
               # есть пин сессии темы → резюмим ЕЁ, --continue не нужен;
               # новая тема без пина НЕ continue'ит последнюю сессию
               # каталога (это чужая тема) — стартует свою
               DEVIN_CONTINUE=("true" if (ext or
                                          (not pin_tid
                                           and continue_mode()))
                                    and not opts.get("model")
                                    and not resume_id
                               else "false"),
               DEVIN_EXTRA_ARGS=(
                   (os.environ.get("DEVIN_EXTRA_ARGS") or "") +
                   (f" {ag['resume_arg'](resume_id)}"
                    if resume_id else "")),
               REPLY_MODE=(opts.get("mode") or task.get("reply_mode")
                           or reply_mode()),
               # сессия неинтерактивная — подтверждать вызовы некому,
               # поэтому всегда dangerous (= bypass): даже «Спросить»
               # должно иметь рабочий exec/fetch; read-only там держится
               # только на промпте. env воркера может переопределить.
               DEVIN_PERMISSION_MODE=(
                   os.environ.get("DEVIN_PERMISSION_MODE")
                   or "dangerous"),
               DEVIN_EXPORT_FILE=str(export_path),
               GIT_AUTO_COMMIT=(
                   "true" if (opts.get("ac") == "1"
                              or (opts.get("ac") is None
                                  and _eff_topic_defaults(
                                      tproj, tid)["auto_commit"] == "1"))
                   else "false"),
               WINDSURF_API_KEY=uset("devin.api_key", task_user,
                                     "WINDSURF_API_KEY"),
               GIT_USER_NAME=uset("git.name", task_user, "GIT_USER_NAME",
                                  "devin-bot"),
               GIT_USER_EMAIL=uset("git.email", task_user,
                                   "GIT_USER_EMAIL", ""))
    chat_id = task.get("chat_id")
    out_path = progress_dir / f"{stem}.out"

    def _run_once(env2: dict) -> tuple:
        """Один прогон devin-task: вывод в .progress/<stem>.out,
        возвращает (status, body). Процесс регистрируется в
        _task_procs[stem] — kill_task(stem) убивает именно его."""
        proc = None
        try:
            # stdout+stderr go to a file the progress thread tails —
            # devin -p prints as it goes, so this gives live output for
            # free. start_new_session: own process group, so /stop
            # kills the whole tree (devin-task -> devin -> children)
            out_f = open(out_path, "w", errors="replace")
            proc = subprocess.Popen(
                [ag["bin"]], env=env2,
                stdout=out_f, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            with _procs_lock:
                _task_procs[stem] = proc
            if chat_id:
                threading.Thread(
                    target=progress_loop, daemon=True,
                    args=(chat_id, export_path, out_path,
                          proc, started_ts,
                          ag["transcripts"])).start()
            try:
                proc.wait(timeout=TASK_TIMEOUT)
                st = f"exit code: {proc.returncode}"
            except subprocess.TimeoutExpired:
                kill_task(stem)
                proc.wait()
                st = f"TIMEOUT after {TASK_TIMEOUT}s"
            out_f.close()
            return st, (out_path.read_text(errors="replace")
                        if out_path.exists() else "")
        finally:
            with _procs_lock:
                _task_procs.pop(stem, None)

    mcp_restore = _mcp_apply(tproj, ag)
    try:
        status, body = _run_once(env)

        # Ключ devin.api_key юзера может быть протухшим/обрезанным — CLI тогда
        # падает на загрузке team settings («Invalid token»). Повторяем один
        # раз с дефолтным ключом (env → credentials.toml), чтобы задача не
        # умирала из-за чужого креда.
        user_key = us_get(task_user, "devin.api_key")
        default_key = os.environ.get("WINDSURF_API_KEY", "")
        auth_bad = ("Invalid token" in body
                    or "failed to get primary API key" in body
                    or "failed to validate Devin token" in body)
        if auth_bad and user_key and user_key != default_key:
            log(f"{name}: devin.api_key юзера {task_user} отклонён, "
                "повторяю с дефолтным ключом")
            env2 = dict(env)
            if default_key:
                env2["WINDSURF_API_KEY"] = default_key
            else:
                env2.pop("WINDSURF_API_KEY", None)  # credentials.toml
            note = (f"⚠️ devin.api_key юзера {task_user} не прошёл валидацию "
                    "(Invalid token) — задача перезапущена с ключом "
                    "по умолчанию. Обнови ключ в «Настройках».\n\n")
            status, body = _run_once(env2)
            body = note + body
    finally:
        mcp_restore()

    body = _clean_task_output(body)
    finished_ts = time.time()
    tstats = ag["stats"](export_path,
                         task.get("started") or started_ts,
                         finished_ts)
    if tstats:
        cost = _task_cost(tstats)
        if cost is not None:
            tstats["cost"] = cost
    db_exec("UPDATE tasks SET status='done',"
            " output=CONCAT(IFNULL(output,''),%s), task_status=%s,"
            " finished=%s, stats=%s WHERE stem=%s",
            (body, status, finished_ts,
             json.dumps(tstats, ensure_ascii=False) if tstats else None,
             stem))
    # статистика темы: строка в topic_stats (project+topic_id на
    # момент завершения) — переживает удаление карточки и её перенос
    # в другую колонку
    try:
        if tstats:
            db_exec("INSERT INTO topic_stats"
                    " (project, topic_id, stem, created, model,"
                    " prompt_tok, cached_tok, completion_tok, cost,"
                    " duration)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (tproj, task.get("topic_id"), stem, finished_ts,
                     tstats.get("model"), tstats.get("prompt_tokens"),
                     tstats.get("cached_tokens"),
                     tstats.get("completion_tokens"),
                     tstats.get("cost"), tstats.get("duration")))
    except Exception as e:
        log(f"topic_stats: {e}")
    # пин сессии темы: следующая задача темы резюмит её через --resume
    sid = (tstats.get("session") or "")[:80]
    if sid and re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        if pin_tid:
            db_exec("UPDATE topics SET session_id=%s, updated=%s"
                    " WHERE id=%s", (sid, time.time(), pin_tid))
        else:
            kv_set(f"tsess:{tproj or ''}", sid)
    with _run_lock:
        RUNNING_PROJS.discard(tproj or "")
        RUNNING_STEMS.discard(stem)
        STATE["running_tasks"] = sorted(
            _task_name(s) for s in RUNNING_STEMS)
        if STATE["current_task"] == name:
            STATE["current_task"] = (STATE["running_tasks"][-1]
                                     if STATE["running_tasks"] else None)
        STATE["tasks_done"] += 1
    STATE.update(last_task=name, last_status=status)
    log(f"done {name} ({status}), output -> mysql")
    if ext and ext.get("hook"):
        payload = {"ok": True, "name": name,
                   "project": ext.get("label") or "",
                   "status": status, "output": body}
        # инструкциями вызова задан свой формат — шлём последний
        # json-объект из ответа агента; не нашли — фолбэк на дефолт
        if ext.get("hook_json"):
            custom = _tail_json(body)
            if custom is not None:
                payload = custom
            else:
                log(f"{name}: ext-hook — json-объект не найден, "
                    "шлю дефолтный payload")
        try:
            req = urllib.request.Request(
                ext["hook"], method="POST",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            log(f"{name}: ext-hook {ext['hook']} не ответил: {e}")
    offer_commit(task, chat_id, workdir)
    if TG_TOKEN:
        notify_chat(stem, f"{name}\n{status}\n\n{body[-3500:]}")
        if chat_id:
            send_task_stats(chat_id, tstats)


def _tail_json(text: str):
    """Последний топ-левел JSON-объект в конце текста (игнорируя
    закрывающий ```-фенс). Первая '{', чей декод достаёт до конца
    хвоста — это внешний объект последнего блока; вложенные '{' у
    него внутри до конца не доходят. Ничего нет — None."""
    tail = text.rstrip()
    if tail.endswith("```"):
        tail = tail[:-3].rstrip()
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", tail):
        try:
            obj, end = dec.raw_decode(tail, m.start())
        except ValueError:
            continue
        if not tail[end:].strip():
            return obj
    return None


def ensure_repo() -> None:
    """Clone GIT_REPO_URL into the workspace if it is not a git repo yet.

    devin-task does the same check before every task, but doing it here too
    means auth/URL problems surface at container start, not on the first task.
    """
    if multi_mode():
        log(f"multi-project mode: {len(list_projects())} project(s) "
            f"in {PROJECTS_ROOT}, current: {project_label()}")
        return
    workdir = Path(os.environ.get("DEVIN_WORKDIR", "/workspace"))
    if (workdir / ".git").exists():
        return
    url = os.environ.get("GIT_REPO_URL")
    if not url:
        log(f"{workdir} is empty and GIT_REPO_URL is not set — "
            "tasks will fail until a repo is mounted or cloned")
        return
    log(f"cloning {url} -> {workdir}")
    args = ["git", "clone"]
    if branch := os.environ.get("GIT_BRANCH"):
        args += ["--branch", branch]
    args += [url, str(workdir)]
    # git bypasses the proxy — strip *_proxy so the clone goes direct
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
    res = subprocess.run(args, env=env)
    if res.returncode != 0:
        log(f"clone failed (exit {res.returncode}) — check GIT_REPO_URL and git credentials; "
            "devin-task will retry before each task")
    else:
        log("clone finished")
