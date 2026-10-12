#!/bin/sh
# Start the egress proxy, then replace this shell with containerboot (PID 1).
set -eu
mkdir -p "${TS_STATE_DIR:-/tmp/tailscale}"
python3 /usr/local/bin/render-proxy.py &
proxy_pid=$!
sleep 0.5
if ! kill -0 "$proxy_pid" 2>/dev/null; then
    echo "render-proxy exited before tailscale started" >&2
    exit 1
fi
exec /usr/local/bin/containerboot
