# CASE: spinmecli errno 65 while ping to the knob works

- Date: 2026-11-12
- Hosts / gear: BlackAir (en0 wifi 192.168.88.59 and en9 2500Base-T 192.168.88.97); knob 192.168.88.45
- Status: remediated

## 1. Symptoms

`ping 192.168.88.45` succeeds. `curl` to port 80 succeeds. `spinmecli --host 192.168.88.45 task list` from a login zsh exits 2 with `No route to host` (errno 65).

## 2. Evidences

Same second, same route (ifscope en9):

- `/usr/bin/python3` (Apple CLT 3.9) `socket.connect` to 192.168.88.45:80 succeeds, local address 192.168.88.97.
- `/usr/bin/curl` gets HTTP 200.
- Homebrew `python3.14` `socket.connect`, and `libc.connect` on a socket that 3.14 created, return errno 65. Binding the socket to en0 or en9 first does not change that.
- Login zsh `python3` is `/opt/homebrew/opt/python@3.14/bin/python3.14`. `spinmecli` was `#!/usr/bin/env python3`, so the login shell ran 3.14.
- Socket options on a fresh socket match between 3.9 and 3.14. 3.14 is ad-hoc signed; the CLT interpreter is Apple-signed.

Anti-evidence: the knob listener was up. Interface retry cannot fix it, because every interface fails inside the 3.14 process while 3.9 succeeds on the same route.

## 3. Analysis

errno 65 here is raised inside the Homebrew Python 3.14 process. The host route and the device both work for Apple-signed `python3` and `curl` at the same moment. A login shell picks 3.14 via `env python3`.

## 4. Remediation

`spinmecli` shebang is `#!/usr/bin/python3` so it does not follow PATH onto Homebrew 3.14. Checked with `zsh -lic 'spinmecli --host 192.168.88.45 task list'` (login PATH, same as the failing prompt).

## Discussion

Retrying `IP_BOUND_IF` does not help this errno. A closed listener is still errno 61.
