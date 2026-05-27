# Thermo private material

`thermo/priv/*` is ignored by git and should contain only local private
material.

Expected private layout:

```text
thermo/priv/
  zone/
    priv.pem
  oauth/
    google-client-secret
    flask-secret-key
    allowed-email
  pico2w/
    office.env
  ssh-host/
    ssh_host_ed25519_key
    ssh_host_rsa_key
```

Non-private counterparts belong under `thermo/config/`:

```text
thermo/config/
  zone/pub.pem
  oauth/google-client-id
  ssh-host/*.pub
```

`make -C thermo/dmz zone-keys` writes `priv/zone/priv.pem` and
`config/zone/pub.pem`.

Pico2W private env files are sourced by the Pico deploy script after the
committed room config. For example, `thermo/priv/pico2w/office.env` should hold
`PICO2W_WIFI_PASSWORD` and can point `ZONE_PRIVATE_KEY_PATH` at
`$THERMO_ROOT/priv/zone/priv.pem`.
