# devin-cli-docker

Docker-образ с [Devin CLI](https://devin.ai) для автономного выполнения задач.

Два режима:

- **watcher** (docker-compose, для сервера) — следит за `tasks/inbox/`,
  прогоняет каждую новую txt-задачу через Devin (pull → задача → commit → push)
  и пишет ответ в `tasks/outbox/`.
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

## Как кидать задачи

```bash
echo "Добавь endpoint /healthz, возвращающий 200" > tasks/inbox/task-001.txt
```

Вотчер каждые `POLL_INTERVAL` секунд (default 30) забирает самый старый
`*.txt` из `tasks/inbox/`, выполняет его и:

- перемещает задачу в `tasks/done/`
- пишет полный вывод Devin в `tasks/outbox/task-001.response.txt`

Задачи выполняются последовательно, по одной.

## Telegram webhook: голос → задача → ответ

Если задан `TELEGRAM_WEBHOOK_URL` — вотчер сам регистрирует webhook у Telegram
(`setWebhook`) и принимает апдейты POST'ом на **любой** путь статус-сервера
(например `https://build.kilop.ru/anything` — зависит от того, как
nginx режет путь; работает всегда).

Поток:

1. Голосовое → `getFile` → OGG → STT (`STT_PROVIDER`: yandex / gemini /
   openai-compatible) → текст.
2. В чат приходит распознанный текст с inline-кнопками
   **«✅ Принять» / «❌ Отмена»** (pending-записи — `tasks/tg-pending.json`).
   Пока pending открыт, любые новые сообщения (текст и голос) **дописываются**
   к нему, а сообщение с кнопками обновляется.
3. «Принять» → `tasks/inbox/tg-*.txt` + маппинг `task → chat_id` в
   `tasks/tg-chats.json`. «Отмена» → pending удаляется.
4. Когда задача отработает — в чат прилетает статус и хвост `outbox`-ответа.

**Команды бота** (кнопка Menu у поля ввода регистрируется автоматически):

- `/menu` — inline-меню: «🧠 Модели», «📊 Статус»
- `/models` — список моделей аккаунта (`devin models list`), каждая —
  кнопка переключения. Выбор хранится в `tasks/model.txt` и действует
  на следующие задачи (имеет приоритет над `DEVIN_MODEL`)
- `/model <name>` — переключить модель напрямую
- `/status` — uptime, очередь, текущая/последняя задача, модель

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

## Статус-страница

Вотчер отдаёт простую страницу `http://server/` (проброс `${WEB_PORT:-80}:8080`)
со статусом: uptime, HEAD репозитория, очередь задач, текущая и последняя
задача, состояние telegram-бота.

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
| `DEVIN_MODEL` | `swe` | Модель (`opus`, `sonnet`, `gpt`, `swe`, …) |
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
| `GEMINI_API_KEY` | — | Ключ Gemini для распознавания голосовых |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Модель Gemini для STT |
| `STT_PROVIDER` | `gemini` | `gemini` / `openai` (OpenAI-совместимый API) / `yandex` |
| `STT_API_KEY` | — | Ключ STT: OpenAI/Groq токен или `Api-Key` Яндекс.Облака |
| `STT_BASE_URL` | `https://api.openai.com/v1` | Базовый URL STT API (для `openai`) |
| `STT_MODEL` | `whisper-1` | Модель STT (напр. `whisper-large-v3-turbo` у Groq) |
| `YANDEX_FOLDER_ID` | — | Папка Яндекс.Облака (опционально) |
| `YANDEX_LANG` | `ru-RU` | Язык распознавания SpeechKit |

## Прокси

Если devin API и telegram доступны только через прокси, задай в `.env`:

```bash
HTTP_PROXY=http://user:password@proxy.company.local:3128
HTTPS_PROXY=http://user:password@proxy.company.local:3128
```

Прокси применяется к **Devin API** (`proxy.mode=manual` в конфиге devin) и
**telegram-боту** (явный `ProxyHandler`, креды маскируются в логах).
Пустые значения = прямые соединения.

**Git прокси игнорирует**: `http.proxy ""` в gitconfig + срезание `*_proxy`
для clone/pull/push — работает и для команд git, которые запускает сам
агент. SSH и HTTPS remote идут напрямую независимо от прокси.

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

## Замечания

- Контейнер работает от `root` — файлы агента в `/workspace` будут root'овые.
- `bypass` авто-аппрувит все команды агента — изоляция только сам контейнер.
