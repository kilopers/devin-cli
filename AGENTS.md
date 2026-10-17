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

## Версия

- При **каждом** изменении поднимай патч-версию в файле `VERSION`
  (0.0.1 → 0.0.2 → …, semver). watcher читает её в `APP_VERSION`
  (`/app/VERSION`, env `VERSION_FILE`) и отдаёт в `/api/status.version`;
  веб показывает серым в шапке рядом с названием — так видно, какая сборка
  реально стоит на сервере.

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
  (default `/app/templates`). Стек веба — **React + MUI** (не vanilla JS,
  не Materialize): исходники `webui/src/*.jsx`, сборка `npm run build`
  (esbuild) → `static/app/*.js` (в .gitignore; Dockerfile-стадия
  `webui-build` собирает в образе, `npm ci` требует package-lock.json).
  `/login` — MUI-форма (login.jsx), ошибка — переменная `error` шаблона.
  Версии: MUI 9.4, x-tree-view 9.14 (с ним пин `@mui/x-internals` той же
  версии — у них exports расходятся между минорками), React 19.
  Мобильная адаптация — брейкпоинты MUI `sx`/`useMediaQuery` (Drawer
  temporary на <md), matchMedia-хаков больше нет. Композер — `Grid`
  (xs: поле 12, кнопки 12 во вторую строку; «В работу» size=small).
  Шапка `AppBar position="fixed"` + `<Toolbar variant="dense"/>`-спейсер —
  всегда прижата к верху. Drawer — `SwipeableDrawer` (свайп от левого
  края открывает меню; на iOS swipe-to-open выключен — конфликт с жестом
  «назад» Safari); скролл меню переживает ререндеры (ref+useLayoutEffect).
  Название приложения — **WebDev** (шапка, drawer, login, manifest).
  ConnBadge живёт в шапке рядом с `(v…)` — точка связи + авторелоад по
  `event: version`. На <md композер — textarea + MUI `BottomNavigation`
  [Меню | Запись/Стоп | (Ещё раз) | В работу]; send активен только при
  непустом тексте; статус распознавания — строкой под textarea.
  `/api/tasks` отдаёт per-item хэш `h` (md5 статуса+output) — фронт
  заменяет элементы `feed` только при смене хэша и `TaskCard` обёрнут
  в `React.memo`: лента не мерцает на идентичных опросах.
  Иконка приложения — фиолетовая шестерёнка с `</>`, генерируется скриптом
  `scripts/gen_icon.py` (Pillow → png/ico + векторный favicon.svg из той же
  геометрии; файлы `static/favicon.svg|favicon.ico|icon.png|apple-icon.png`,
  отдаётся штатным `/static/*`; `/favicon.ico` — отдельный роут, иначе браузеры ловили
  status-page из catch-all). Установка на рабочий стол телефона — PWA:
  `static/manifest.webmanifest` + `sw.js` с роута `/sw.js` (нужен заголовок
  `Service-Worker-Allowed: /` — скоуп шире `/static/`); SW кэширует только
  `/static/*`, `/api/*` и POST'ы идут в сеть. Проект выбирается селектом в
  шапке (`ProjectSelect`, после названия+версии; `POST /api/project` →
  `kv.project_web`, сохраняется между логинами); пункт «➕ Добавить
  проект…» в селекте и drawer → `AddProject.jsx` (папка+URL+токен →
  `POST /api/project/add` клонирует в `PROJECTS_ROOT/<folder>`,
  https-URL получает `x-access-token:`/`oauth2:`-инжект, вывод clone
  показывается тёмным `<pre>` в модалке, токен маскируется `***`; токен необязателен — при пустом берётся ключ из `kv.git_creds` по домену хоста, иначе ошибка «для <host> нет ключа»). Мультиюзер: таблицы `users` (логин+pbkdf2-хэш) и `project_owner` (папка общая, принадлежность в базе; неразмеченные лениво → админ). Админ = `WEB_ADMIN_USER` в kv. Профиль-меню у админа имеет «Пользователи» (`Users.jsx`: список/создать/удалить; при удалении проекты → админу). Клик по юзеру → модалка прав `project_acl` (name,user): выданные проекты видны в его селекте и доступны везде (`_owns_project` = owner или acl), но owner не меняется — push идёт ключом владельца (токен в remote), а ротация своего ключа юзером трогает только его собственные проекты (`_cred_propagate` по `owner`). `/api/users*` только для админа, `/api/password` по текущему uid, ключи — `kv.git_creds:<uid>` (у админа fallback на старый `git_creds`). Проекты фильтруются: `/api/projects`, `_proj_root`/файлы/диффы/таски — `abort(403)` на чужом; клон пишет owner=текущий юзер; пропагация токена — только по своим проектам. Онбординг: у нового юзера проектов нет → сразу модалка ключей, при закрытии — модалка добавления репозитория. Рабочие пространства (`Workspaces.jsx`, меню профиля): таблицы `workspaces` (owner/name/color/is_default; дефолт «По умолчанию» создаётся каждому юзеру, удалить нельзя — только переименовать) и `project_ws` (user+name→ws — привязка ПО-ЮЗЕРНАЯ: зашаренный проект падает в дефолт получателя, клон — в выбранное в AddProject). Активное — `kv.ws:<uid>` (`/api/ws*` CRUD+active, `/api/project/ws` перенос); `/api/projects` фильтрует по активному ws и отдаёт `wsmap` для цветных точек в селекте (клик по точке → меню переноса). Цвет активного ws красит AppBar и мобильный BottomNavigation (`accent`-проп Composer). Per-user креды: `kv.us:<uid>` (JSON; секреты `enc:v1:`-Fernet, ключ `kv.secret_key`). `uset(k,u,env)` — юзер → env → дефолт. `migrate_env_secrets()` разово сливает env в настройки админа (STT/Gemini/Yandex/Devin/TG/Git identity/gitlab base). STT-провайдеры, `run_task` (WINDSURF_API_KEY + git identity владельца проекта), reply_mode/model для веб-скоупа, gitlab.base_url в CI — всё per-user. «Настройки» в профиле (`Settings.jsx`, `GET/POST /api/settings`, маски `…хвост`, пустое = не менять, 🗑 = удалить). Настройки проекта (`kv.pj:<name>`): шестерёнка в селекте проектов → `ProjectSettings.jsx` (модель/режим/автокоммит, пустое = наследовать из `us:<uid>`; автокоммит по умолчанию ВЫКЛ → `GIT_AUTO_COMMIT` в `run_task`). Глобальные ModelSelect/ModeSelect из шапки и drawer убраны — модель/режим теперь per-проект и per-user. `GET/POST /api/project/settings`. Меню профиля (иконка человечка → MUI Menu): «Ключи репозиториев» (`RepoKeys.jsx` — список ключей из `kv.git_creds` {host: token}, маска `…хвост`; вложенная модалка «Новый ключ» — GitHub: только ключ, GitLab: домен+ключ), «Смена пароля», «Выход». `GET/POST /api/creds`, `POST /api/creds/delete`; при добавлении/смене ключа `_cred_propagate` переписывает origin-remote всех проектов этого хоста (`remote set-url`, тот же x-access-token/oauth2-инжект). `/api/build` тоже фолбечит на `_cred_get(host)` после токена из remote. Текстария композера растёт до 80vh (sx maxHeight на InputBase).
  Вкладок-проектов нет,
  в мобильном drawer список проектов продублирован. Смена проекта: расширение дерева применяется
  только после загрузки верхнего уровня (иначе expandedItems с
  несмонтированными id мог валить TreeView → белый экран); весь UI
  обёрнут в ErrBoundary — ошибка рендера показывается текстом вместо
  белой страницы. Справа в вебе —
  дерево файлов проекта (`GET /api/files` отдаёт один уровень, ленивое
  раскрытие аяксом; на мобильном — в drawer под «Файлы»). Раскрытые папки
  и scroll дерева сохраняются в localStorage per-проект
  (`ft:expanded:<p>`/`ft:scroll:<p>`) — переживают перезагрузку/релогин;
  скролл восстанавливается в два прохода (после ленивой подгрузки
  сохранённых каталогов).
  Блок «Изменения» — сворачиваемый список git-status файлов (`/api/diff`),
  клик → fullscreen-диалог с diff (`/api/diff/file`, hljs `diff`-подсветка;
  untracked → `git diff --no-index /dev/null`). В ленте ```diff-фенсы
  красятся своим `paintDiff` (hljs-тема не имеет цветов для diff) —
  эффект в `Markdown.jsx` без deps, т.к. опрос ленты перерендеривает и
  React сбрасывает innerHTML на сырой (цвета «пропадали через секунду»).
  Клик по файлу в дереве → fullscreen-редактор на CodeMirror 6
  (`FileEditor.jsx`; `GET /api/file` читает текст ≤1 МБ, `POST /api/file`
  пишет атомарно через tmp+replace; `..`/бинарники отсекаются).
  Бандл — ESM со `splitting`: языковые пакеты CodeMirror ленивыми чанками
  `static/app/chunks/*`, шаблоны грузят `<script type="module">`.
  `/api/tasks` теперь отдаёт только задачи запрошенного проекта (раньше project IS NULL показывались везде); `cleanup_legacy_files` при старте удаляет смигрированные done/outbox/*.txt и *.txt/json-состояние (inbox/ и .progress/ живые). Мобильный BottomNavigation — primary-синий с белыми подписями/иконками. В ленту diff задачи больше НЕ дописывается — всё в панели «Изменения».
  Индикатор связи — SSE `GET /api/stream` (EventSource, keepalive `: ping`
  15 с, `retry: 2000`): `ConnDot.jsx` в правом нижнем углу — зелёная точка
  онлайн, спиннер при автореконнекте, красная + «нет подключения» офлайн.
  Тот же стрим шлёт `event: version` с `APP_VERSION` — ConnDot сверяет с
  версией страницы (baseline из `/api/status`) и делает `location.reload()`,
  если сервер обновился; рядом с точкой показывается `v<версия>`.
  WebSocket не используем — waitress чистый WSGI. Кнопка «⛔ Стоп» — в шапке
  при `status.current_task` и на карточке running-задачи рядом с чипом
  «выполняется», «✖ удалить» на карточке queued-задачи → общий диалог
  (`confirm = {kind, name, stem}`) → `POST /api/stop` или
  `POST /api/task/cancel` (удаляет строку `tasks`, только status='queued';
  running → 409). `/api/tasks` обрезает старый «### Что изменилось в репо»
  из сохранённых output — история задач тоже чистая.
  (тот же `kill_task`, что и телеграм `/stop`). В композере: при ошибке
  STT запись сохраняется в `lastAudio` и рядом с микрофоном появляется
  «ещё раз» — повторная отправка того же WAV, аудио не теряется.
  Иконка сборки в заголовке «Изменения» — `GET /api/build`: парсит remote
  origin (`github.com` → Actions runs, `gitlab*` → pipelines API),
  статусы success/failed/running/canceled, клик → урл пайплайна.
  Под «Изменениями» своя секция «Сборки» (`BuildsPanel`) — последние
  6 прогонов из поля `runs` (иконка+имя+#N+ref+время, клик → урл прогона).
  Иконка — в кружке `IconButton` (видно что кликабельна); при ошибке API
  клик открывает **Popover** с подробным текстом (`_http_json` отдаёт
  `HTTP {code} {reason}: {body[:300]}`), при успехе — ссылку на прогон.
  Токен берётся и из remote URL (`x-access-token:ghp_…@github.com`,
  `oauth2:glpat-…@gitlab.com` — парсится из userinfo), иначе env;
  404 → подсказка «приватный/не найден → задай *_TOKEN».
  Кэш 60 с (`_BUILD_CACHE`); запросы через `TG_OPENER`. Токены —
  `GITHUB_TOKEN`/`GITLAB_TOKEN`/`GITLAB_BASE_URL` (env). Роуты под
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
  Распознаёт тем же `STT_PROVIDER` — он может быть списком через запятую
  (`gemini,openai`): `_stt_chain` разбирает, `_stt_run` пробует по очереди
  и собирает ошибки всех провайдеров; `_stt_ready` — проверка ключей.
  Для yandex в `web_transcribe` вилка:
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
