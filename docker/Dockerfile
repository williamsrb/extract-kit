# syntax=docker/dockerfile:1
# Image for `extractkit headless` in a pipeline. Build from the repo root:
#   docker build -f docker/Dockerfile -t extractkit-headless .
# Every tool version is a build argument; the last step fails the build when a
# required tool is broken.

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

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# System tools, Node (tarball, so its version is pinned) and the Python modules the kit imports.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates xz-utils \
    && arch="$(dpkg --print-architecture | sed 's/amd64/x64/')" \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz" \
       | tar -xJ -C /usr/local --strip-components=1 \
    && pip install "pyyaml==${PYYAML_VERSION}" "jsonschema==${JSONSCHEMA_VERSION}" "uv==${UV_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# graft, the agent CLIs and Playwright with Chromium. graft compiles native
# tree-sitter modules, so the compiler is installed for this step only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && npm install -g \
        "@nanonets/graft@${GRAFT_VERSION}" \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@openai/codex@${CODEX_VERSION}" \
        "playwright@${PLAYWRIGHT_VERSION}" \
        "@playwright/cli@${PLAYWRIGHT_CLI_VERSION}" \
    && apt-get purge -y --auto-remove build-essential \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /opt/ms-playwright \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# The agent CLIs refuse some permission modes as root, so everything below runs as a normal user.
RUN useradd --create-home --uid 1000 extract
USER extract
ENV HOME=/home/extract \
    PATH=/home/extract/.local/bin:${PATH}

# Serena and Graphify through uv.
RUN uv tool install "serena-agent==${SERENA_VERSION}" \
    && uv tool install "graphifyy==${GRAPHIFY_VERSION}"

# Install the kit from a bind-mounted copy of the build context. The mount
# exists only for this step, so no copy of the checkout stays in any layer, and
# every build proves the detached install works.
RUN --mount=type=bind,target=/build/kit \
    python3 /build/kit/extractkit install

WORKDIR /work

# A broken required tool fails the build here.
RUN extractkit deps --profile enonic --json > /dev/null

ENTRYPOINT ["extractkit", "headless", "--json"]
CMD ["--source", "/work"]
