# Concepts (KV, boot, Log, authority)

## Authority

While fabric tickets are in play, those **todos are the design source of
truth** for both these docs and the code. Update the matching file under
[`docs/`](README.md) and the implementation to match the todo (Body / Notes /
WorkItems), not the reverse.

| Ticket | Owns (design) |
|--------|----------------|
| `todo:afc1dc50` (done) | Dead-simple KV layout + allocator, boot roster/load/`init`/`exit`, USB-only base loader, Net HTTP REST KV set / OTA payloads. Host path shipped; ELF map still a stub |
| `todo:15b92eaa` (done) | Log TaskActor baseline (sample/buffer/off-device drain), universal `ta_all_*`, Net NTP; **consumes** KV |
| `todo:cff5c240` | Test `get_debug`, QuLog PSRAM three-ring store, RFC-5424 TCP drain with ACK-advanced heads; HTTP path lowercasing |
| `todo:b946f61f` | **Lose monolithic Net.** One TaskActor per protocol (Http, Ntp, QuLog/Rfc5424, Mpd, ...); each owns its select/state-machine fds |

Later, if code drifts from a closed ticket, **sync these docs to the code**
(as-built fidelity). Do not treat a stale doc as design authority over an
open ticket.

Shipped baseline: host C99 suite + Waveshare TaskActor boot
(`todo:3135a46a`, merged). Directional PLAN (Rotary / MPDVolume /
ownership): [`../PLAN.md`](../PLAN.md). Host how-to:
[`../host/README.md`](../host/README.md). Board checklist:
[`../host/SMOKE.md`](../host/SMOKE.md).

The exposition split: events, TaskActors, shapes/draw, ISR/flows, plus
boot/KV/OTA contracts ratified on the tickets above. Gaps vs PLAN live in
[`host-map-and-gaps.md`](host-map-and-gaps.md).

## KV image and boot (`todo:afc1dc50` + `todo:720ac539` KvConfig)

One writable KV image, owned by the **KvConfig** TaskActor
(`ta_kvconfig_start`), prepopulated by `ta_kv_install_factory`. Items are a
packed little-endian linked list kept **sorted by key**. `next` is a byte
offset from the image base (need not be adjacent). 0 means empty or end; a
4-byte head at offset 0 holds the first pointer. New items use first-fit
holes; there is no compacting GC.

Each item: `uint32 packed` (`keylen:8 | vallen:20 | type:4`, low to high),
`uint32 next`, then `key[keylen]` and `value[vallen]`. Item size is
`8 + keylen + vallen`. Types (`TA_KV_VTYPE_*`): bool, int, str, blob,
executable, bitmap. Untyped `ta_kv_put` stores a blob. Typed helpers and
`ta_kv_put_typed` set the discriminant. Actor events: `KvGet` / `KvSet`
(form fields `key`, `type`, `value`) / `KvList` (comma-separated keys) /
`KvDelete`.

`actors_to_start` is newline-separated actor names. Each name is also a key
whose blob is that actor's image. The base bin loader stays USB-only. The
image init loader is `ta_boot_from_kv`: roster, blob, stub load (non-empty
blob; ELF map not yet), `ta_actor_init`. `ta_actor_exit` is the inverse
(stop the loop, unregister). `ta_boot_exit_all` then boot again is the reload.

**Direction (`todo:b946f61f`):** no monolithic Net socket owner. One TaskActor
per protocol -- Http (inbound listen + one client), Ntp, QuLog/Rfc5424 drain,
Mpd (Volumio client), and later siblings -- each with its own non-blocking
select/state machine. Cross-protocol work is events between actors, not a
shared Net outbound lane. As-built still registers `Net` and uses
`player_http` + an Arduino `WiFiServer` HTTP stopgap until that ticket lands.

OTA intake today is `ta_net_kv_http_put` (`PUT /kv/<key>`): upload a TaskActor
**code** blob (or a config string) with `Content-Length` into `ta_kv_put`.
After a code put, `ta_boot_exit_all` and `ta_boot_from_kv` reload the roster.
That path moves under the Http actor with `todo:b946f61f`.

Inbound HTTP today (port 80 stopgap): `POST /event/<taskactor>/<eventname>`
(`ta_net_http_event`). Path segments are ASCII-lowercased before registry
lookup; canonical registered names are lowercase (`test`, `log`, `net`, ...).
Query and/or form body are parsed as `x-www-form-urlencoded` (body keys
override query). Handler enqueues the event with a fresh `session_id`, blocks
up to `TA_TIMEOUT_SHORT_MS` (2s) for `TA_EV_NET_HTTP_REPLY` or a large blob
offer, and returns that status/body; unknown actor -> 404; incomplete / no
reply within TIMEOUT_SHORT -> HTTP 201 (`accepted`). Deferred answer retrieve
(KV) is out of scope for now. mDNS advertises hostname `spinme` (`.local`) on
`ALL_PERFORM_INIT` and on a Scheduler-timed `NetMdnsAdvertise` refresh.

Host CLI: `spinmecli --hostname spinme.local event <actor> <event> [k=v ...]`
(`host/scripts/spinmecli`) POSTs taskevent form bodies to
`/event/<actor>/<event>`. `spinmecli event <actor> --list` POSTs
`list_events` (`TA_EV_LIST_EVENTS`); every TaskActor offers a comma-separated
slug list (HTTP 200). `spinmecli event <actor> <event> --help` is local only:
it prints the Python `taskevent` class fields / kinds and does not contact the
device. `spinmecli task list` POSTs `list_tasks` then `list_events` for each
actor and prints one line per task: `name: slug, slug, ...`.

`POST /event/controller/debugall` fans out `DebugStatus` to every registered
actor; Controller list-aggregates replies into the HTTP body (200 if complete
within TIMEOUT_SHORT, else 201).

Test (`test`) also owns debug duty: `POST /event/test/get_debug` returns a
blob with `w`/`h`/`fmt=pack66`/`px_n`/`logs` header, optional pack66 pixels,
and time-merged ring log lines (`todo:cff5c240`).

## Log (`todo:15b92eaa` + `todo:cff5c240`)

`ta_all_broadcast_perform_init` posts `TA_EV_ALL_PERFORM_INIT` to every
registered actor. Async replies use `TA_EV_ALL_INFORM_RESULT`.

Log accepts lines into a three-ring store (`ta_log_rings`: ERROR 128 KiB, WARN
128 KiB, INFO-and-below 256 KiB by default; host injects smaller caps). Rings
are doubly-linked circular arenas (PSRAM on device later). Same-text tails
compress to a repeat count. Overrun emits WARN `log overrun` and drops the
oldest head. Drain merges by timestamp into short RFC-5424 frames toward KV
`logtarget` (fallback `log_receiver_url`; factory QuLog on `qnap.local`).
Heads advance only on successful send / `TA_EV_NET_LOG_DRAIN_ACK`
(`ta_log_rings_ack_through`); failed QuLog leaves the rings for retry. Cadence
empty ticks still use `log_cadence_s`.

