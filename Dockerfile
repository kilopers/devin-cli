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
        make \
        socat \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Devin CLI.
# install.sh finishes by launching the interactive `devin setup` wizard —
# strip that line so the image build stays non-interactive.
# Install under /opt/devin-install (not the default ~/.local/share/devin) so the
# persistent data-dir mount doesn't shadow the installed binary.
RUN curl -fsSL https://cli.devin.ai/install.sh -o /tmp/devin-install.sh \
    && sed -i 's|"\$VERSION_DIR/bin/\$COMPILED_BIN_NAME" setup|true|' /tmp/devin-install.sh \
    && XDG_DATA_HOME=/opt/devin-install bash /tmp/devin-install.sh \
    && rm -f /tmp/devin-install.sh

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

COPY entrypoint.sh /usr/local/bin/devin-task
COPY watcher.py /app/watcher.py
COPY webui.html /app/webui.html
COPY bot.py /app/bot.py
RUN chmod +x /usr/local/bin/devin-task /app/watcher.py /app/bot.py

WORKDIR /workspace

ENTRYPOINT ["devin-task"]
