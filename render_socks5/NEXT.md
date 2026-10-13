# Next

Each step is one line, then one command. `up` creates or wakes the proxy.
`down` only suspends it.

## 1. Tailscale tag

Open Access controls, then the JSON editor.

    https://login.tailscale.com/admin/acls

Add this `tagOwners` entry. On an allow-all tailnet it is the only policy edit.

    "tagOwners": { "tag:render": ["autogroup:admin"] }

## 2. Tailscale credential

Open Settings, then Trust credentials.

    https://login.tailscale.com/admin/settings

Choose Credential, then OAuth. Set Auth keys to Write. Select only `tag:render`.

Copy the client secret (`tskey-client-...`), not the client id. It is shown once.

Put that secret in `ts_authkey` in section 4.

Fallback, only if OAuth is unavailable: open Keys, generate a key that is
Reusable, Ephemeral, and tagged `tag:render`. It expires within 90 days.

    https://login.tailscale.com/admin/settings/keys

## 3. Render API key

Open API keys. Create one. It starts with `rnd_` and is shown once.

    https://dashboard.render.com/u/settings#api-keys

Put that value in `render_api_key` in section 4. The key has no GitHub scope.

## 4. Let Render read the repo

Open the Render GitHub App. On account `jovlinger`, Configure or Install.

    https://github.com/apps/render/installations/new

Set Repository access to All repositories, or Only select repositories and add `utils`. Save.

Confirm GitHub is listed under Git Deployment Credentials.

    https://dashboard.render.com/u/settings

## 5. Local config

Create the config directory.

    mkdir -p ~/.config/render_socks5_util

Make the directory owner-only.

    chmod 700 ~/.config/render_socks5_util

Write a JSON object. `ts_authkey` is the `tskey-client-` secret, not the client id.

    cat > ~/.config/render_socks5_util/config.json << 'EOF'
    {
      "render_api_key": "rnd_...",
      "ts_authkey": "tskey-client-..."
    }
    EOF

Lock the file.

    chmod 600 ~/.config/render_socks5_util/config.json

## 6. Publish

From the utils checkout, push. This only puts the commit on GitHub.

    git push

## 7. Bring it up

`up` wakes the proxy. If the SOCKS port does not accept a connection, it starts a new build. No flag.

    render_socks5_util up

Run the curl it prints. It gives up after 5 seconds. If it fails, run `render_socks5_util up` again.

    curl --connect-timeout 5 --socks5-hostname 100.x.y.z:1080 https://ifconfig.me

## 8. Un-deploy

Suspend the service. The ephemeral node leaves the tailnet. The service remains.

    render_socks5_util down

Delete the service. `down` does not do this. The id is the `srv-...` value that `down` prints.

    curl -sS -X DELETE -H "Authorization: Bearer $RENDER_API_KEY" -H "Accept: application/json" "https://api.render.com/v1/services/srv-REPLACE"

Or open the dashboard, select `tailscale-exit`, then Settings, then Delete Web Service.

    https://dashboard.render.com

## 9. Remove the Render app from GitHub

Open Installed GitHub Apps. Next to Render, choose Configure, then Uninstall.

    https://github.com/settings/installations

Revoke Render under Authorized GitHub Apps so it cannot act for your user.

    https://github.com/settings/applications

## 10. Remove the Render account

Delete the service first (section 8). Then open Account Settings.

    https://dashboard.render.com/u/settings

At the bottom, choose Delete Render Account.

Delete the local secrets.

    rm -rf ~/.config/render_socks5_util
