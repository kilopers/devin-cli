# --- Слой «агент»: единая точка входа движков выполнения --------------
# run_task, «✨ оформить», прогресс и детект фаз «запускается»/
# «выполняется» обращаются к движку только через AGENTS — новый backend
# (Claude и т.п.) добавляется записью сюда + launcher-скриптом с тем же
# env-контрактом, без разбросанных if'ов по воркеру. Сейчас backend
# один — Devin CLI.

AGENT_DEFAULT = "devin"


def _devin_resume_arg(session_id: str) -> str:
    return f"--resume {session_id}"


AGENTS = {
    "devin": {
        "label": "Devin",
        # launcher задачи — скрипт с env-контрактом devin-task
        # (DEVIN_TASK_FILE/WORKDIR/MODEL/CONTINUE/EXTRA_ARGS/
        #  EXPORT_FILE/PERMISSION_MODE, GIT_AUTO_COMMIT, REPLY_MODE)
        "bin": DEVIN_TASK,
        # маркер стартового баннера в .progress/<stem>.out: фаза
        # «запускается» длится, пока после строки с маркером нет вывода;
        # у движка без баннера — None (всегда сразу «выполняется»)
        "start_marker": b"all set",
        # флаг резюма пинненой сессии темы (в EXTRA_ARGS launcher'а)
        "resume_arg": _devin_resume_arg,
        # каталог моделей -> [{id, description, family, info}]
        "models": devin_models,
        # живые транскрипты сессии — прогресс до export-файла
        "transcripts":
            Path.home() / ".local/share/devin/cli/transcripts",
        # MCP-конфиг CLI, подмешиваемый проектными серверами на время
        # задачи (_mcp_apply)
        "mcp_config": _MCP_CFG,
        # сбор метрик завершённого прогона -> tasks.stats
        "stats": _collect_task_stats,
    },
}


def agent_of(task: dict | None, opts: dict | None = None) -> str:
    """Движок задачи по цепочке дефолтов, как у модели: разовый оверрайд
    opts:<stem>.agent → tasks.agent → дефолт колонки/проекта
    (topics.agent → pj:<p>.agent) → devin. Неизвестное значение
    откатывается на дефолтный движок."""
    task, opts = task or {}, opts or {}
    a = (opts.get("agent") or task.get("agent") or "").strip()
    proj = task.get("project")
    if not a and proj:
        try:
            a = (_eff_topic_defaults(proj, task.get("topic_id"))
                 .get("agent") or "").strip()
        except Exception:
            a = ""
    return a if a in AGENTS else AGENT_DEFAULT


def agent_def(task: dict | None, opts: dict | None = None) -> dict:
    """Запись AGENTS движка задачи — все обращения к движку идут
    отсюда."""
    return AGENTS[agent_of(task, opts)]
