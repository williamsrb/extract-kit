# syntax=docker/dockerfile:1
# Image for `extractkit headless` in a pipeline. Build from the repo root:
#   docker build -f docker/Dockerfile -t extractkit-ci .
# Every tool version is a build argument; the last step fails the build when a
# required tool is broken. The default build has every feature. Slimmer
# variants drop parts with build arguments:
#   --build-arg WITH_PLAYWRIGHT=0   no Playwright or Chromium (the enonic baseline step)
#   --build-arg WITH_PHP=0          no php-cli or composer (the php profile)
#   --build-arg WITH_1PASSWORD=0    no 1Password CLI (`op`)
#   --build-arg AGENTS="claude"     only these agent CLIs: claude, codex, cursor
#   --build-arg RUN_AS=root         start as root instead of uid 1000, for runners
#                                   that check the source out as root (see docker/README.md)

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG NODE_VERSION=22.23.1
ARG PYYAML_VERSION=6.0.2
ARG JSONSCHEMA_VERSION=4.23.0
ARG UV_VERSION=0.11.25
ARG GRAFT_VERSION=0.19.0
ARG GRAPHIFY_VERSION=0.9.73
ARG SERENA_VERSION=1.7.0
ARG PLAYWRIGHT_VERSION=1.63.0
ARG PLAYWRIGHT_CLI_VERSION=0.1.22
ARG CLAUDE_CODE_VERSION=2.1.280
ARG CODEX_VERSION=0.151.0
ARG WITH_PLAYWRIGHT=1
ARG WITH_PHP=1
ARG WITH_1PASSWORD=1
ARG AGENTS="claude codex cursor"
ARG RUN_AS=extract

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# System tools (7-Zip opens the password-protected agent credentials), Node (tarball, so its version is pinned) and the Python modules the kit imports.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates xz-utils p7zip-full \
    && arch="$(dpkg --print-architecture | sed 's/amd64/x64/')" \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz" \
       | tar -xJ -C /usr/local --strip-components=1 \
    && pip install "pyyaml==${PYYAML_VERSION}" "jsonschema==${JSONSCHEMA_VERSION}" "uv==${UV_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# PHP tooling for the php profile.
RUN if [ "${WITH_PHP}" = 1 ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends php-cli composer \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# 1Password CLI (`op`) from the official apt repository, set up the same way as
# the remote-deployer-ci images. The package is not pinned.
RUN if [ "${WITH_1PASSWORD}" = 1 ]; then \
        set -eux; \
        apt-get update; \
        apt-get install -y --no-install-recommends gnupg; \
        arch="$(dpkg --print-architecture)"; \
        curl -sS https://downloads.1password.com/linux/keys/1password.asc \
            | gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg; \
        echo "deb [arch=${arch} signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/${arch} stable main" \
            > /etc/apt/sources.list.d/1password.list; \
        mkdir -p /etc/debsig/policies/AC2D62742012EA22/ /usr/share/debsig/keyrings/AC2D62742012EA22; \
        curl -sS https://downloads.1password.com/linux/debian/debsig/1password.pol \
            > /etc/debsig/policies/AC2D62742012EA22/1password.pol; \
        curl -sS https://downloads.1password.com/linux/keys/1password.asc \
            | gpg --dearmor --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg; \
        apt-get update; \
        apt-get install -y --no-install-recommends 1password-cli; \
        op --version; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# graft, the selected agent CLIs and Playwright with Chromium. graft compiles
# native tree-sitter modules, so the compiler is installed for this step only.
RUN set -eu; \
    pkgs="@nanonets/graft@${GRAFT_VERSION}"; \
    for agent in ${AGENTS}; do \
        case "${agent}" in \
            claude) pkgs="${pkgs} @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" ;; \
            codex) pkgs="${pkgs} @openai/codex@${CODEX_VERSION}" ;; \
            cursor) ;; \
            *) echo "unknown agent '${agent}' in AGENTS; use claude, codex, cursor" >&2; exit 1 ;; \
        esac; \
    done; \
    if [ "${WITH_PLAYWRIGHT}" = 1 ]; then \
        pkgs="${pkgs} playwright@${PLAYWRIGHT_VERSION} @playwright/cli@${PLAYWRIGHT_CLI_VERSION}"; \
    fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && npm install -g ${pkgs} \
    && apt-get purge -y --auto-remove build-essential \
    && if [ "${WITH_PLAYWRIGHT}" = 1 ]; then \
        playwright install --with-deps chromium \
        && chmod -R a+rX /opt/ms-playwright; \
    fi \
    && rm -rf /var/lib/apt/lists/* /root/.npm

COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/extractkit-entrypoint
# Copy of the script the 1Password jobs of the other pipelines call: turns a vault name into its ID.
COPY --chmod=0755 docker/filter-by-name.sh /filter-by-name.sh

# The agent CLIs refuse some permission modes as root, so everything below runs as a normal user.
RUN useradd --create-home --uid 1000 extract
USER extract
ENV HOME=/home/extract \
    PATH=/home/extract/.local/bin:${PATH}

# Serena and Graphify through uv.
RUN uv tool install "serena-agent==${SERENA_VERSION}" \
    && uv tool install "graphifyy==${GRAPHIFY_VERSION}"

# The headless preflight onboards Serena through its MCP tools, so the agent
# needs the server in its own user config; installing the binary is not enough.
RUN case " ${AGENTS} " in \
        *" claude "*) claude mcp add --scope user serena -- \
            serena start-mcp-server --project-from-cwd --context=claude-code ;; \
    esac

# cursor-agent, from Cursor's official installer into ~/.local/bin. Unlike the
# other tools it has no pinned release, so a rebuild can pick up a newer
# version than docs/headless.md names; `--agent cursor` is the only user.
RUN case " ${AGENTS} " in \
        *" cursor "*) curl -fsS https://cursor.com/install | bash && cursor-agent --version ;; \
    esac

# Install the kit from a bind-mounted copy of the build context. The mount
# exists only for this step, so no copy of the checkout stays in any layer, and
# every build proves the detached install works.
RUN --mount=type=bind,target=/build/kit \
    python3 /build/kit/extractkit install

WORKDIR /work

# The tools live under /home/extract and are on PATH for either user. Only the
# start user differs.
USER ${RUN_AS}

# A broken required tool fails the build here.
RUN extractkit deps --profile enonic --json > /dev/null

# The entrypoint runs `extractkit headless --json` for flags and passes any other
# command through, so a pipeline runner can start a shell in the image. See
# docker/entrypoint.sh and docker/README.md.
ENTRYPOINT ["extractkit-entrypoint"]
CMD ["--source", "/work"]
