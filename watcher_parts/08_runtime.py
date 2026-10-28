def start_web() -> None:
    # env wins; otherwise a generated key persisted in kv — sessions survive
    # container restarts either way
    app.secret_key = WEB_SESSION_SECRET or kv_get("session_secret") \
        or secrets.token_hex(32)
    kv_set("session_secret", app.secret_key)
    threading.Thread(
        target=lambda: serve(app, host="0.0.0.0", port=WEB_PORT,
                             threads=16, channel_timeout=600),
        daemon=True).start()
    log(f"web ui on :{WEB_PORT}"
        + ("" if _admin_hash()
           else " — auth OFF (set WEB_ADMIN_PASSWORD to enable)"))


def start_mihomo() -> None:
    """Run mihomo when /mihomo/config.yaml is mounted.

    mihomo exposes a local HTTP/SOCKS5 proxy at MIHOMO_PROXY (default
    127.0.0.1:7890) forwarding to the nodes from the config. If no explicit
    *_proxy env is set, it becomes the default proxy for the devin API and
    telegram — children inherit os.environ, TG_OPENER is rebuilt for the
    in-process webhook handler. Git stays direct either way.
    """
    global _mihomo_proc, TG_OPENER
    cfg = MIHOMO_DIR / "config.yaml"
    if not cfg.exists():
        return
    if _mihomo_proc and _mihomo_proc.poll() is None:
        return
    try:
        _mihomo_proc = subprocess.Popen(["mihomo", "-d", str(MIHOMO_DIR)])
    except FileNotFoundError:
        log("mihomo config found but the binary is missing — not starting")
        return
    log(f"mihomo started (config {cfg}), waiting for {MIHOMO_PROXY}")
    port = int(MIHOMO_PROXY.rsplit(":", 1)[-1])
    for _ in range(50):
        if _mihomo_proc.poll() is not None:
            log(f"mihomo exited ({_mihomo_proc.returncode}) — "
                "check /mihomo/config.yaml; running without it")
            return
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        log("mihomo port did not open in 10s — continuing anyway")
    if not (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")):
        os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"] = MIHOMO_PROXY
        os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
        os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
        TG_OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {"http": MIHOMO_PROXY, "https": MIHOMO_PROXY}))
        log(f"proxy -> {MIHOMO_PROXY} (mihomo) for devin API and telegram; "
            "git stays direct")


def start_bot() -> None:
    """Run bot.py in parallel when TELEGRAM_BOT_TOKEN is set."""
    global _bot_proc
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    if _bot_proc and _bot_proc.poll() is None:
        return
    log("starting telegram bot")
    # -u: unbuffered stdout so bot logs show up in `docker logs`
    _bot_proc = subprocess.Popen([sys.executable, "-u", BOT_SCRIPT])


def _self_deploy_report() -> None:
    """Раз за запуск: пишем в «Деплой» devin-cli запущенную версию —
    видно, что выкатилось (watchtower пересоздаёт контейнер)."""
    p, data = "devin-cli", f"запущена v{APP_VERSION}"
    try:
        last = json.loads(kv_get(f"deploy:{p}") or "{}")
        if last.get("data") == data:
            return   # рестарт без смены версии — историю не засоряем
        rec = {"status": "success", "ts": time.time(), "data": data}
        kv_set(f"deploy:{p}", json.dumps(rec, ensure_ascii=False))
        hist = json.loads(kv_get(f"deploy_hist:{p}") or "[]")
        hist.append(rec)
        kv_set(f"deploy_hist:{p}", json.dumps(hist[-10:],
                                            ensure_ascii=False))
    except Exception as e:
        log(f"self deploy report: {e}")


def main() -> int:
    global _bot_proc, _mihomo_proc
    for d in (INBOX, DONE, OUTBOX):
        d.mkdir(parents=True, exist_ok=True)

    init_db()
    _self_deploy_report()
    migrate_files_to_db()
    migrate_env_secrets()
    _migrate_workspaces()
    cleanup_legacy_files()
    ensure_repo()
    start_mihomo()
    start_bot()
    register_webhook()
    register_commands()
    start_web()
    # каталог моделей для веб-селекта — в фоне: mihomo может ещё мерить ноды
    threading.Thread(target=refresh_models, daemon=True).start()
    log(f"watching {INBOX} every {POLL_INTERVAL}s "
        f"(timeout {TASK_TIMEOUT}s, workers {WORKER_THREADS})")
    # воркеры: задачи РАЗНЫХ проектов идут параллельно, одного —
    # по очереди (RUNNING_PROJS в claim_task). WORKER_THREADS из env.
    def _worker(wid: int) -> None:
        while True:
            try:
                task = claim_task()
                if task is None:
                    time.sleep(POLL_INTERVAL)
                    continue
                run_task(task)
            except Exception as e:
                log(f"worker{wid} ERROR: {e}")
                time.sleep(POLL_INTERVAL)
    for i in range(WORKER_THREADS):
        threading.Thread(target=_worker, args=(i,), daemon=True,
                         name=f"worker-{i}").start()
    while True:
        try:
            if _bot_proc and _bot_proc.poll() is not None \
                    and _bot_proc.returncode != 0:
                # clean exit (e.g. INTERVAL<=0 one-shot mode) — don't restart
                log(f"telegram bot exited ({_bot_proc.returncode}), restarting")
                start_bot()
            if _mihomo_proc and _mihomo_proc.poll() is not None:
                log(f"mihomo exited ({_mihomo_proc.returncode}), restarting")
                _mihomo_proc = None
                start_mihomo()
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("stopping")
            if _bot_proc:
                _bot_proc.terminate()
            if _mihomo_proc:
                _mihomo_proc.terminate()
            return 0
        except Exception as e:  # keep the watcher alive no matter what
            log(f"ERROR: {e}")
            time.sleep(POLL_INTERVAL)
