# Boot debug (you're typing on the Pi — one command, short reply)

**Step 1.** Run:

```sh
dmesg | grep -E 'Mounting boot|Loading user'
```

Reply with the exact line(s) you see, or "nothing".

**Step 2.** Run:

```sh
ls /etc/local.d/
```

Reply with the list (e.g. "README only" or "README dmz-init.start").

That's enough for the next fix. More steps only if we need them.

---

**When network didn't come up** — on the Pi (console, no network needed), run this one command and paste the full output:

```sh
cat /tmp/dmz-boot.log
```

Paste everything it prints. That file is written by dmz-init at boot and contains the banner, SD path, and network step messages so we can fix the script.
