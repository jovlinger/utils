# Shared Docker cleanup targets for utils subprojects.
#
# Set before include:
#   UTILS_ROOT              - path to utils repo root (required)
#   DOCKER_CLEAN_REPOS      - space-separated image repository names (no tags)
#
# Optional:
#   DOCKER_CLEAN_CONTAINER_NAMES          - exact container names to remove
#   DOCKER_CLEAN_CONTAINER_NAME_PREFIXES  - container name prefixes (dmz-startup-viability-)
#   DOCKER_CLEAN_MARKERS                  - stamp files (.image, .image.app, ...)
#   DOCKER_CLEAN_STAGING_DIRS             - dirs recreated on build (.docker-import)
#   DOCKER_CLEAN_OUTPUT_DIRS              - deeper outputs removed by docker-all-clean (dist/)
#   DOCKER_CLEAN_TEST_FILES               - log/transcript files from dockertest etc.
#   DOCKER_CLEAN_COMPOSE_DIRS             - dirs with docker-compose.yml (compose down)
#   DOCKER_CLEAN_PROTECTED_IMAGE_REFS     - full repo:tag refs kept by docker-old-clean
#
# Targets:
#   docker-testing-clean  - stop/remove test containers and delete test/staging artifacts
#   docker-old-clean      - remove older local images; keep newest per DOCKER_CLEAN_REPOS entry
#   docker-clean          - docker-testing-clean + docker-old-clean
#   docker-all-clean      - docker-clean + all tagged images, markers, and output dirs

DOCKER_CLEAN_REPOS ?=
DOCKER_CLEAN_CONTAINER_NAMES ?=
DOCKER_CLEAN_CONTAINER_NAME_PREFIXES ?=
DOCKER_CLEAN_MARKERS ?=
DOCKER_CLEAN_STAGING_DIRS ?=
DOCKER_CLEAN_OUTPUT_DIRS ?=
DOCKER_CLEAN_TEST_FILES ?=
DOCKER_CLEAN_COMPOSE_DIRS ?=
DOCKER_CLEAN_PROTECTED_IMAGE_REFS ?=

DOCKER_PRUNE_OLD_IMAGES := $(abspath $(UTILS_ROOT)/lib/docker-prune-old-images.sh)

.PHONY: docker-testing-clean docker-old-clean docker-clean docker-all-clean

docker-testing-clean:
	@for d in $(DOCKER_CLEAN_COMPOSE_DIRS); do \
		[ -n "$$d" ] || continue; \
		if [ -f "$$d/docker-compose.yml" ] || [ -f "$$d/compose.yml" ]; then \
			(cd "$$d" && docker compose down --remove-orphans 2>/dev/null) || true; \
		fi; \
	done
	@for n in $(DOCKER_CLEAN_CONTAINER_NAMES); do \
		[ -n "$$n" ] || continue; \
		docker rm -f "$$n" 2>/dev/null || true; \
	done
	@for p in $(DOCKER_CLEAN_CONTAINER_NAME_PREFIXES); do \
		[ -n "$$p" ] || continue; \
		ids="$$(docker ps -aq --filter "name=$$p" 2>/dev/null || true)"; \
		[ -z "$$ids" ] || docker rm -f $$ids 2>/dev/null || true; \
	done
	@for d in $(DOCKER_CLEAN_STAGING_DIRS); do \
		[ -n "$$d" ] || continue; \
		rm -rf "$$d"; \
	done
	@for f in $(DOCKER_CLEAN_TEST_FILES); do \
		[ -n "$$f" ] || continue; \
		rm -f "$$f"; \
	done

docker-old-clean:
	@for repo in $(DOCKER_CLEAN_REPOS); do \
		[ -n "$$repo" ] || continue; \
		DOCKER_PRUNE_PROTECTED_REFS="$(DOCKER_CLEAN_PROTECTED_IMAGE_REFS)" \
			"$(DOCKER_PRUNE_OLD_IMAGES)" "$$repo"; \
	done

docker-clean: docker-testing-clean docker-old-clean

docker-all-clean: docker-clean
	@for repo in $(DOCKER_CLEAN_REPOS); do \
		[ -n "$$repo" ] || continue; \
		tags="$$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
			| awk -v r="$$repo" '$$1 ~ "^" r ":" {print $$1}')"; \
		for tag in $$tags; do \
			keep=0; \
			for pref in $(DOCKER_CLEAN_PROTECTED_IMAGE_REFS); do \
				[ "$$tag" = "$$pref" ] && keep=1; \
			done; \
			[ "$$keep" -eq 1 ] || docker rmi "$$tag" 2>/dev/null || true; \
		done; \
	done
	@for m in $(DOCKER_CLEAN_MARKERS); do \
		[ -n "$$m" ] || continue; \
		rm -f "$$m"; \
	done
	@for d in $(DOCKER_CLEAN_OUTPUT_DIRS); do \
		[ -n "$$d" ] || continue; \
		rm -rf "$$d"; \
	done
