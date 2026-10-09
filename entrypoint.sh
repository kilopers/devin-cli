#!/usr/bin/env bash
# devin-task — run Devin CLI non-interactively inside Docker.
#
# Flow: (clone | mounted) repo -> git pull -> read repo instructions ->
#       execute task file -> commit & push.
#
# Configuration (env vars):
#   DEVIN_WORKDIR            Repo directory inside the container (default: /workspace)
#   DEVIN_TASK_FILE          Path to the task .txt file    (default: /task/task.txt)
#   DEVIN_MODEL              Model to use                  (default: swe)
#   DEVIN_PERMISSION_MODE    Permission mode               (default: bypass)
#   DEVIN_INSTRUCTIONS_FILE  Optional extra instructions file appended to the prompt
#   DEVIN_EXTRA_ARGS         Extra flags appended to the devin invocation
#   GIT_REPO_URL             If set and WORKDIR is empty — clone instead of requiring a mount
#   GIT_BRANCH               Branch for the clone (optional)
#   GIT_USER_NAME            git user.name for commits  (else uses mounted ~/.gitconfig)
#   GIT_USER_EMAIL           git user.email for commits (else uses mounted ~/.gitconfig)
#   GIT_SSH_COMMAND          Overrides the default ssh command used by git
set -euo pipefail

log()  { printf '\033[1;34m[devin-task]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[devin-task] WARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[devin-task] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

WORKDIR="${DEVIN_WORKDIR:-/workspace}"
TASK_FILE="${DEVIN_TASK_FILE:-/task/task.txt}"
INSTRUCTIONS_FILE="${DEVIN_INSTRUCTIONS_FILE:-}"
MODEL="${DEVIN_MODEL:-swe}"
PERMISSION_MODE="${DEVIN_PERMISSION_MODE:-bypass}"

# --- git setup -------------------------------------------------------------
[ -n "${GIT_USER_NAME:-}" ]  && git config --global user.name  "$GIT_USER_NAME"
[ -n "${GIT_USER_EMAIL:-}" ] && git config --global user.email "$GIT_USER_EMAIL"
# Mounted repos are owned by the host uid — never fail on "dubious ownership".
git config --global --add safe.directory '*'
# Accept new host keys without prompting; don't persist them (ssh dir may be read-only).
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null}"

# --- 1. get the repo -------------------------------------------------------
if [ ! -d "$WORKDIR/.git" ]; then
    if [ -n "${GIT_REPO_URL:-}" ]; then
        log "Cloning $GIT_REPO_URL -> $WORKDIR"
        mkdir -p "$WORKDIR"
        git clone ${GIT_BRANCH:+--branch "$GIT_BRANCH"} "$GIT_REPO_URL" "$WORKDIR"
    elif [ ! -f "$TASK_FILE" ] && [ -t 0 ]; then
        warn "No repo and no task file — starting an interactive devin session."
        mkdir -p "$WORKDIR" && cd "$WORKDIR"
        exec devin "$@"
    else
        die "$WORKDIR is not a git repository. Mount one with -v /path/to/repo:$WORKDIR or set GIT_REPO_URL."
    fi
fi
cd "$WORKDIR"

# --- 2. pull latest --------------------------------------------------------
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    log "Pulling latest changes (ff-only)"
    git pull --ff-only || die "git pull --ff-only failed (history diverged?). Fix the checkout and retry."
else
    warn "No upstream configured for the current branch — skipping git pull."
fi
log "HEAD: $(git log -1 --oneline)"

# --- 3. auth check ---------------------------------------------------------
if ! devin auth status >/dev/null 2>&1; then
    warn "Not authenticated. Mount ~/.local/share/devin/credentials.toml or set WINDSURF_API_KEY."
fi

# --- 4. build the prompt ---------------------------------------------------
[ -f "$TASK_FILE" ] || die "Task file not found: $TASK_FILE (mount it with -v /path/task.txt:$TASK_FILE:ro)"
TASK="$(cat "$TASK_FILE")"
[ -n "$(printf '%s' "$TASK" | tr -d '[:space:]')" ] || die "Task file is empty: $TASK_FILE"

EXTRA=""
if [ -n "$INSTRUCTIONS_FILE" ] && [ -f "$INSTRUCTIONS_FILE" ]; then
    EXTRA="$(cat "$INSTRUCTIONS_FILE")"
fi

PROMPT_FILE="$(mktemp /tmp/devin-prompt.XXXXXX)"
cat > "$PROMPT_FILE" <<EOF
You are running autonomously inside a Docker container. No human can answer questions — make reasonable decisions on your own.

The repository at $WORKDIR has already been pulled to the latest upstream commit.

First, read and follow the repository's own instructions and conventions (AGENTS.md, CLAUDE.md, CONTRIBUTING.md, .devin/, .windsurf/, .cursor/rules, README.md — whatever exists).

Then complete this task:

<task>
$TASK
</task>
${EXTRA:+
Additional instructions:
<instructions>
$EXTRA
</instructions>
}
When you are done:
1. Verify your work — run the repo's tests/linters/build if they exist.
2. Stage ALL changes: git add -A
3. Commit with a clear, conventional message.
4. Push to the current branch's upstream with git push. Do not force-push, do not open a PR.

Finally, print a short summary of what you did.
EOF
PROMPT="$(cat "$PROMPT_FILE")"

# --- 5. run devin ----------------------------------------------------------
log "Running devin (model=$MODEL, permission-mode=$PERMISSION_MODE)"
# shellcheck disable=SC2086
devin --model "$MODEL" \
      --permission-mode "$PERMISSION_MODE" \
      --respect-workspace-trust false \
      -p "$PROMPT" ${DEVIN_EXTRA_ARGS:-} "$@"

# --- 6. safety net ---------------------------------------------------------
if [ -n "$(git status --porcelain)" ]; then
    warn "Working tree still has uncommitted changes:"
    git status --short >&2
fi
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1 \
    && [ -n "$(git log '@{u}..HEAD' --oneline)" ]; then
    warn "Unpushed commits detected — pushing as a fallback."
    git push || warn "Fallback git push failed — push manually."
fi

log "Done."
