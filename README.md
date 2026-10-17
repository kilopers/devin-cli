# devin-cli-docker

Docker-образ с [Devin CLI](https://devin.ai) для автономного выполнения задач.

Два режима:

- **watcher** (docker-compose, для сервера) — вся очередь и состояние живут в
  MySQL (сервис `mysql` в том же compose): забирает старейшую `queued`-задачу,
  прогоняет через Devin (pull → задача → commit → push) и пишет ответ в
  `output` задачи. Файлы `tasks/inbox/*.txt` тоже принимаются — импортируются
  в БД и удаляются.
- **one-shot** (`docker run`) — выполняет один task-файл и завершается.

Образ собирается GitHub Actions (`.github/workflows/docker.yml`) и пушится в
GitHub Container Registry — `ghcr.io/kilopers/devin-cli`. Secrets настраивать
не нужно: логин идёт через встроенный `GITHUB_TOKEN`.

## Сервер: установка и запуск

```bash
# 1. залогиниться в ghcr (нужен PAT с правом read:packages,
#    если пакет приватный; для public-пакета логин не нужен)
echo $GITHUB_PAT | docker login ghcr.io -u kilopers --password-stdin

# 2. забрать файлы запуска
git clone git@github.com:kilopers/devin-cli.git
cd devin-cli

# 3. настроить
cp .env.example .env
# в .env прописать:
#   PROJECT_DIR=/srv/my-project — пустая папка или существующий чекаут
#   GIT_REPO_URL=...            — если папка пустая, репо склонируется сам
#   DEVIN_MODEL, GIT_USER_NAME/EMAIL

# 4. один раз авторизовать Devin (manual token flow — вставь токен)
docker compose --profile auth run --rm auth
#    либо просто скопируй credentials.toml с машины, где уже залогинен:
#    scp ~/.local/share/devin/credentials.toml server:devin-cli/devin-data/

# 5. запустить
docker compose up -d
docker compose logs -f
```

Креды живут в `./devin-data/` — авторизация переживает перезапуски и ребилды.

## Автообновление образа (watchtower)

Сервис `watchtower` в compose раз в 5 минут спрашивает GHCR: если `:latest`
пересобрался (push в main → GitHub Actions), делает `pull` и пересоздаёт
контейнер `devin` сам — ручной `docker compose pull && up -d` не нужен.
Учти: пересоздание — это SIGTERM контейнеру, выполняющаяся задача умрёт.

Один раз на сервере нужен логин в GHCR (см. PAT ниже):

```bash
echo $GITHUB_PAT | docker login ghcr.io -u kilopers --password-stdin
docker compose up -d   # поднимет и watchtower
```

## GitHub PAT — clone/pull/push и GHCR без SSH-ключей

1. github.com → аватар → **Settings** → **Developer settings** →
   **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Scopes: **`repo`** (клонировать/пулить/пушить приватные репо) и
   **`read:packages`** (docker pull из GHCR; `write:packages` — если пушишь
   образы вручную).
3. Скопируй токен сразу — второй раз его не покажут.

```bash
# git по HTTPS: логин — GitHub username, пароль — токен
git clone https://github.com/kilopers/devin-cli.git
# чтобы не вводить каждый раз:
git config --global credential.helper store

# GHCR на сервере:
echo <TOKEN> | docker login ghcr.io -u <github-username> --password-stdin
```

Тот же PAT используется воркеру в `GIT_REPO_URL` вида
`https://<TOKEN>@github.com/org/repo.git` — но помни: токен остаётся
в `.git/config` открытым текстом.

## Как кидать задачи

```bash
echo "Добавь endpoint /healthz, возвращающий 200" > tasks/inbox/task-001.txt
```

Вотчер каждые `POLL_INTERVAL` секунд (default 30) забирает самую старую
`queued`-задачу из таблицы `tasks` (дропнутые в `tasks/inbox/` файлы
импортируются туда же), выполняет её и пишет статус (`task_status`,
например `exit code: 0`) и полный вывод Devin в колонку `output`.

Задачи выполняются последовательно, по одной. Старые файлы состояния
(`inbox/done/outbox`, `tg-chats.json`, `tg-pending.json`, `*.txt` настроек)
при первом старте **мигрируются в MySQL автоматически** — история задач
не теряется; сами файлы на диске остаются нетронутыми.

## Telegram webhook: голос → задача → ответ

Если задан `TELEGRAM_WEBHOOK_URL` — вотчер сам регистрирует webhook у Telegram
(`setWebhook`) и принимает апдейты POST'ом на **любой** путь статус-сервера
(например `https://build.kilop.ru/anything` — зависит от того, как
nginx режет путь; работает всегда).

Поток:

1. Голосовое → `getFile` → OGG → STT (`STT_PROVIDER`: yandex / gemini /
   openai-compatible — можно списком через запятую `gemini,openai`:
   провайдеры пробуются по очереди, при отказе первого распознаёт
   следующий — переживает и 403 у Gemini, и недоступность API) → текст.
   Yandex SpeechKit работает в **асинхронном**
   режиме (API v3 `recognizeFileAsync`, аудио уходит base64-контентом без
   Object Storage): бот пишет «отправлено на распознавание», каждые 10с
   обновляет статус («пока не готово, проверяю ещё»), при готовности то же
   сообщение превращается в «Распознано: …» с кнопками. Длинные голосовые
   (до ~10 мин) поддерживаются.
2. В чат приходит распознанный текст с inline-кнопками
   **«✅ Принять» / «❌ Отмена»** (pending-записи — таблица `pending`).
   Пока pending открыт, любые новые сообщения (текст и голос) **дописываются**
   к нему, а сообщение с кнопками обновляется.
3. «Принять» → строка `tg-*` в таблице `tasks` (chat_id и проект — колонками).
   «Отмена» → pending удаляется.
4. Когда задача отработает — в чат прилетает статус и хвост её `output`.

**Команды бота** (кнопка Menu у поля ввода регистрируется автоматически):

- `/menu` — inline-меню: «🧠 Модели», «📊 Статус»
- `/models` — список моделей аккаунта (`devin models list`), каждая —
  кнопка переключения. Выбор хранится в `kv.model_telegram` и действует
  на задачи из телеграма (у веба свой селект → `kv.model_web`)
- `/model <name>` — переключить модель напрямую
- `/session` — режим сессий: «продолжать» (`devin --continue` к последней
  сессии выбранного проекта; сессии хранятся per-директории, т.е. у каждого
  проекта свои) или «каждая задача — новая». Хранится в `kv`
  (`session_mode`), приоритет над `DEVIN_CONTINUE`
- `/stop` — SIGKILL всей процесс-группе текущей задачи (подвисший Devin
  убивается вместе с дочерними процессами), воркер берёт следующую из очереди
- `/mode` — режим ответа: «🛠 код» (обычная задача) или «💬 вопрос»
  (агент читает репо и отвечает, ничего не меняет и не коммитит).
  Хранится в `kv.reply_mode_telegram`; у веба свой — `kv.reply_mode_web`
  (селект в шапке), задача фиксирует режим источника в `tasks.reply_mode`
- `/status` — сводка: uptime, проект, модель, режимы, очередь,
  текущая/последняя задача, токены за 24ч и 7 дней, HEAD репо

**Лайв-прогресс задачи.** `devin` запускается с `--export`, транскрипт
обновляется после каждого шага агента; вотчер тейлит его и шлёт в чат
дайджест действий (`$ команда`, читает/правит файл, поиск, субагенты,
💬 ответы модели) — не чаще раза в 20 секунд, батчами.

**Мультипроектный режим (GEARS).** Папка `./projects` рядом с compose уже
смонтирована — клади туда папки с репозиториями, и режим включается сам
(или укажи `PROJECTS_DIR` в `.env` на свой путь). Прямые подпапки —
это проекты (имя папки = имя проекта, список
сканируется автоматически при каждом `/projects`, рекурсии нет). Текущий
проект выбирается кнопкой «📁 Проект» в `/menu` или командой
`/projects` / `/project <name>`; выбор хранится в `kv.project` — это
«телеграмовский» текущий проект. У веб-интерфейса свой — `kv.project_web`
(вкладка сверху, fallback на телеграмовский). Задача получает модель и
проект того интерфейса, из которого её поставили — колонки
`tasks.project`/`tasks.model`.
Каждое подтверждение и постановка задачи показывает `Проект: <имя>`,
задачи и кнопки коммита работают в директории выбранного проекта.
Если `PROJECTS_DIR` не задан — работает старый однопроектный режим
(`PROJECT_DIR` → `/workspace`).

**Статистика и подтверждение коммита.** После задачи бот присылает
результат, затем статистику сессии (модель, prompt/cached/completion
токены, шаги — читается из транскрипта `devin-data/cli/transcripts/`).
Если в репо остались незакоммиченные или незапушенные изменения — сообщение
с кнопками «✅ Закоммитить и запушить» / «⏭ Пропустить». Чтобы агент сам
не коммитил, поставь `GIT_AUTO_COMMIT=false` в `.env` (и/или пропиши это
в `AGENTS.md` проекта).

`TELEGRAM_WEBHOOK_SECRET` — опционально, сверяется с заголовком
`X-Telegram-Bot-Api-Secret-Token`.

Внимание: при активном webhook `getUpdates` возвращает 409 — если используешь
пингер-бота (bot.py), задай `CHAT_ID` явно или выключи его.

## Веб-интерфейс

На `http://server/` (тот же порт, что и webhook) — веб-морда на
**React + Material UI** (`webui/src/*.jsx`, сборка esbuild →
`static/app/*.js`; стадия `webui-build` в Dockerfile гоняет `npm ci` +
`npm run build`, локально — `cd webui && npm ci && npm run build`).
HTTP-слой — Flask + waitress; страницы — Jinja2-шаблоны (`templates/`,
`render_template`; путь переопределяется `TEMPLATES_DIR`), логин — тоже
MUI-форма, POST на `/login`.
Иконка приложения — официальный логотип Devin, скачан с devin.ai:
`static/favicon.svg` (+ `favicon.ico` и `icon.png` для `apple-touch-icon`),
показан в шапке, мобильном меню и на странице входа.
Веб-морда — **PWA**: `static/manifest.webmanifest` + `sw.js` (роут `/sw.js`,
кэширует только `/static/*`, `/api/*` и POST'ы всегда в сеть) — на Android
Chrome предложит «Установить приложение», на iPhone — «На экран Домой»
из меню «Поделиться»; открывается в standalone без адресной строки.
Авторизация по сессии (один админ):

- `/` и все `/api/*` требуют логина (`/login` — форма, сессия в cookie
  HttpOnly+SameSite=Lax; `secret_key` из `WEB_SESSION_SECRET` или
  сгенерированный в `kv.session_secret` — переживает рестарты).
- Пароль хранится хешем в `kv.admin_password_hash`: сидится из
  `WEB_ADMIN_PASSWORD` при первом запуске, дальше меняется в профиле
  (иконка person в шапке → модалка; `POST /api/password`). Сброс: удали
  ключ `admin_password_hash` из kv и задай `WEB_ADMIN_PASSWORD` заново.
  Пустой `WEB_ADMIN_PASSWORD` без сида = веб без авторизации (dev).
- Публичными остаются `/status` и telegram-webhook (POST на любой не-`/api`
  путь, проверка по `TELEGRAM_WEBHOOK_SECRET`).

- Вкладки сверху — по одной на каждый проект из `./projects` (мультирежим).
  Клик по вкладке переключает **веб-скоуп** проекта (`POST /api/project` →
  `kv.project_web`) — на телеграмовский выбор не влияет: у каждого
  интерфейса свои «последние» проект и модель, а задача бежит с настройками
  того интерфейса, откуда её поставили. На узких экранах (≤992px) вкладки
  прячутся в выдвижное левое меню (гамбургер в шапке, Materialize sidenav)
  вместе с селектами модели/режима и строкой статуса; композер внизу
  переносит поле ввода и кнопки на две строки.
- Внизу поле ввода во всю ширину: пишешь задачу → Ctrl+Enter или «В работу»
  → строка `web-*` в таблице `tasks` с колонкой `project` = выбранная вкладка.
- Лента задач по центру: текст задачи + вывод devin — читается из MySQL.
  Задачи из Telegram отображаются там же (бейдж источника: web/telegram) —
  видны и промежуточный лог (сырой хвост `.progress/<task>.out` во время
  выполнения), и финальный ответ. Финальный ответ рендерится как Markdown с
  подсветкой кода и diff'ов (marked + DOMPurify + highlight.js по CDN).
  Опрос API — каждые 3 секунды; грузятся 5 последних задач, при прокрутке
  вверх AJAX догружает ещё по 5 (`/api/tasks?limit=5&before=<stem>`),
  фильтр по проекту — колонка `tasks.project`.
- В шапке — селект модели Devin: список с описаниями подтягивается из
  `devin models list --format json` (кэш — `kv.models_cache`,
  обновляется при старте и лениво по запросу). Выбор пишется в
  `kv.model_web` — телеграмовский `/models` (`kv.model_telegram`)
  не затрагивается. Рядом — селект режима «🛠 код / 💬 вопрос»
  (`POST /api/mode` → `kv.reply_mode_web`).
- Рядом с «В работу» — кнопка микрофона 🎙: диктовка прямо в браузере.
  Запись через `AudioContext` → WAV (PCM16, ресемпл в 16 кГц — Яндекс
  принимает только 8/16/48 кГц), отправка на `POST /api/stt`
  (сырое тело octet-stream, до 16 МБ) → распознавание тем же провайдером,
  что и телеграмовские голосовые (`STT_PROVIDER`). Для Yandex: до ~28 с —
  sync `stt:recognize` (LPCM), длиннее — v3 async (WAV-контейнер, поллинг
  `getRecognition`), прогресс транслируется в `GET /api/status.stt_status`
  и показывается у кнопки. Текст дописывается в поле ввода — можно
  диктовать несколько раз, потом отправить. Ошибки — toast, во время
  записи показывается таймер `mm:ss`, при распознавании — статус.
  Запись автоматически стопается через 300 с.
- Справа — панель «Файлы проекта»: дерево файлов выбранного проекта,
  `GET /api/files?project=&path=` отдаёт **один уровень** каталога —
  верхний сразу, подпапки догружаются аяксом при раскрытии (`.git` скрыт,
  лимит 500 записей на каталог, `..` за пределы корня — 400). На мобильном
  та же панель уезжает в левое меню под «Файлы». Под деревом — сворачиваемый
  блок «Изменения» (MUI Collapse): `GET /api/diff` = `git status --porcelain`
  (опрос раз в 5 с, чистый репо → «изменений нет»), клик по файлу →
  модалка на весь экран с unified diff (`GET /api/diff/file`; untracked —
  все строки «добавлены» через `diff --no-index`), подсветка hljs diff:
  удалённое красным, добавленное зелёным (цвета заданы явно — в теме
  github-dark для hljs-addition/deletion цветов нет). Клик по имени файла в
  дереве открывает редактор на весь экран — CodeMirror 6 с подсветкой по
  расширению: `GET /api/file` читает (UTF-8 текст ≤1 МБ, бинарники — 415),
  «Сохранить»/Ctrl+S → `POST /api/file` пишет атомарно; после сохранения
  файл сразу появляется в «Изменениях».
- В правом нижнем углу — индикатор связи с сервером (SSE `GET /api/stream`):
  зелёная точка = онлайн, спиннер = автореконнект, красная + подпись «нет
  подключения» = офлайн. Браузер сам переподключается каждые 2 с.
- Пока идёт задача, кнопка «⛔ Стоп» видна и в шапке, и на карточке самой
  задачи (рядом с чипом «выполняется») — после модального подтверждения
  `POST /api/stop` убивает процесс-группу (как `/stop` в телеграме).
  У задач «в очереди» — кнопка «✖ удалить»: с подтверждением
  `POST /api/task/cancel` убирает её из очереди совсем.
- Если распознавание голоса упало (ошибка провайдера/сети), запись не
  теряется: рядом с микрофоном появляется кнопка «ещё раз», повторно
  отправляющая тот же WAV на `/api/stt`.
- В заголовке «Изменений» — иконка статуса последней CI-сборки
  (`GET /api/build`, кэш 60 с): remote `github.com` → GitHub Actions,
  `gitlab*` → GitLab pipelines. Зелёная ✓ / красная ✗ / спиннер / серая —
  иконка в кружке, клик открывает пайплайн; при ошибке обращения к CI
  (⚠) клик показывает popover с подробным текстом ошибки
  (HTTP-код + тело ответа API). Для приватных репо — `GITHUB_TOKEN`
  (actions:read) и/или `GITLAB_TOKEN` (read_api), self-hosted GitLab —
  `GITLAB_BASE_URL`.
- После завершённой задачи, если репозиторий грязный или есть незапушенные
  коммиты, в карточке появляются кнопки «✅ закоммитить и запушить» /
  «⏭ пропустить» — тот же флаг `tasks.commit_offered`, что и у
  телеграмовских inline-кнопок (`POST /api/commit`). Ответ одноразовый:
  кто нажал первым (веб или телеграм), тот и сработал.

Старый статус-эндпоинт остался на `/status`. JSON-API: `GET /api/projects`,
`POST /api/project` (`{"project": "..."}`), `GET /api/status`,
`GET /api/models`, `POST /api/model` (`{"model": "swe-2"}`),
`POST /api/mode` (`{"mode": "ask"|"code"}`),
`GET /api/tasks?project=<имя>`, `POST /api/tasks`
(`{"project": "...", "text": "..."}`),
`POST /api/stt` (octet-stream WAV → `{"ok": true, "text": "..."}`),
`GET /api/files?project=&path=` (уровень дерева файлов проекта),
`POST /api/commit` (`{"stem": "...", "action": "commit"|"skip"}`).
Webhook Telegram работает как раньше: любой POST на не-`/api` путь, включая корень `/`.
При старте вотчер пишет в лог `last_error_message` из `getWebhookInfo`, если Telegram не смог доставить апдейты.

## Статус-страница

Вотчер отдаёт простую страницу `http://server/status` (проброс
`${WEB_PORT:-80}:8080`) со статусом: uptime, HEAD репозитория, очередь задач,
текущая и последняя задача, состояние telegram-бота.

## Telegram-бот (опционально)

Если задан `TELEGRAM_BOT_TOKEN` — вотчер параллельно запускает `bot.py`,
который шлёт `MESSAGE_TEXT` в чат `CHAT_ID` каждые `INTERVAL` секунд.

Узнать свой `CHAT_ID` — напиши боту `/start`, затем:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep -A5 '"chat"'
```

Если `CHAT_ID` не задан, бот сам поймает его из `getUpdates`, когда
`TG_USERNAME` напишет боту.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PROJECT_DIR` | — (обязательна) | Папка проекта на сервере, монтируется в `/workspace`. Пустая → clone, с репо → pull |
| `DEVIN_MODEL` | `swe` | Модель (`opus`, `sonnet`, `gpt`, `swe`, …); перекрывается выбором в веб-селекте или `/models` (хранится в `tasks/model.txt`) |
| `DEVIN_PERMISSION_MODE` | `bypass` | Режим разрешений Devin CLI |
| `POLL_INTERVAL` | `30` | Период опроса `inbox/`, сек |
| `TASK_TIMEOUT` | `7200` | Таймаут одной задачи, сек |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | `devin-bot` | Git-идентичность для коммитов |
| `GIT_REPO_URL` | — | Клонируется в пустой `/workspace` при старте и перед каждой задачей |
| `GIT_BRANCH` | — | Ветка при клонировании |
| `DEVIN_INSTRUCTIONS_FILE` | — | Доп. инструкции, добавляются в промпт |
| `DEVIN_EXTRA_ARGS` | — | Доп. флаги для `devin` |
| `TELEGRAM_BOT_TOKEN` | — (выкл) | Токен бота — включает telegram-пингер |
| `CHAT_ID` | — | Числовой id чата; иначе ловится из `getUpdates` по `TG_USERNAME` |
| `TG_USERNAME` | `kiloper` | Username для авто-детекта chat_id |
| `MESSAGE_TEXT` | `привет` | Текст сообщения |
| `INTERVAL` | `60` | Период отправки, сек |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | — | Исходящий прокси для devin API и telegram; git всегда напрямую |
| `TELEGRAM_WEBHOOK_URL` | — | Публичный URL — регистрируется setWebhook при старте |
| `TELEGRAM_WEBHOOK_SECRET` | — | Секрет для проверки заголовка webhook |
| `MYSQL_HOST` / `MYSQL_PORT` | `mysql` / `3306` | Хост БД — по умолчанию сервис `mysql` из compose; можно указать внешний |
| `MYSQL_USER` / `MYSQL_PASSWORD` | `devin` / — | Пользователь и пароль (обязательны) |
| `MYSQL_DATABASE` | `devin_worker` | База; таблицы `tasks`/`kv`/`pending` создаются сами |
| `GEMINI_API_KEY` | — | Ключ Gemini для распознавания голосовых |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Модель Gemini для STT |
| `STT_PROVIDER` | `gemini` | `gemini` / `openai` (OpenAI-совместимый API) / `yandex`; через запятую — цепочка запасных (`gemini,openai`) |
| `STT_API_KEY` | — | Ключ STT: OpenAI/Groq токен или `Api-Key` Яндекс.Облака |
| `STT_BASE_URL` | `https://api.openai.com/v1` | Базовый URL STT API (для `openai`) |
| `STT_MODEL` | `whisper-1` | Модель STT (напр. `whisper-large-v3-turbo` у Groq) |
| `YANDEX_FOLDER_ID` | — | Папка Яндекс.Облака (опционально) |
| `YANDEX_LANG` | `ru-RU` | Язык распознавания SpeechKit |

## Прокси

**Встроенный mihomo (Clash Meta) — рекомендуемый вариант.** В образ уже
вшит бинарник mihomo; если рядом с compose-файлом есть `mihomo/config.yaml`,
watcher сам поднимает его при старте, и трафик devin API и telegram идёт
через `http://127.0.0.1:7890` → дальше на ноды из конфига (VLESS и т.д.):

```bash
mkdir -p mihomo
cp mihomo.example.yaml mihomo/config.yaml   # впиши свои ноды в proxies:
docker compose up -d
```

Шаблон группы `Прокси` — `url-test` с `include-all`: ноды подхватываются
из `proxies:` автоматически, ездит через самую быструю. Менять ноду —
править `mihomo/config.yaml` и `docker compose restart devin`.
`mihomo/` в `.gitignore` — ключи подписки не уедут в репо.

**Внешний прокси** — если mihomo не нужен, а прокси один готовый:

```bash
HTTP_PROXY=http://user:password@proxy.company.local:3128
HTTPS_PROXY=http://user:password@proxy.company.local:3128
```

Прокси применяется к **Devin API** (`proxy.mode=manual` в конфиге devin) и
**telegram-боту** (явный `ProxyHandler`, креды маскируются в логах).
Явные `HTTP(S)_PROXY` имеют приоритет над mihomo; пусто + нет
`mihomo/config.yaml` = прямые соединения.

**Git прокси игнорирует**: `http.proxy ""` в gitconfig + срезание `*_proxy`
для clone/pull/push — работает и для команд git, которые запускает сам
агент. SSH и HTTPS remote идут напрямую независимо от прокси.

**Яндекс SpeechKit тоже напрямую**: запросы STT ходят отдельным opener'ом,
игнорирующим любой прокси — РФ-сервису европейский выход не нужен.

## One-shot режим (без compose)

```bash
docker run --rm \
    -e DEVIN_MODEL=opus \
    -e GIT_USER_NAME="Yura" -e GIT_USER_EMAIL="yura@example.com" \
    -v /path/to/repo:/workspace \
    -v /path/to/task.txt:/task/task.txt:ro \
    -v ./devin-data:/root/.local/share/devin \
    -v ~/.ssh:/root/.ssh:ro \
    ghcr.io/kilopers/devin-cli:latest
```

## Что делает контейнер

При старте вотчера: если `/workspace` пуст и задан `GIT_REPO_URL` — репо
клонируется сразу (ошибки авторизации видны в логах сразу, а не на первой задаче).

Для каждой задачи:

1. `git pull --ff-only` в `/workspace` (если репо ещё нет — клонирует по `GIT_REPO_URL`).
2. Проверяет авторизацию (`devin auth status`).
3. Промпт = инструкции репозитория (`AGENTS.md`, `.devin/` и т.п.) + задача +
   обязательство `git add -A` → commit → push.
4. `devin -p` в режиме `bypass`.
5. Safety-net: незапушенные коммиты допушиваются самим скриптом.

## Git push

- **SSH**: смонтирован `~/.ssh` (host key принимается автоматически,
  `UserKnownHostsFile=/dev/null`).
- **HTTPS**: `GIT_REPO_URL` вида `https://user:token@host/repo.git`
  или `~/.git-credentials` (добавь маунт в compose).

## Локальная сборка

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
    -t ghcr.io/kilopers/devin-cli:latest --push .
```

Ставится всегда свежий Devin CLI (`install.sh` → latest).

## Замечания

- Контейнер работает от `root` — файлы агента в `/workspace` будут root'овые.
- `bypass` авто-аппрувит все команды агента — изоляция только сам контейнер.
- Раньше Devin CLI был запинен на `3000.10.48` из-за пустого списка моделей
  при создании сессии (`Available models:` пустой, любой `--model` падал с
  `Unknown model`). Причиной оказался не релиз, а внешний HTTP-прокси: запрос
  `GetCliModelConfigs` (remote config) через него не укладывался в таймаут.
  Со встроенным mihomo проблема ушла — пин снят, проверка:
  `devin -p "ping" --model adaptive --respect-workspace-trust false`.
