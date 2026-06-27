# Deploy prerequisites for thermo/onboard/Makefile and zone deploy targets.
# Local pizero2w deploy runs docker compose; remote SSH and firmware backends do not.

include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../lib/assert-docker.mk)

_deploy_env_path := $(if $(THERMO_ENV_FILE),$(THERMO_ROOT)/$(THERMO_ENV_FILE),)
_deploy_backend := $(shell test -n "$(_deploy_env_path)" && test -f "$(_deploy_env_path)" && grep -E '^ONBOARD_DEPLOY_BACKEND=' "$(_deploy_env_path)" 2>/dev/null | cut -d= -f2- | tr -d '\r\n' || true)
_deploy_host := $(shell test -n "$(_deploy_env_path)" && test -f "$(_deploy_env_path)" && grep -E '^ONBOARD_DEPLOY_HOST=' "$(_deploy_env_path)" 2>/dev/null | cut -d= -f2- | tr -d '\r\n' || true)

deploy_zone_docker_prereq :=
ifeq ($(_deploy_backend),pizero2w)
ifeq ($(_deploy_host),)
deploy_zone_docker_prereq := assert_docker_up
endif
endif
