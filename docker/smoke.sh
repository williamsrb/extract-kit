#!/bin/sh
# Smoke test of the ways a pipeline starts the image. Usage: docker/smoke.sh IMAGE
# Plain sh on purpose: CI runs it in docker:29, which has no Python. Volumes
# instead of bind mounts, so it also works against a docker-in-docker daemon.
set -eu

image="${1:?usage: docker/smoke.sh IMAGE}"
volume="extractkit-smoke-$$"
failed=0

check() { # name, expected substring, command output
	if printf '%s' "$3" | grep -q -- "$2"; then
		echo "ok    $1"
	else
		echo "FAIL  $1 (wanted '$2')"
		printf '%s\n' "$3" | head -5 | sed 's/^/      /'
		failed=1
	fi
}

# 1. flags go to `extractkit headless` (the default CMD, compose, docker run)
check "flags reach headless" "usage: extractkit headless" "$(docker run --rm "$image" --help 2>&1 || true)"
# 2. the spelled-out form
check "headless subcommand" "usage: extractkit headless" "$(docker run --rm "$image" headless --help 2>&1 || true)"
# 3. any other extractkit command
check "extractkit command" "usage: extractkit" "$(docker run --rm "$image" extractkit --help 2>&1 || true)"
check "extractkit group" '"command": "deps"' "$(docker run --rm "$image" deps --profile core --json 2>&1 || true)"
# 4. a runner that pipes the job script into a shell, entrypoint kept (GitLab, Jenkins)
check "shell with stdin script" "job-ran" "$(printf 'echo job-ran\n' | docker run --rm -i "$image" sh 2>&1 || true)"
# 5. the same with the entrypoint cleared (`image:entrypoint: [""]`, `docker run --entrypoint ''`)
check "entrypoint cleared" "job-ran" "$(printf 'echo job-ran\n' | docker run --rm -i --entrypoint '' "$image" sh 2>&1 || true)"
# 6. the 1Password CLI is on PATH and reachable through the entrypoint
# (set SMOKE_WITHOUT_1PASSWORD=1 for an image built with WITH_1PASSWORD=0)
if [ "${SMOKE_WITHOUT_1PASSWORD:-}" = 1 ]; then
	echo "skip  1password cli (built without it)"
else
	check "1password cli" "[0-9]\\.[0-9]" "$(docker run --rm "$image" op --version 2>&1 || true)"
fi
# 6b. /filter-by-name.sh turns an `op vault list` table into the ID of the matching vault (needs no op)
table='ID    NAME
aaa1  Other
bbb2  CI Vault'
check "vault id lookup" "bbb2" "$(printf '%s\n' "$table" | docker run --rm -i "$image" sh -c '/filter-by-name.sh "$0"' CI 2>&1 || true)"
code=0
printf '%s\n' "$table" | docker run --rm -i "$image" sh -c '/filter-by-name.sh "$0"' Nope > /dev/null 2>&1 || code=$?
check "vault id lookup without match" "1" "$code"
# 6c. 7z writes a password-protected archive and reads it back to stdout, as the pipeline job does
check "7zip round trip" "dummy-ok" "$(docker run --rm "$image" sh -c 'cd "$(mktemp -d)" && echo "k: dummy-ok" > k.yaml && 7z a -mhe=on -ppass k.yaml.7z k.yaml > /dev/null && 7z x -so -ppass k.yaml.7z' 2>&1 || true)"
# 6d. `extractkit assets` reads attachments by content: a yaml resource of any name, a bad file reported, exit 0
check "assets command" "agent_api_key" "$(docker run --rm "$image" sh -c 'd=$(mktemp -d) && printf "resource:\n  type: agent_api_key\n  data:\n    token: x\n    agent: claude\n" > "$d/any-name.bin" && echo junk > "$d/bad.txt" && cd "$d" && extractkit assets --assets-dir "$d" && echo assets-exit-$?' 2>&1 || true)"
# 6e. devkit is healthy, installed headless, and leaves no way to become root (checked as the
# `extract` user, so an image that starts as root is judged the same way)
check "devkit doctor" "doctor: clean" "$(docker run --rm --user extract "$image" sh -c 'devkit doctor' 2>&1 || true)"
check "graft" "[0-9]" "$(docker run --rm "$image" graft --version 2>&1 || true)"
check "serena" "[0-9]" "$(docker run --rm "$image" serena --version 2>&1 || true)"
# the Serena MCP command every agent config launches exists; a wrong path only shows as ENOENT in preflight
check "serena mcp command" "serena-mcp-ok" "$(docker run --rm "$image" sh -c '
	set -- $(grep -ho "\"[^\"]*serena-mcp\"" "$HOME/.agents-profiles/$EXTRACTKIT_DEVKIT_PROFILE"/*/.claude.json \
		"$HOME/.agents-profiles/$EXTRACTKIT_DEVKIT_PROFILE"/*/config.toml "$HOME/.agents-profiles/$EXTRACTKIT_DEVKIT_PROFILE"/*/mcp.json 2>/dev/null | tr -d "\"")
	[ "$#" -gt 0 ] || { echo "no serena entry"; exit 1; }
	for command in "$@"; do [ -x "$command" ] || { echo "missing $command"; exit 1; }; done
	echo serena-mcp-ok' 2>&1 || true)"
check "graphify" "[a-z]" "$(docker run --rm "$image" graphify --help 2>&1 || true)"
# `claude-extract` is the devkit profile wrapper; a version proves it does not loop into itself
# (set SMOKE_AGENTS to the AGENTS build-arg of an image built with another agent list)
agents="${SMOKE_AGENTS:-$(sed -n 's/^ARG AGENTS="\(.*\)"$/\1/p' "$(dirname "$0")/Dockerfile")}"
case " $agents " in
*" claude "*) has_claude=1 ;;
*) has_claude=0 ;;
esac
if [ "$has_claude" = 0 ]; then
	echo "skip  claude-extract (built without claude)"
else
	# the version the Dockerfile pins (a build with another CLAUDE_CODE_VERSION sets SMOKE_CLAUDE_VERSION)
	pinned="${SMOKE_CLAUDE_VERSION:-$(sed -n 's/^ARG CLAUDE_CODE_VERSION=//p' "$(dirname "$0")/Dockerfile")}"
	check "claude profile wrapper" "^$pinned (Claude Code)" "$(docker run --rm "$image" claude-extract --version 2>&1 || true)"
fi
code=0
docker run --rm "$image" sh -c 'ls /home/extract/.local/share/applications' > /dev/null 2>&1 || code=$?
check "no desktop launchers" "[1-9]" "$code"
code=0
docker run --rm --user extract "$image" sh -c 'sudo -n true' > /dev/null 2>&1 || code=$?
check "no passwordless sudo" "[1-9]" "$code"
# 7. an arbitrary command and its exit code survive the wrapper
code=0
docker run --rm "$image" sh -c 'exit 7' > /dev/null 2>&1 || code=$?
check "exit code passes through" "7" "$code"
# 8. a checkout the container user cannot write fails with a clear error, not a traceback
# (the volume must be non-empty, or Docker resets its owner to the image's on the next mount)
if [ "$(docker run --rm --entrypoint id "$image" -u)" = 0 ]; then
	echo "skip  unwritable source (image starts as root)"
else
	docker volume create "$volume" > /dev/null
	docker run --rm -v "$volume:/work" --user 0 --entrypoint sh "$image" -c 'touch /work/keep && chown root:root /work && chmod 755 /work'
	check "unwritable source" "source_not_writable" "$(docker run --rm -v "$volume:/work" "$image" --source /work 2>&1 || true)"
	docker volume rm "$volume" > /dev/null
fi

exit "$failed"
