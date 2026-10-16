# Project Rules

Сначала прочитай `README.md` — там полное описание установки, env-переменных
и сценариев использования. Этот файл — правила и краткая памятка.

## Что это за проект

Docker-образ (`ghcr.io/kilopers/devin-cli`) с автономным Devin CLI воркером:
задачи приходят текстовыми файлами в `tasks/inbox/` или через Telegram-бота
(webhook на том же HTTP-порту, что и статус-страница), Devin выполняет их в
выбранном проекте (`./projects/<имя>` = git-репозиторий, мультирежим),
результат уходит в `tasks/outbox/` и обратно в чат. Голосовые сообщения
распознаются Yandex SpeechKit v3 async, перед постановкой задачи текст
подтверждается inline-кнопками. Сборка — GitHub Actions → GHCR только под `linux/amd64` (сервер x86),
кэш слоёв `type=gha` — деплой `docker compose up -d` на сервере;
автообновление — `watchtower` (метка `com.centurylinklabs.watchtower.enable`,
5 мин, требует `docker login ghcr.io` на хосте).

## Коммиты и язык

- Сообщения коммитов писать **на русском языке** (заголовок и описание) —
  названия запусков GitHub Actions берутся из них и тоже должны быть русскими.
- Тексты для пользователя (Telegram-ответы, README, комментарии) — по-русски.
- Идентификаторы в коде, имена файлов и переменных — по-английски.

## Архитектура

- `watcher.py` — единственный долгоживущий процесс: webhook Telegram, очередь
  задач, веб-интерфейс (`/` → `templates/webui.html` + JSON `/api/*`) и
  статус-страница (`/status`). HTTP-слой — Flask + waitress (`start_web`);
  страницы рендерятся через Jinja2 `render_template` из `TEMPLATES_DIR`
  (default `/app/templates`); `/login` — обычная HTML-форма в стиле
  Material (чистый CSS, без JS и внешних CDN — React/MUI/Babel по CDN давали
  белый экран: UMD у MUI v6 нет, на мобильном CDN может резаться), ошибка
  входа пробрасывается шаблону переменной `error`. Роуты под
  `login_required` (сессия-cookie; хеш пароля — `kv.admin_password_hash`,
  сид из `WEB_ADMIN_*`, смена — профиль/`POST /api/password`; пустой пароль =
  auth off). Telegram webhook (`POST /` и `POST /<any>` — корень тоже, иначе 405) и GET /status — публичные.
  в отдельной процесс-группе (убивается по /stop).
- Вся персистентность — в MySQL (сервис `mysql` в compose, pymysql,
  соединение per-thread через threading.local): таблица `tasks` (очередь,
  история, вывод, колонки `project`/`chat_id`/`commit_offered`), `kv`
  (проект/модель/режимы/кэш моделей), `pending` (подтверждения голосовых).
  Старые файлы `tasks/*.txt|*.json` мигрируются в БД один раз при старте
  (`kv.files_migrated`). Дроп `*.txt` в `tasks/inbox/` по-прежнему работает —
  файлы импортируются в БД и удаляются. На диске остаётся только
  `tasks/.progress/` — живой вывод и транскрипты выполняющихся задач.
- Привязка задачи к проекту — колонка `tasks.project`; `run_task` берёт
  workdir из неё, иначе — текущий проект. Web-задачи имеют префикс `web-`,
  телеграм — `tg-`. Модель фиксируется при постановке (`tasks.model`).
- Скоупы настроек раздельные: телеграм — `kv.project`/`kv.model_telegram`/
  `kv.reply_mode_telegram`, веб — `kv.project_web`/`kv.model_web`/
  `kv.reply_mode_web`. `current_project()`/`current_model()`/`reply_mode()`
  принимают scope; в задачу попадают значения интерфейса-источника
  (`tasks.project`/`tasks.model`/`tasks.reply_mode`).
- Новые env-переменные добавлять одновременно в `docker-compose.yml`,
  `.env.example` и README.
- Devin CLI ставится latest (пин снят): пустой список моделей был не багом
  `3000.11.x`, а таймаутом remote config (`GetCliModelConfigs`) через внешний
  HTTP-прокси — лечится встроенным mihomo.
- Выбор модели: веб-селект в шапке (`GET /api/models`, `POST /api/model`) и
  `/models` в телеграме — по скоупам выше; приоритет над `DEVIN_MODEL`.
  Каталог моделей кэшируется в `kv.models_cache` (обновляется при старте и
  лениво раз в минуту, пока пуст).
- Веб-микрофон: кнопка 🎙 рядом с «В работу» пишет PCM16 → WAV @16kHz
  (ресемпл на клиенте) и шлёт `POST /api/stt` (octet-stream, ≤16 МБ);
  ответ дописывается в textarea. У кнопки — таймер записи и статус
  распознавания (`STATE["stt"]` → `GET /api/status.stt_status`).
  Распознаёт тем же `STT_PROVIDER`; для yandex в `web_transcribe` вилка:
  <28с — v1 sync (LPCM), длиннее — v3 async с WAV-контейнером
  (`_wav_wrap`), как у телеграм-голосовых.
- Оффер коммита общий для всех источников: `offer_commit` ставит
  `tasks.commit_offered` при грязном репо/непушнутых коммитах после задачи,
  телеграм жмёт инлайн-кнопки, веб — `POST /api/commit` (одноразово,
  кто первый нажал).
- В образ встроен mihomo (прокси на 127.0.0.1:7890): watcher стартует его,
  если смонтирован `/mihomo/config.yaml`, и сам выставляет `*_proxy` env
  (явные HTTP(S)_PROXY в .env важнее). Шаблон — `mihomo.example.yaml`,
  реальный конфиг с ключами в `mihomo/` — в .gitignore, в гит не класть.
  Git всегда идёт напрямую (env срезается).

## Проверка перед коммитом

- `python3 -m py_compile watcher.py bot.py`
- `bash -n entrypoint.sh`
- Убедиться, что в файлах нет повреждённых UTF-8 символов (�).

## Поддержание документации

- После каждого изменения функциональности **кратко дописывать этот файл**
  (пара строк: что и зачем) и соответствующий раздел README.
