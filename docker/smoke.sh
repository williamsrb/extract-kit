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
