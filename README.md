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
# в .env прописать PROJECT_DIR=/path/to/repo, DEVIN_MODEL, git-идентичность

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

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `PROJECT_DIR` | — (обязательна) | Папка проекта на сервере, монтируется в `/workspace` |
| `DEVIN_MODEL` | `swe` | Модель (`opus`, `sonnet`, `gpt`, `swe`, …) |
| `DEVIN_PERMISSION_MODE` | `bypass` | Режим разрешений Devin CLI |
| `POLL_INTERVAL` | `30` | Период опроса `inbox/`, сек |
| `TASK_TIMEOUT` | `7200` | Таймаут одной задачи, сек |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | `devin-bot` | Git-идентичность для коммитов |
| `GIT_REPO_URL` | — | Клонировать репо, если `/workspace` пуст |
| `DEVIN_INSTRUCTIONS_FILE` | — | Доп. инструкции, добавляются в промпт |
| `DEVIN_EXTRA_ARGS` | — | Доп. флаги для `devin` |

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

## Что делает контейнер для каждой задачи

1. `git pull --ff-only` в `/workspace` (или клонирует по `GIT_REPO_URL`).
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
