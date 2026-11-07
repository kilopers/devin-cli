# --- ночной GC сиротских сессий -------------------------------------------
# Devin хранит сессии в ~/.local/share/devin/cli/sessions.db (~90МБ на
# сессию) — растёт безгранично: «↺ Сбросить сессию»/удаление темы стирают
# только пин, транскрипт остаётся. Раз в сутки ночью стираем сессии,
# которые НЕ прибиты ни к одной теме и не использовались дольше
# SESS_GC_AGE_DAYS. Живые пины: topics.session_id + kv tsess:<proj>.
# claude: транскрипты — jsonl в ~/.claude/projects/<slug>/, чистим по
# mtime тем же правилом «не в пинах и старше порога».

SESS_GC_AGE_DAYS = 5          # сироты старше этого срока — в мусор
SESS_GC_HOUR = 4              # локальный час ночного прогона


def _sess_gc_pins() -> set:
    """Все session_id, которые ещё нужны: пины тем + общие tsess:<proj>."""
    pins = {r["session_id"] for r in db_query(
        "SELECT session_id FROM topics WHERE session_id IS NOT NULL")}
    pins |= {r["v"] for r in db_query(
        "SELECT v FROM kv WHERE k LIKE 'tsess:%'")}
    return {p for p in pins if p}


def _sess_gc_dirs() -> list:
    """Рабочие каталоги, где могли жить devin-сессии воркера."""
    dirs = {WORKDIR}
    if PROJECTS_ROOT and PROJECTS_ROOT.is_dir():
        dirs |= {p for p in PROJECTS_ROOT.iterdir() if p.is_dir()}
    ext = TASKS_DIR / "ext"
    if ext.is_dir():
        dirs |= {p for p in ext.iterdir() if p.is_dir()}
    return [d for d in dirs if (d / ".git").exists() or d == WORKDIR]


def _sess_gc_devin(cutoff: float, pins: set) -> tuple:
    """devin list в каждом workdir → devin rm сирот старше cutoff."""
    listed = removed = 0
    for d in _sess_gc_dirs():
        try:
            out = subprocess.run(
                ["devin", "list", "--format", "json"], cwd=str(d),
                capture_output=True, text=True, timeout=60)
            sessions = json.loads(out.stdout or "[]")
        except Exception as e:
            log(f"sess-gc: devin list in {d} failed: {e}")
            continue
        for s in sessions:
            listed += 1
            sid = s.get("id") or ""
            if sid in pins or \
                    (s.get("last_activity_at") or 0) >= cutoff:
                continue
            try:
                subprocess.run(["devin", "rm", "--force", sid],
                               cwd=str(d), capture_output=True,
                               text=True, timeout=60)
                removed += 1
                log(f"sess-gc: removed devin session {sid} "
                    f"({s.get('title', '')[:60]})")
            except Exception as e:
                log(f"sess-gc: devin rm {sid} failed: {e}")
    return listed, removed


def _sess_gc_claude(cutoff: float, pins: set) -> tuple:
    """Транскрипты claude: ~/.claude/projects/*/*.jsonl — файлы-сироты."""
    root = Path.home() / ".claude" / "projects"
    seen = removed = 0
    if not root.is_dir():
        return seen, removed
    for f in root.glob("*/*.jsonl"):
        seen += 1
        try:
            if f.stem in pins or f.stat().st_mtime >= cutoff:
                continue
            f.unlink()
            removed += 1
            log(f"sess-gc: removed claude transcript {f.name}")
        except Exception as e:
            log(f"sess-gc: rm {f} failed: {e}")
    return seen, removed


def sess_gc() -> None:
    """Один прогон сборки: сироты старше SESS_GC_AGE_DAYS дней."""
    cutoff = time.time() - SESS_GC_AGE_DAYS * 86400
    pins = _sess_gc_pins()
    dl, dr = _sess_gc_devin(cutoff, pins)
    cl, cr = _sess_gc_claude(cutoff, pins)
    kv_set("sess_gc_at", str(time.time()))
    log(f"sess-gc done: devin {dr}/{dl} removed, "
        f"claude {cr}/{cl} removed, pins={len(pins)}")


def sess_gc_cron() -> None:
    """Ежесуточный прогон в SESS_GC_HOUR локального времени."""
    while True:
        now = time.localtime()
        nxt = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                           SESS_GC_HOUR, 0, 0, 0, 0, -1))
        if nxt <= time.time():
            nxt += 86400
        time.sleep(nxt - time.time())
        try:
            sess_gc()
        except Exception as e:
            log(f"sess-gc ERROR: {e}")
