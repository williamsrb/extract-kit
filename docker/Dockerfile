# syntax=docker/dockerfile:1
# Image for `extractkit headless` in a pipeline. devkit (dev-kit) installs
# the tools, skills, kb and Serena MCP through its `extract` profile, so the
# image needs a checkout of it as the `devkit` build context. Build from the
# repo root:
#   docker build -f docker/Dockerfile --build-context devkit=<path-to-dev-kit> -t extractkit-ci .
# The versions of node, graft, serena, graphify and playwright-cli are pinned in
# devkit's profiles/extract.json; the rest are build arguments. The last steps
# fail the build when a required tool is broken. The default build has every
# feature. Slimmer variants drop parts with build arguments:
#   --build-arg WITH_PLAYWRIGHT=0   no Playwright or Chromium (the enonic baseline step)
#   --build-arg WITH_PHP=0          no php-cli or composer (the php profile)
#   --build-arg WITH_1PASSWORD=0    no 1Password CLI (`op`)
#   --build-arg AGENTS="claude"     only these agent CLIs: claude, codex, cursor
#   --build-arg RUN_AS=root         start as root instead of uid 1000, for runners
#                                   that check the source out as root (see docker/README.md)
#   --build-arg DEVKIT_PROFILE=NAME the devkit profile to install (default: extract)

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG PYYAML_VERSION=6.0.2
ARG JSONSCHEMA_VERSION=4.23.0
ARG UV_VERSION=0.11.25
ARG PLAYWRIGHT_VERSION=1.63.0
ARG CLAUDE_CODE_VERSION=2.1.284
ARG CODEX_VERSION=0.151.0
ARG WITH_PLAYWRIGHT=1
ARG WITH_PHP=1
ARG WITH_1PASSWORD=1
ARG AGENTS="claude codex cursor"
ARG RUN_AS=extract
ARG DEVKIT_PROFILE=extract

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# System tools, `sudo` for the devkit bootstrap (removed again below) and the Python modules the kit imports. 7-Zip, Node, graft, Serena and Graphify come from devkit.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates xz-utils sudo \
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

COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/extractkit-entrypoint
# Copy of the script the 1Password jobs of the other pipelines call: turns a vault name into its ID.
COPY --chmod=0755 docker/filter-by-name.sh /filter-by-name.sh

# The agent CLIs refuse some permission modes as root, so everything below runs
# as a normal user. devkit refuses root and its bootstrap needs sudo: the user
# gets a passwordless sudoers entry that is removed again before the image ends.
RUN useradd --create-home --uid 1000 extract \
    && echo "extract ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/extract \
    && chmod 0440 /etc/sudoers.d/extract
USER extract
ENV HOME=/home/extract \
    DEVKIT_HEADLESS=1 \
    PATH=/home/extract/.local/node-bin:/home/extract/.local/bin:${PATH}

# devkit's tools for the profile: node (through nvm), graft, Serena, Graphify,
# playwright-cli and 7-Zip. Third-party apt sources are not wanted.
RUN --mount=type=bind,from=devkit,target=/opt/devkit \
    cd /opt/devkit && ./bootstrap.sh --profile ${DEVKIT_PROFILE} --apply --third-party no

# nvm keeps node under $HOME and not on the entrypoint's PATH: link it to a fixed place.
RUN ln -sfn "$(ls -d "$HOME"/.nvm/versions/node/*/bin | head -n1)" "$HOME/.local/node-bin"

# Playwright with Chromium. The profile carries only playwright-cli; the browser stays here so WITH_PLAYWRIGHT=0 drops it.
RUN if [ "${WITH_PLAYWRIGHT}" = 1 ]; then \
        npm install -g "playwright@${PLAYWRIGHT_VERSION}" \
        && sudo env "PATH=$PATH" playwright install-deps chromium \
        && sudo install -d -o extract /opt/ms-playwright \
        && playwright install chromium; \
    fi

# The selected agent CLIs. They come before devkit's install.py: a profile
# wrapper bakes in the path of the vendor CLI it finds at that time.
RUN set -eu; \
    pkgs=""; \
    for agent in ${AGENTS}; do \
        case "${agent}" in \
            claude) pkgs="${pkgs} @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" ;; \
            codex) pkgs="${pkgs} @openai/codex@${CODEX_VERSION}" ;; \
            cursor) ;; \
            *) echo "unknown agent '${agent}' in AGENTS; use claude, codex, cursor" >&2; exit 1 ;; \
        esac; \
    done; \
    if [ -n "${pkgs}" ]; then npm install -g ${pkgs}; fi

# cursor-agent, from Cursor's official installer into ~/.local/bin. Unlike the
# other tools it has no pinned release, so a rebuild can pick up a newer
# version than docs/headless.md names; `--agent cursor` is the only user.
RUN case " ${AGENTS} " in \
        *" cursor "*) curl -fsS https://cursor.com/install | bash && cursor-agent --version ;; \
    esac

# The devkit profile instances (claude-extract, codex-extract, cursor-agent's
# wrapper), the profile's skills and kb, and Serena registered for each agent.
# Headless: no launchers, URL handlers or app forks.
RUN --mount=type=bind,from=devkit,target=/opt/devkit \
    cd /opt/devkit && ./install.py --profile ${DEVKIT_PROFILE} --headless --apply

# Install the kit from a bind-mounted copy of the build context. The mount
# exists only for this step, so no copy of the checkout stays in any layer, and
# every build proves the detached install works.
RUN --mount=type=bind,target=/build/kit \
    python3 /build/kit/extractkit install

# Drop the build-time sudo, then prove: no GUI paths, no sudo, a healthy devkit.
RUN sudo rm -f /etc/sudoers.d/extract \
    && test ! -e "$HOME/.local/share/applications" \
    && ! sudo -n true 2>/dev/null \
    && devkit doctor

ENV EXTRACTKIT_DEVKIT_PROFILE=${DEVKIT_PROFILE}
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
