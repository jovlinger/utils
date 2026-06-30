#!/bin/sh
# Run the DMZ image through its default entrypoint and require Flask diagnostics to answer.

set -eu

IMAGE="${DMZ_DOCKER_IMAGE:-jovlinger/thermo/dmz:armv6}"
PLATFORM="${DMZ_DOCKER_PLATFORM:-linux/arm/v6}"
TIMEOUT_SECONDS="${DMZ_STARTUP_TIMEOUT:-90}"
NAME="dmz-startup-viability-$$-$(date +%s)"

show_logs() {
	echo "--- docker logs ($NAME) ---" >&2
	docker logs "$NAME" >&2 2>/dev/null || true
	echo "--- /var/log/dmz.log ($NAME) ---" >&2
	docker cp "$NAME:/var/log/dmz.log" - 2>/dev/null | tar -xOf - >&2 || true
	echo "--- /var/log/startup_tests.log ($NAME) ---" >&2
	docker cp "$NAME:/var/log/startup_tests.log" - 2>/dev/null | tar -xOf - >&2 || true
}

cleanup() {
	docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! command -v docker >/dev/null 2>&1; then
	echo "docker-startup-viability: docker not found" >&2
	exit 127
fi
if ! docker info >/dev/null 2>&1; then
	echo "docker-startup-viability: docker daemon not reachable" >&2
	exit 127
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
	echo "docker-startup-viability: image not found: $IMAGE" >&2
	exit 127
fi

cid=$(
	docker run -d \
		--name "$NAME" \
		--platform "$PLATFORM" \
		"$IMAGE"
)
echo "docker-startup-viability: container=$cid image=$IMAGE platform=$PLATFORM"

start_ts=$(date +%s)
deadline=$((start_ts + TIMEOUT_SECONDS))
while [ "$(date +%s)" -lt "$deadline" ]; do
	state=$(docker inspect "$NAME" --format '{{.State.Status}} {{.State.ExitCode}}' 2>/dev/null || echo "missing 127")
	case "$state" in
	running\ *)
		if docker exec "$NAME" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ui/diagnostics', timeout=2).read()" >/dev/null 2>&1; then
			elapsed=$(($(date +%s) - start_ts))
			echo "docker-startup-viability: /ui/diagnostics responded after ${elapsed}s"
			exit 0
		fi
		;;
	exited\ * | dead\ * | missing\ *)
		echo "docker-startup-viability: container stopped before diagnostics were ready: $state" >&2
		show_logs
		exit 1
		;;
	esac
	sleep 2
done

echo "docker-startup-viability: timed out after ${TIMEOUT_SECONDS}s waiting for /ui/diagnostics" >&2
show_logs
exit 1
