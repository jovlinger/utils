# render_exit - userspace Tailscale egress proxy on Render's free tier.
BINLINKS := ../binlinks

.PHONY: binlinks test all-tests

VENV_PYTEST := .venv/bin/pytest

$(VENV_PYTEST): requirements.txt
	../create_pipenv.sh --sync render_exit

binlinks:
	ln -sf ../render_exit/render_exit_util.py $(BINLINKS)/render_exit_util

test: $(VENV_PYTEST)
	$(VENV_PYTEST) -q tests/test_render_exit_util.py

all-tests: test
