# render_socks5 - userspace Tailscale egress proxy on Render's free tier.
BINLINKS := ../binlinks

.PHONY: binlinks test all-tests

VENV_PYTEST := .venv/bin/pytest

$(VENV_PYTEST): requirements.txt
	../create_pipenv.sh --sync render_socks5

binlinks:
	ln -sf ../render_socks5/render_socks5_util.py $(BINLINKS)/render_socks5_util

test: $(VENV_PYTEST)
	$(VENV_PYTEST) -q tests/test_render_socks5_util.py

all-tests: test
