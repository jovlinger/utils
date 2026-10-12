# Userspace Tailscale on Render's free tier.
# No /dev/net/tun and no iptables: containerboot runs with TS_USERSPACE
# (tailscaled --tun=userspace-networking) and --netfilter-mode=off.
# Tailscale Serve publishes the egress proxies on the node's 100.x address.
# tailscaled's own SOCKS/HTTP listeners are left unset; those proxies enter
# the tailnet, and this image needs the opposite direction.
FROM tailscale/tailscale:latest

USER root
RUN apk add --no-cache python3 \
    && adduser -D -u 1000 -h /tmp/tailscale ts \
    && mkdir -p /tmp/tailscale /config \
    && chown ts:ts /tmp/tailscale /config

COPY --chown=ts:ts serve.json /config/serve.json
COPY --chown=ts:ts render_proxy.py /usr/local/bin/render-proxy.py
COPY --chown=ts:ts entrypoint.sh /usr/local/bin/render-entrypoint.sh
RUN chmod 755 /usr/local/bin/render-proxy.py /usr/local/bin/render-entrypoint.sh

ENV TS_KUBE_SECRET="" \
    TS_USERSPACE=true \
    TS_STATE_DIR=/tmp/tailscale \
    TS_SOCKET=/tmp/tailscale/tailscaled.sock \
    TS_SERVE_CONFIG=/config/serve.json \
    TS_HOSTNAME=render-exit \
    TS_ACCEPT_DNS=false \
    TS_AUTH_ONCE=false \
    TS_EXTRA_ARGS=--advertise-tags=tag:render \
    TS_TAILSCALED_EXTRA_ARGS=--netfilter-mode=off \
    HOME=/tmp/tailscale \
    SOCKS_PORT=1080 \
    HTTP_PROXY_PORT=1055

USER ts
EXPOSE 1080 1055
ENTRYPOINT ["/usr/local/bin/render-entrypoint.sh"]
