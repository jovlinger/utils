# CASE: DMZ OAuth login never starts (markupsafe SIGSEGV)

- Date: 2026-10-22
- Hosts / gear: `jovlinger.duckdns.org` (Pi 1B, eth0 `10.0.0.2`), image build `6876D688` `2026-10-11T18:42:34Z`
- Status: open

## 1. Symptoms

Browser OAuth login to the public DMZ does not complete. `http://jovlinger.duckdns.org:5000` refuses the connection. The Pi answers SSH on port 22 and has been up about 10 days, but nothing listens on Flask `PORT` 5000 or UI port 8090.

## 2. Evidences

- `jovlinger.duckdns.org` resolves to `130.44.160.34` and SSH as root lands on eth0 `10.0.0.2/24`. `jovlinger.duckdns.net` resolves to a different address (`64.190.63.222`).
- Boot log (`/tmp/boot.log`) records OAuth files installed and `start.sh` setting `PORT=5000`. `tini` is supervising `run.sh`.
- `/var/log/dmz.log` (chroot `/tmp/dmz_rootfs/var/log/dmz.log`) shows `import app` printing `about to import app` then `Segmentation fault`, then `child_returncode=139` and a relaunch. Observed iteration about 2532. Each cycle is about 6 minutes because `run.sh` waits 60s for `/ui/diagnostics` after the crash.
- Probes in that log: `cryptography ok`, `pydantic_core absent`, `pydantic ok`. Separate imports: `charset_normalizer`, `requests`, `cffi`, and `cryptography.hazmat.bindings._rust` succeed. `import flask`, `import werkzeug`, and `import markupsafe._speedups` exit 139.
- The only Flask-related native module is `markupsafe/_speedups.cpython-311-arm-linux-musleabihf.so` (markupsafe 3.0.4, flask 3.1.3, werkzeug 3.1.9). ELF `.ARM.attributes` vendor string is `7-A` and tag 6 (CPU arch) is 10 (ARM v7). `uname -m` is `armv6l`.
- Copying the markupsafe package aside, deleting that `.so`, and importing it via `PYTHONPATH` returns success and `escape()` works.

Anti-evidence:

- Wrong DuckDNS TLD or a dead port-forward is not the failure. SSH to `.org` reaches this Pi, and the Pi's own netstat has no listener on 5000, so the refused connection matches a closed local port.
- Missing OAuth client files or a bad Google redirect URI is not the failure. The boot log says the client id, secret, flask secret, and allowed-email were installed, and no process ever calls Google because import dies first.
- The already-handled `charset_normalizer` `cd.*.so` SIGSEGV is not this crash. `import charset_normalizer` succeeds, and no `charset_normalizer` `.so` is present.
- `pydantic_core absent` is not the crash. `import pydantic` succeeds on the pure-Python v1 path; the segfault is the next import, which loads Flask and markupsafe.

## 3. Analysis

OAuth is a route on Flask (`GET /login` then Google, then `/authorize`). Flask loads Werkzeug, which loads markupsafe, which imports the native `_speedups` module before any request is served. That module is an ARM v7-A shared object. On this Pi 1B (ARMv6) loading it kills the interpreter with SIGSEGV (exit 139). `run-with-stdout-logged.py` treats that as a crashed child and starts `run.sh` again, so the host spends its time crash-looping and never binds port 5000. From the outside that looks like a login failure. It is a process that never reaches the OAuth code.

MarkupSafe falls back to pure Python when `_speedups` is absent. That path imports and escapes on this host. The image build already strips `charset_normalizer` native modules for the same armv6 + musl class of crash (`thermo/dmz/strip_charset_normalizer_so.py`, `Dockerfile`). markupsafe's speedups were not stripped, and the published musllinux arm wheel is v7-A inside a generic `arm-linux-musleabihf` filename.

## 4. Remediation

Do not install MarkupSafe's musllinux arm wheel on this image. That wheel's `_speedups.so` is ARM v7-A, and the pure-Python module is a working substitute (verified on the Pi: `escape()` succeeds once the `.so` is absent). Upstream `setup.py` has no skip flag; a failing `CC` makes it retry the build with no extension, so the package never contains `_speedups.so`. `thermo/dmz/Dockerfile` now force-reinstalls the already-resolved MarkupSafe version that way (`--no-binary=markupsafe`, `CC=false`) and refuses the layer if any MarkupSafe `.so` remains.

The running Pi still extracts the old `dmz_rootfs.tar` until a new SD image is flashed. Deleting the `.so` only on the live tmpfs root lets the next `run.sh` restart bind Flask, but a reboot brings the crash back.

## Discussion

`dmesg` on the host had no current segfault lines; the ring has been turning over for about 10 days of restarts, so an empty `dmesg` does not clear the exit-139 evidence. A first look at `pydantic_core absent` is a cousin of this failure and is already logged on purpose; it is not fatal. The same pattern (generic `arm` musl wheel, ELF actually `7-A`, SIGSEGV only on `import`) is what to check if a future wheel starts crashing `import app` again after markupsafe is stripped.
