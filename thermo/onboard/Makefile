# Build and push thermo/onboard to GHCR (ghcr.io/jovlinger/thermo-onboard)
# Pi Zero 2 W: arm64 or armhf (32-bit OS). Always builds for Pi regardless of host. Requires CR_PAT for push.
.PHONY: all build push clean test ci

IMAGE := ghcr.io/jovlinger/thermo-onboard
TAG ?= latest
# Pi Zero 2 W with 32-bit OS (armhf); use linux/arm64 for 64-bit OS
PLATFORM ?= linux/arm/v7

all: build

build: .image

.image: Dockerfile requirements.txt $(wildcard *.py) $(wildcard *.sh) $(wildcard heatpumpirctl/*.py)
	docker buildx build -q --platform $(PLATFORM) -t $(IMAGE):$(TAG) --load .
	@docker image inspect $(IMAGE):$(TAG) -f '{{.Id}}' | cut -d: -f2 > .image

push: build
	@[ -n "$${CR_PAT}" ] || { echo "CR_PAT not set. export CR_PAT=ghp_..."; exit 1; }
	echo "$$CR_PAT" | docker login ghcr.io -u jovlinger --password-stdin
	docker push $(IMAGE):$(TAG)

clean:
	@[ -f .image ] && docker image rm $(IMAGE):$(TAG) 2>/dev/null || true
	@rm -f .image

test: build
	./test/run.sh

# Trigger GitHub Actions workflow (builds arm64 + armhf, pushes to GHCR).
# Uses push to thermo/onboard/ (workflow_dispatch needs admin). Requires push access, run from main/master.
ci:
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	test "$$BRANCH" = main || test "$$BRANCH" = master || { echo "Run from main or master"; exit 1; }; \
	echo "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .ci-trigger && \
	git add .ci-trigger && \
	git commit -m "ci: trigger thermo-onboard build" && \
	git push origin $$BRANCH
	@echo "Workflow triggered. See https://github.com/jovlinger/utils/actions"
