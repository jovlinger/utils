#!/bin/sh
# Keep the newest local image per REPOSITORY plus any protected repo:tag refs; prune the rest.
# Usage: DOCKER_PRUNE_PROTECTED_REFS="repo:tag ..." docker-prune-old-images.sh REPOSITORY [...]

set -eu

if ! command -v docker >/dev/null 2>&1; then
	exit 0
fi

DOCKER_PRUNE_PROTECTED_REFS="${DOCKER_PRUNE_PROTECTED_REFS:-}"

id_is_kept() {
	target="$1"
	keep_list="$2"
	for keep in $keep_list; do
		[ -n "$keep" ] || continue
		[ "$target" = "$keep" ] && return 0
	done
	return 1
}

image_id_for_ref() {
	docker image inspect --format '{{.Id}}' "$1" 2>/dev/null || true
}

keep_ids_for_repo() {
	repo="$1"
	ids=""

	newest_ref="$(
		docker images --format '{{.Repository}}:{{.Tag}} {{.CreatedAt}}' 2>/dev/null \
			| awk -v r="$repo" '$1 ~ "^" r ":" && $1 !~ ":<none>$" {print}' \
			| sort -k2 -r \
			| head -1 \
			| awk '{print $1}'
	)"
	if [ -n "$newest_ref" ]; then
		pid="$(image_id_for_ref "$newest_ref")"
		[ -n "$pid" ] && ids="$ids $pid"
	fi

	for ref in $DOCKER_PRUNE_PROTECTED_REFS; do
		[ -n "$ref" ] || continue
		ref_repo="${ref%%:*}"
		[ "$ref_repo" = "$repo" ] || continue
		pid="$(image_id_for_ref "$ref")"
		[ -n "$pid" ] && ids="$ids $pid"
	done

	printf '%s' "$ids"
}

prune_repo() {
	repo="$1"
	[ -n "$repo" ] || return 0

	keep_ids="$(keep_ids_for_repo "$repo")"
	[ -n "$keep_ids" ] || return 0

	docker images --no-trunc --format '{{.Repository}} {{.ID}}' 2>/dev/null \
		| awk -v r="$repo" '$1 == r {print $2}' \
		| sort -u \
		| while read -r id; do
			[ -n "$id" ] || continue
			id_is_kept "$id" "$keep_ids" || docker rmi "$id" 2>/dev/null || true
		done
}

for repo in "$@"; do
	prune_repo "$repo"
done
