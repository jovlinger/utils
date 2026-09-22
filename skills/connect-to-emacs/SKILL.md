---
name: connect-to-emacs
description: >-
  Drive a running Emacs via emacsclient / server-eval (no MCP). Discover the
  server socket, eval Lisp, load config, install modes. Use when the user asks
  to talk to Emacs, emacsclient, server-start, configure Emacs from an agent,
  or rejects emacs-mcp.
---

# Connect to Emacs (no MCP)

Prefer plain `emacsclient` over any Emacs MCP wrapper. MCP adds nothing here;
the control plane is the Emacs server socket.

## Hard rules

1. **Probe from the shell with `emacsclient`**, never by evaluating Lisp inside
   an Emacs buffer. In-buffer `(emacs-pid)` only proves Emacs is alive; it does
   not prove a client can connect.
2. **Do not stop at "can't find socket".** On macOS the socket often lives under
   `$TMPDIR/emacs$UID/` (e.g. `/var/folders/.../T/emacs501/`) and may be named
   `server-<pid>` instead of `server`.
3. **Ask a real question once connected** (e.g. `emacs-version`), not just PID.
4. **Prefer `--eval` / `-e` with simple quoting.** Avoid nested shell quotes;
   pass one S-exp, or write a temp `.el` and `(load ...)`.

## Connect workflow

```bash
# 1) Default socket
emacsclient -e 'emacs-version'

# 2) If that fails: find sockets for this user
ls "${TMPDIR:-/tmp}/emacs$(id -u)/" 2>/dev/null
# or: lsof -c Emacs 2>/dev/null | rg 'emacs[0-9]+/server'

# 3) Non-default name (common: server-<pid>)
emacsclient --socket-name=server-PID -e 'emacs-version'
```

Success looks like a printed Lisp value (e.g. `"29.1"`), exit 0.

## Start server only if needed

If no socket exists:

- In Emacs: `M-x server-start`
- Or daemon: `emacs --daemon`

Then re-run the connect workflow. Do not tell the user to eval `(emacs-pid)`
in `*scratch*` as a connectivity check.

## Useful client calls

```bash
EMACS_SOCK=(--socket-name=server-PID)  # omit if default `server` works

emacsclient "${EMACS_SOCK[@]}" -e 'emacs-version'
emacsclient "${EMACS_SOCK[@]}" -e '(emacs-pid)'
emacsclient "${EMACS_SOCK[@]}" --eval '(load "/abs/path/to/file.el" nil t)'
emacsclient "${EMACS_SOCK[@]}" --eval '(require (quote vox-mode))'
```

Persist config under the user's Emacs init (e.g. `configfiles` sibling to
`utils`); use `emacsclient` only to load/verify the live session.

## Anti-patterns

- Recommending MCP / emacs-mcp for this job.
- Treating scratch-buffer eval as a server health check.
- Declaring "not running" after only the default socket failed.
- Dumping long multi-line Lisp through fragile nested shell quoting.
