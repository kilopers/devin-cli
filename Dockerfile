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
    && rm -rf /var/lib/apt/lists/*

# Install Devin CLI.
# install.sh finishes by launching the interactive `devin setup` wizard —
# strip that line so the image build stays non-interactive.
RUN curl -fsSL https://cli.devin.ai/install.sh -o /tmp/devin-install.sh \
    && sed -i 's|"\$VERSION_DIR/bin/\$COMPILED_BIN_NAME" setup|true|' /tmp/devin-install.sh \
    && bash /tmp/devin-install.sh \
    && rm -f /tmp/devin-install.sh

ENV PATH="/root/.local/bin:${PATH}"

# Deterministic unattended defaults: no background self-update inside containers.
RUN mkdir -p /root/.config/devin \
    && echo '{ "version": 1, "auto_update": false }' > /root/.config/devin/config.json

COPY entrypoint.sh /usr/local/bin/devin-task
COPY watcher.py /app/watcher.py
RUN chmod +x /usr/local/bin/devin-task /app/watcher.py

WORKDIR /workspace

ENTRYPOINT ["devin-task"]
