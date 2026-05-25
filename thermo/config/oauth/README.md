# OAuth public config

Commit non-secret OAuth config here.

Expected files:

```text
google-client-id
```

Sensitive OAuth files belong in `thermo/priv/oauth/`:

```text
google-client-secret
flask-secret-key
allowed-email
```

`allowed-email` is not a credential, but it is privacy-sensitive and belongs in
`thermo/priv`.
