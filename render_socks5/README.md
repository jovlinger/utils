# render_socks5

A SOCKS5 proxy on a Render free web service, reached over Tailscale. It is not a Tailscale exit node. The container has no tunnel device, so it does not take your default route. Only a program pointed at the proxy sends traffic through Render.

- SOCKS5 on port 1080
- HTTP proxy on port 1055

Render sleeps a free instance 15 minutes after the last request to the public URL. Tailscale traffic does not count, so while a client is connected the proxy requests that URL itself.

    render_socks5_util up
    render_socks5_util down

`up` wakes the service. If port 1080 does not accept a connection, it starts a new build and exits with an error if the port is still closed.

Setup, suspend, and teardown are in [NEXT.md](NEXT.md).


- This url appears to be our persistent logs for debug. 
https://dashboard.render.com/web/srv-db6mr9mi0phs73d5s2cg/logs?t=app&r=live

