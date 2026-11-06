# --- web UI build: React + MUI bundled by esbuild → /app/static/app ---
FROM node:22-bookworm-slim AS webui-build
WORKDIR /repo
COPY webui/package.json webui/package-lock.json webui/
RUN cd webui && npm ci --no-audit --no-fund
COPY webui/ webui/
RUN cd webui && npm run build    # writes /repo/static/app/{webui,login}.js

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        openssh-client \
        ripgrep \
        jq \
        python3 \
        python3-pymysql \
        python3-cryptography \
        python3-flask \
        python3-waitress \
        make \
        socat \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# Установка Devin CLI (всегда latest: пустой список моделей был не версией,
# а таймаутом remote config через внешний прокси — лечится mihomo ниже).
# install.sh завершается запуском интерактивного `devin setup` — строка
# вырезается, сборка не виснет. Ставим в /opt/devin-install (а не в
# ~/.local/share/devin), чтобы примонтированный data-dir не перекрыл бинарник.
RUN curl -fsSL https://cli.devin.ai/install.sh -o /tmp/devin-install.sh \
    && sed -i 's|"\$VERSION_DIR/bin/\$COMPILED_BIN_NAME" setup|true|' /tmp/devin-install.sh \
    && XDG_DATA_HOME=/opt/devin-install bash /tmp/devin-install.sh \
    && rm -f /tmp/devin-install.sh

# mihomo (Clash Meta) — локальный HTTP/SOCKS5-прокси внутри контейнера.
# Слушает 127.0.0.1:7890; watcher запускает его, только если смонтирован
# /mihomo/config.yaml (см. mihomo.example.yaml). Нужен, когда devin API /
# telegram доступны только через VLESS-ноды (geoblock). Трафик дальше уходит
# на ноды из конфига; git по-прежнему идёт напрямую (env срезается).
# compatible-сборка — работает на любом amd64 без требований к микроархитектуре.
ARG MIHOMO_VERSION=v1.19.32
RUN curl -fsSL "https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/mihomo-linux-amd64-compatible-${MIHOMO_VERSION}.gz" \
        | gunzip > /usr/local/bin/mihomo \
    && chmod +x /usr/local/bin/mihomo \
    && mihomo -v

# Toolchain for user projects: Node.js 22 LTS (npm/Vite) + PHP 8.5 + Composer.
# Dev servers the agent starts stay inside the container — it reaches them on
# localhost directly, no host port mapping needed.
RUN curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/nodesource.gpg \
    && echo "deb https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && curl -fsSL https://packages.sury.org/php/apt.gpg \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/sury-php.gpg \
    && echo "deb https://packages.sury.org/php/ bookworm main" \
        > /etc/apt/sources.list.d/sury-php.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
        zip unzip \
        php8.5-cli php8.5-mbstring php8.5-xml php8.5-curl php8.5-zip \
        php8.5-intl php8.5-gd php8.5-bcmath php8.5-sqlite3 \
        php8.5-mysql php8.5-pgsql \
    && rm -rf /var/lib/apt/lists/* \
    && php -r "copy('https://getcomposer.org/installer', '/tmp/composer-setup.php');" \
    && php /tmp/composer-setup.php --install-dir=/usr/local/bin --filename=composer --quiet \
    && rm -f /tmp/composer-setup.php \
    && node --version && npm --version && php --version | head -1 && composer --version

ENV PATH="/root/.local/bin:${PATH}"
# Accept new SSH host keys without prompting (ssh dir is mounted read-only).
ENV GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null"

# Deterministic unattended defaults: no background self-update inside containers.
RUN mkdir -p /root/.config/devin \
    && echo '{ "version": 1, "auto_update": false }' > /root/.config/devin/config.json

# Claude Code CLI — движок «claude» реестра AGENTS (launcher claude-task).
RUN npm i -g @anthropic-ai/claude-code

# Chromium — headless-браузер для задач агента: просмотр страниц,
# скриншоты, эмуляция входа, CDP (--remote-debugging-port) для
# puppeteer-core/playwright. В контейнере всё идёт под root — Chromium
# без --no-sandbox не стартует, поэтому прямые вызовы лучше делать
# через обёртку chromium-safe (добавляет --no-sandbox,
# --disable-dev-shm-usage для маленького /dev/shm, --disable-gpu);
# google-chrome/chromium-browser и $CHROME_BIN/PUPPETEER_EXECUTABLE_PATH
# тоже указывают на неё — сторонние тулы подхватывают браузер сами.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && printf '#!/bin/sh\nexec /usr/bin/chromium --no-sandbox --disable-gpu --disable-dev-shm-usage "$@"\n' \
        > /usr/local/bin/chromium-safe \
    && chmod +x /usr/local/bin/chromium-safe \
    && ln -sf chromium-safe /usr/local/bin/google-chrome \
    && ln -sf chromium-safe /usr/local/bin/chromium-browser \
    && /usr/local/bin/chromium-safe --version
ENV CHROME_BIN=/usr/local/bin/chromium-safe \
    PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chromium-safe

COPY entrypoint.sh /usr/local/bin/devin-task
COPY claude-task.sh /usr/local/bin/claude-task
COPY claude-relay.py /usr/local/bin/claude-relay.py
COPY watcher.py /app/watcher.py
COPY watcher_parts/ /app/watcher_parts/
COPY VERSION /app/VERSION
COPY RELEASE_NOTES.md /app/RELEASE_NOTES.md
COPY templates/ /app/templates/
COPY static/ /app/static/
COPY --from=webui-build /repo/static/app/ /app/static/app/
COPY bot.py /app/bot.py
RUN chmod +x /usr/local/bin/devin-task /usr/local/bin/claude-task \
        /usr/local/bin/claude-relay.py /app/watcher.py /app/bot.py

WORKDIR /workspace

ENTRYPOINT ["devin-task"]
