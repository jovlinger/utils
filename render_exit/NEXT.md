# Next

Steps still required to deploy the Tailscale userspace egress proxy
(`render_exit_util` in this directory). I added `up` / `down`, the
`render/` image, and tests. `tests/test_render_exit_util.py` passed
(12). Render builds the GitHub branch you push.

## 1. Tailscale tag

In Access controls, add:

    "tagOwners": { "tag:render": ["autogroup:admin"] }

On a default allow-all tailnet, that is the only policy edit. On a locked-down
tailnet, also grant your devices TCP 1080 and 1055 to `tag:render`.

> edited in admin console -> access controls -> json editor

## 2. Tailscale credential

Do section 1 first. The credential form only lists tags that already exist
in the policy file, so `tag:render` has to be there before you can select it.

Tailscale shows the secret once. Copy it into the local config in section 4
and nowhere else: not chat, not shell history, and not the git repo. If you
close the page without copying it, revoke that credential and create another.
The secret is case-sensitive.

Use an OAuth client. An auth key is only the fallback, because it expires.

### OAuth client (preferred)

You need to be an Owner, Admin, Network admin, or IT admin of the tailnet.
The click path is documented at
https://tailscale.com/docs/features/oauth-clients

1. In the admin console, open Trust credentials.

> under settings -> trust credentials

2. Select Credential, then OAuth.
3. Set Auth keys to Write. The scope id is `auth_keys`. Read is not enough:
   the container mints a node login on every wake. Leave every other scope
   off. This client only logs the proxy in.
4. The form then requires a tag. Select `tag:render` and no other tag. The
   image always passes `--advertise-tags=tag:render`. A client that does not
   include that tag fails login, because the node is not allowed to wear it.
5. Select Generate credential.
6. On Credential created, copy the client secret. It starts with
   `tskey-client-`. That whole string is `ts_authkey` in section 4. The
   client ID is not a secret and is not what the container uses, so leave it
   out of `config.json`.
7. Select Done. The secret cannot be displayed again after this page closes.

This is the credential to keep. The secret does not expire. Nodes that log
in with it are ephemeral. Render's free instance has no persistent disk,
sleeps after 15 minutes without an HTTP request, and logs in again on every
wake (`TS_AUTH_ONCE=false` in the image). The same secret still works. When
the process stops, the ephemeral node drops off the tailnet.

### Auth key (fallback)

Use this only when you cannot create an OAuth client. The key expires in at
most 90 days, and it cannot be renewed in place. When it expires, generate
another, replace `ts_authkey`, and run `render_exit_util up` again so Render
stores the new value.

The click path is documented at
https://tailscale.com/docs/features/access-control/auth-keys
The Keys page itself is https://login.tailscale.com/admin/settings/keys

1. In the admin console, open Keys.
2. Select Generate auth key.
3. Turn Reusable on. Render logs in again after every sleep and every
   `up`. A one-time key works on the first boot only, then the next wake
   cannot log in.
4. Turn Ephemeral on, so Tailscale removes the node after it goes offline
   instead of leaving a dead machine in the admin console.
5. Turn Tags on and select `tag:render`. An untagged key logs the node in as
   your user, and the image's `--advertise-tags=tag:render` is rejected.
6. If this tailnet requires device approval, also turn Pre-approved on.
   Otherwise the node stays pending and never gets a 100.x address. Skip
   this when device approval is off.
7. Set the expiry as far out as the form allows (90 days).
8. Select Generate key and copy the key. It starts with `tskey-auth-`. That
   whole string is `ts_authkey` in section 4. It is shown once.

## 3. Render API key

Create a key at https://dashboard.render.com/u/settings#api-keys

That Render account must be allowed to read the public repo
`https://github.com/jovlinger/utils`. `render_exit_util up` creates free web
service `tailscale-exit` from that repo, with root directory
`render_exit/render`. The create call fails until Render can see the
repository.

## 4. Local config

    mkdir -p ~/.config/render_exit_util
    chmod 700 ~/.config/render_exit_util

Write `~/.config/render_exit_util/config.json` and run `chmod 600` on it.
`render_api_key` is the Render key from section 3. `ts_authkey` is the OAuth
client secret (`tskey-client-...`) or the auth key (`tskey-auth-...`) from
section 2, not the OAuth client ID:

    {
      "render_api_key": "...",
      "ts_authkey": "..."
    }

`RENDER_API_KEY` and `TS_AUTHKEY` override the file when set.

## 5. Publish the image source

Commit and push this tree in `https://github.com/jovlinger/utils`:

- `render_exit/` (image, `render_exit_util.py`, and tests)
- `binlinks/render_exit_util`

Render builds the branch named in the config (default: the current branch of
this checkout). It builds the pushed commit, so push before `up`.

## 6. Bring it up

    render_exit_util up

The command prints `curl --socks5-hostname 100.x.y.z:1080 https://ifconfig.me`.
That request should show Render's public IP.

A free instance sleeps after 15 minutes without an HTTP request to its public
service URL. Run `up` again to wake it. `render_exit_util down` suspends the
service, and the ephemeral node leaves the tailnet.

Clients use SOCKS5 port 1080 or the HTTP proxy on port 1055 at the node's
100.x address. `tailscale exit-node` needs `/dev/net/tun`, which this free
container does not have.
