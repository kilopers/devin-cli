# --- Слой «агент»: единая точка входа движков выполнения --------------
# run_task, «✨ оформить», прогресс и детект фаз «запускается»/
# «выполняется» обращаются к движку только через AGENTS — новый backend
# добавляется записью сюда + launcher-скриптом с тем же env-контрактом,
# без разбросанных if'ов по воркеру.
#
# Поля записи движка:
#   bin           launcher задачи (скрипт с env-контрактом devin-task)
#   start_marker  байт-маркер стартового баннера в .progress/<stem>.out
#                 (None — баннера нет, сразу «выполняется»)
#   resume_arg    fn(session_id) -> флаг резюма пинненой сессии темы
#   models        fn() -> [{id, description, family, info}]
#   transcripts   каталог живых транскриптов (прогресс до export-файла)
#   mcp_config    MCP-конфиг CLI, подмешиваемый на время задачи
#   stats         fn(export_path, started, finished) -> tasks.stats
#   cred_key/cred_env/cred_file  чем движок авторизуется (для
#                 «настроен/нет» в UI и agent_configured)
#   auth_url      где юзеру взять ключ (ссылка в диалоге авторизации)
#   default_model модель, если у задачи/настроек своей нет

AGENT_DEFAULT = "devin"
CLAUDE_TASK = os.environ.get("CLAUDE_TASK_BIN",
                             "/usr/local/bin/claude-task")


def _devin_resume_arg(session_id: str) -> str:
    return f"--resume {session_id}"


# ------------------------------------------------------------------ claude

# $/1M токенов: (input, output); cached читается как input*0.1 —
# формат cost_summary тот же, что парсит _model_costs у devin-каталога.
_CLAUDE_PRICES = (
    ("opus",   (5.0, 25.0)),
    ("sonnet", (3.0, 15.0)),
    ("haiku",  (1.0, 5.0)),
)


def _claude_cost_summary(model_id: str) -> str:
    mid = (model_id or "").lower()
    for pat, (pin, pout) in _CLAUDE_PRICES:
        if pat in mid:
            return (f"${pin:g} / 1M Input · ${pin * 0.1:g} / 1M "
                    f"Cached input · ${pout:g} / 1M Output")
    return ""


_CLAUDE_FALLBACK_MODELS = (
    ("claude-opus-4-5",   "Claude Opus 4.5"),
    ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
    ("claude-haiku-4-5",  "Claude Haiku 4.5"),
    ("claude-sonnet-4-0", "Claude Sonnet 4"),
    ("claude-opus-4-1",   "Claude Opus 4.1"),
    ("opus",              "алиас → последняя Opus"),
    ("sonnet",            "алиас → последняя Sonnet"),
    ("haiku",             "алиас → последняя Haiku"),
)


def _claude_models_static() -> list:
    """Фолбэк-каталог, когда API недоступен или ключа ещё нет."""
    return [{"id": mid, "description": name,
             "family": re.sub(r"\s*[\d.]+\s*$", "", name).strip()
                      or "Claude",
             "info": {"label": name,
                      "cost_summary": _claude_cost_summary(mid)}}
            for mid, name in _CLAUDE_FALLBACK_MODELS]


def claude_models() -> list:
    """[{id, description, family, info}] через Anthropic GET /v1/models.
    Кэш — models_cache:claude (per-agent каталог)."""
    key = uset("claude.api_key", WEB_ADMIN_USER, "ANTHROPIC_API_KEY")
    models = []
    if key:
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/models?limit=100",
                headers={"x-api-key": key,
                         "anthropic-version": "2023-06-01"})
            data = json.loads(
                urllib.request.urlopen(req, timeout=30).read())
            for m in data.get("data") or []:
                mid = m.get("id")
                if not mid:
                    continue
                name = m.get("display_name") or mid
                info = {k: v for k, v in m.items()
                        if k not in ("id", "display_name")}
                info["label"] = name
                info["cost_summary"] = _claude_cost_summary(mid)
                models.append({"id": mid, "description": name,
                               "family": re.sub(r"\s*[\d.]+\s*$", "",
                                                name).strip()
                                         or "Claude",
                               "info": info})
        except Exception as e:
            log(f"claude models list failed: {e}")
    # алиасы CLI — тоже runnable id; добавляем всегда
    seen = {m["id"] for m in models}
    for mid, name in _CLAUDE_FALLBACK_MODELS:
        if mid not in seen:
            st = dict(_claude_models_static()[0])
            st = {"id": mid, "description": name,
                  "family": "Алиасы" if mid in ("opus", "sonnet", "haiku")
                            else re.sub(r"\s*[\d.]+\s*$", "", name).strip()
                            or "Claude",
                  "info": {"label": name,
                           "cost_summary": _claude_cost_summary(mid)}}
            models.append(st)
    if not models:
        models = _claude_models_static()
    else:
        try:
            kv_set("models_cache:claude",
                   json.dumps(models, ensure_ascii=False))
            kv_set("models_cache_at:claude", str(int(time.time())))
        except Exception:
            pass
    return models


def _claude_collect_stats(export_path: Path, started: float,
                          finished: float) -> dict:
    """Метрики завершённой claude-задачи из result-JSON, который relay
    сохранил в DEVIN_EXPORT_FILE: usage + total_cost_usd + session_id.
    prompt = весь вход (input + cache read/create), cached — его часть
    из prefix-кэша — те же поля, что у devin-статистики."""
    st = {}
    try:
        docs = _load_transcript_docs(export_path)
        ev = next((d for d in reversed(docs)
                   if isinstance(d, dict) and d.get("type") == "result"),
                  docs[-1] if docs else {})
        if isinstance(ev, dict) and ev:
            usg = ev.get("usage") or {}
            mu = ev.get("modelUsage") or {}
            cache = (usg.get("cache_read_input_tokens") or 0) \
                + (usg.get("cache_creation_input_tokens") or 0)
            st = {"session": ev.get("session_id"),
                  "model": next(iter(mu), None),
                  "prompt_tokens": (usg.get("input_tokens") or 0)
                                   + cache,
                  "completion_tokens": usg.get("output_tokens"),
                  "cached_tokens": cache or None,
                  "steps": ev.get("num_turns"),
                  # реальная стоимость прогона — точнее оценки по тарифу
                  "cost": ev.get("total_cost_usd")}
    except Exception:
        pass
    if started and finished:
        st["duration"] = max(0, int(finished - started))
    uid = _model_uid(st.get("model") or "", "claude")
    if uid:
        st["model_uid"] = uid
    return st


# ------------------------------------------------------------------ реестр

AGENTS = {
    "devin": {
        "label": "Devin",
        "bin": DEVIN_TASK,
        "start_marker": b"all set",
        "resume_arg": _devin_resume_arg,
        "models": devin_models,
        "transcripts":
            Path.home() / ".local/share/devin/cli/transcripts",
        "mcp_config": _MCP_CFG,
        "stats": _collect_task_stats,
        "cred_key": "devin.api_key",
        "cred_env": "WINDSURF_API_KEY",
        "cred_file":
            Path.home() / ".local/share/devin/credentials.toml",
        "auth_url": "https://app.devin.ai/settings/api-keys",
        "default_model": "",                    # current_model()
    },
    "claude": {
        "label": "Claude",
        "bin": CLAUDE_TASK,
        # баннера нет — relay сразу печатает события в .out
        "start_marker": None,
        "resume_arg": _devin_resume_arg,        # claude тоже --resume
        "models": claude_models,
        "transcripts": Path.home() / ".claude/projects",
        "mcp_config": os.path.expanduser("~/.claude.json"),
        "stats": _claude_collect_stats,
        "cred_key": "claude.api_key",
        "cred_env": "ANTHROPIC_API_KEY",
        "cred_file": Path.home() / ".claude.json",
        "auth_url": "https://console.anthropic.com/settings/keys",
        "default_model": "sonnet",
    },
}


def agent_configured(key: str, user: str | None = None) -> bool:
    """У движка есть авторизация: ключ юзера → env → файл кредов CLI."""
    ag = AGENTS.get(key)
    if not ag:
        return False
    ck, ce = ag.get("cred_key"), ag.get("cred_env")
    try:
        if us_get(user or WEB_ADMIN_USER, ck) \
                or os.environ.get(ce or ""):
            return True
    except Exception:
        pass
    cf = ag.get("cred_file")
    return bool(cf and Path(cf).exists())


def agent_default(user: str | None = None) -> str:
    """Движок «по умолчанию» юзера: его выбор в шапке (us:<u>.agent),
    иначе первый настроенный из реестра; ничего не настроено — devin."""
    try:
        a = us_get(user or WEB_ADMIN_USER, "agent")
    except Exception:
        a = ""
    u = user or WEB_ADMIN_USER
    if a in AGENTS and agent_configured(a, u):
        return a
    for k in AGENTS:
        if agent_configured(k, u):
            return k
    return AGENT_DEFAULT


def agent_of(task: dict | None, opts: dict | None = None) -> str:
    """Движок задачи по цепочке дефолтов, как у модели: разовый оверрайд
    opts:<stem>.agent → tasks.agent → дефолт колонки/проекта
    (topics.agent → pj:<p>.agent) → выбор юзера в шапке (us:<u>.agent) →
    первый настроенный. Неизвестное значение откатывается на дефолтный."""
    task, opts = task or {}, opts or {}
    a = (opts.get("agent") or task.get("agent") or "").strip()
    proj = task.get("project")
    if not a and proj:
        try:
            a = (_eff_topic_defaults(proj, task.get("topic_id"))
                 .get("agent") or "").strip()
        except Exception:
            a = ""
    if a and a in AGENTS:
        return a
    try:
        return agent_default(task.get("user"))
    except Exception:
        return AGENT_DEFAULT


def agent_def(task: dict | None, opts: dict | None = None) -> dict:
    """Запись AGENTS движка задачи — все обращения к движку идут
    отсюда."""
    return AGENTS[agent_of(task, opts)]


def models_cache_keys(key: str) -> tuple:
    """kv-ключи каталога моделей движка (per-agent). У devin исторически
    общие models_cache/models_cache_at — новый ключ пишется рядом."""
    return (f"models_cache:{key}", f"models_cache_at:{key}")
