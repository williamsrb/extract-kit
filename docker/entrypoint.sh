#!/bin/sh
# Entrypoint of the headless image. Same contract as `docker:cli`: the image
# stays usable where a pipeline runner supplies its own command.
#   docker run IMAGE --source /work   headless run (flags go to `extractkit headless`)
#   docker run IMAGE headless ...     the same, spelled out
#   docker run IMAGE doctor ...       any other `extractkit` command
#   docker run IMAGE sh               anything else is executed as given, so a
#                                     runner that pipes a job script into a shell
#                                     (GitLab, Jenkins, Kubernetes) gets its shell
set -eu

if [ "$#" -gt 0 ]; then
	if [ "${1#-}" != "$1" ]; then
		set -- extractkit headless --json "$@"
	elif [ "$1" = headless ]; then
		shift
		set -- extractkit headless --json "$@"
	elif extractkit "$1" --help > /dev/null 2>&1; then
		set -- extractkit "$@"
	fi
fi

exec "$@"
