# TaskActors and event APIs

Registered names and ownership:

| Registry name | Constant | Source | Owns type range |
|---------------|----------|--------|-----------------|
| `Logger` | `TA_LOGGER_NAME` | `ta_logger` | uses `TA_EV_LOG` / accept+drain (`todo:15b92eaa`) |
| `Config` / KV | (TBD `TA_CONFIG_NAME`) | dead-simple KV store + actor face | owns packed LL KV + first-fit (`todo:afc1dc50`); get/inform for peers |
| `Draw` | `TA_DRAW_NAME` | `ta_draw_events` | `0x200..` (6 oclock debug -> Log) |
| `Net` | `TA_NET_NAME` | `ta_net_events` | `0x300..` (+ HTTP REST KV set; NTP) |
| `Controller` | `TA_CONTROLLER_NAME` | `ta_router` | `TA_EV_SET_ROUTE` + forwards ControlEvents |
| `MPDController` | `TA_MPD_NAME` | `ta_controller` | consumes ControlEvents |
| `SonosController` | `TA_SONOS_NAME` | `ta_controller` | stub, same surface |
| `Scheduler` | `TA_SCHED_NAME` | `ta_sched_events` | `0x500..` |

ISR mail is **not** a registry actor; it only accepts `0x100`/`0x101` into
Draw's ingress.

Helpers that are **not** actors: artwork (`ta_artwork_*`), hit walk
(`ta_react_*`), follow chrome builder, shape/text/viewport/under-image math.

---

### 3.1 Logger

**Start:** `ta_logger_start()` registers `Logger`.

| API | Role |
|-----|------|
| `ta_logger_enqueue` | Accept events |
| `ta_logger_emit(...)` | Build `TA_EV_LOG` and post |
| `ta_logger_set_policy` / `policy` | Per-severity: DROP / NVM / EXTERNAL |
| `ta_logger_drain` | Process queued logs |

**`TA_EV_LOG` body:** `ta_log_emit_line_t` (`severity`, `tag`, `text[TA_LOG_TEXT_MAX]`).

**Callback:** none required; emit is one-way unless a future policy adds ack.

---

### 3.2 Draw

**Start:** `ta_draw_start()`. Draw is the **sole glass owner**: `ta_draw_events`
dispatches into `ta_draw_glass` (follow chrome state, text slots, status,
idle/backlight) which runs update / phase1 / phase2 and executes the push list
through a `ta_glass_backend_t` (host fake or `panel_push_pack66` on device).
Nothing else paints. Draw's queue is MP/SC (`ta_draw_bind_queue`); the Draw
task alone pumps it with `ta_draw_pump(mails, n)`, which also drains the ISR
mails first.

| Type | Value | Body | Completion |
|------|-------|------|------------|
| `TA_EV_DRAW_UPDATE` | 0x200 | `ta_draw_update_t` (`kind` CADENCE/STATUS/BASE_DIRTY; status fields 0xFF=keep; optional `reply_to`) | paints when changed; `reply_to` -> `UPDATE_DONE` |
| `TA_EV_DRAW_PAINT` | 0x201 | `ta_draw_paint_t` (optional `reply_to`) | -> `PAINT_DONE` |
| `TA_EV_DRAW_REACT_TOUCH` / `TA_EV_ISR_TOUCH` | 0x202 / 0x100 | `ta_draw_react_touch_t` / `ta_isr_touch_t` (`x`,`y`) | hit walk -> ControlEvent; dark: wake only |
| `TA_EV_DRAW_REACT_ROTATE` / `TA_EV_ISR_ROTARY` | 0x203 / 0x101 | `ta_draw_react_rotate_t` / `ta_isr_rotary_t` | `CTRL_VOLUME` REL to Controller |
| `TA_EV_DRAW_SET_SHAPE_STACK` | 0x204 | empty | installs follow chrome + first full paint |
| `TA_EV_DRAW_LOG` | 0x205 | empty | none |
| `TA_EV_DRAW_SCROLL_OX` | 0x206 | `ta_draw_scroll_ox_t` (`has_ox=0` => step; else absolute `ox`) | repaint title viewport |
| `TA_EV_DRAW_SET_TEXT` | 0x207 | `ta_draw_set_text_t` chunks (`FIRST`/`LAST`); helper `ta_draw_post_text` | rebuild L2R on LAST, paint |
| `TA_EV_DRAW_UPDATE_DONE` | 0x210 | empty | n/a |
| `TA_EV_DRAW_PAINT_DONE` | 0x211 | empty | n/a |

Text fields: `TA_DRAW_TEXT_ZONE/ARTIST/ALBUM/TITLE`. Volume and transport
lines are derived from status (desired shown while it differs from polled;
`play`/`stop`). Clock digits come from the backend wall clock or uptime.

Glass pipeline per paint (`ta_glass_paint`):

1. **`ta_draw_update`** -- dirty Shape/UILayout flags only; may run
   `TA_UPD_REPRESENT_TIME` for clock digits. Never touches `*pixels`.
2. **`ta_draw_phase1`** -- farthest->nearest rebuild dirty local pixmaps.
   Text paper is transparent, so each dirty L2R/Viewport composites the
   matching crop of the base (artwork) bitmap under its glyphs
   (`ta_phase1_opts_t.base_shape_idx`); no panel-sized shadow exists.
   Viewports blit the child at `-ox` and again at `period - ox` so the
   scroll wraps with `TA_PHASE1_SCROLL_GAP`.
3. **`ta_draw_phase2`** -- nearest->farthest coverage cull; emit exterior
   push list; clear dirty. Draw executes the list **farthest-first** so a
   farther rect never overpaints a nearer one.

Idle: each cadence UPDATE without input counts; after
`TA_GLASS_SCREEN_OFF_S` the backend backlight goes off and paints are
skipped. The next touch wakes (no hit-test) and repaints everything.

---

### 3.3 Protocol actors (replace Net) -- `todo:b946f61f`

**Normative:** there is **no** single Net socket owner. Each wire protocol is
its own TaskActor with a **private** non-blocking select/state machine and
statically bounded fds (not a free-form connection pool).

| Actor (planned) | Owns | MVP concurrency |
|-----------------|------|-----------------|
| Http | `listen_fd` + at most one accepted `in_fd`; POST `/event/...`, PUT `/kv/...` | One active inbound client; backlog holds the rest |
| Ntp | SNTP client fd / state | One outbound NTP conversation |
| QuLog / Rfc5424 | Drain TCP client + ACK | One outbound drain conversation |
| Mpd | Volumio/MPD client (poll/set/albumart) | One outbound MPD conversation (may queue ops) |
| (optional) Mdns | Advertise refresh | No long-lived client fd required |

Cross-protocol ordering is **events** (registry posts), not a shared Net
outbound lane. Http progress must not wait on Mpd/Ntp/QuLog, and vice versa.

```text
  each protocol actor turn (example Http):
    select/poll on { listen_fd?, in_fd? }
    if listen readable and in_fd empty: accept -> in_fd
    if in_fd ready: non-blocking read/write; complete request -> enqueue
         fabric event / offer HTTP reply; close or keep-alive later
    if listen readable and in_fd busy: leave peer on backlog
```

**As-built (until `todo:b946f61f` finishes):** `Net` still owns Volumio
outbound via `player_http` (lwIP select). Inbound `:80` is already the
**Http** actor (`TA_HTTP_NAME`); Arduino `WiFiServer` is hidden behind
`ta_http_wifi_up()` / `ta_http_listen.cpp` (device-only). Replace that glue
with Http's own listen/`in_fd` state machine next.

**NTP:** Net owns SNTP. After WiFi is up, `player_http` calls
`ta_net_sntp_after_wifi()` (device sets TZ + `configTime` to pool.ntp.org).
Draw still reads `time()`. Device smoke that the clock matches host ToD is
still open on `todo:15b92eaa`.

| Type | Value | Body | Completion |
|------|-------|------|------------|
| `TA_EV_NET_SET_DIALECT` | 0x300 | empty (MPD vs Sonos TBD) | none in stub |
| `TA_EV_NET_POLL` | 0x301 | `ta_net_poll_playerstate_t` (`reply_to`) | -> `POLL_DONE` |
| `TA_EV_NET_SET` | 0x302 | `ta_net_set_t` (`op` TOGGLE/VOLUME, `volume`, `reply_to`) | -> `SET_DONE` |
| `TA_EV_NET_ALBUMART` | 0x303 | `ta_net_fetch_albumart_t` (`path[TA_PATH_MAX]`, `reply_to`) | -> `ALBUMART_DONE` |
| `TA_EV_NET_POLL_DONE` | 0x310 | `ta_coord_inform_playerstate_t` (volume/playing today; 0xFF unknown) | n/a |
| `TA_EV_NET_SET_DONE` | 0x311 | empty | n/a |
| `TA_EV_NET_ALBUMART_DONE` | 0x312 | empty (bytes/fp TBD) | n/a |

MPD dialect also no-ops unsupported `TA_EV_CTRL_NEXT` / `PREV` when seen on
the Net side.

Device backend (`ta_net_player_bind.c`, the dialect edge): a `getState`
completion fills the POLL_DONE status payload via
`ta_net_backend_complete_ex`, posts artist/album/title to Draw with
`ta_draw_post_text`, and requests `NET_ALBUMART` when the artwork path
changes. MPDController adopts the polled volume into its model (unless a
SET is in flight), remembers `playing`, and posts `DRAW_UPDATE` status to
Draw on POLL_DONE, TOGGLE (optimistic flip) and VOLUME.

**Artwork calm (not an event):** after decode to RGBA, product path is
`ta_artwork_calm_rgba`: box-down to `TA_ART_LORES` (90), Q8 quadratic
B-spline 2D uprez, light desat. Default-art fingerprint
`TA_ART_DEFAULT_FP`. Album change helper
`ta_artwork_on_album_change` arms Scheduler oneshots (NET_POLL @ 50 ms,
DRAW_UPDATE @ time-remaining).

---

### 3.4 Controller Router + Controllers

**Router** registers as `"Controller"`. Only it handles `TA_EV_SET_ROUTE`;
everything else is forwarded **intact** (typed body + `session_id`) to the
current target name.

| Type | Value | Body | Notes |
|------|-------|------|-------|
| `TA_EV_SET_ROUTE` | 2 | `ta_ctrl_set_route_t.target` | sets route; not forwarded |

**ControlEvents** (posted to `"Controller"`, consumed by MPD/Sonos):

| Type | Value | Body | MPDController behaviour |
|------|-------|------|-------------------------|
| `TA_EV_CTRL_TOGGLE` | 0x400 | `ta_ctrl_toggle_t` (`reply_to` optional) | posts `NET_SET` TOGGLE; echoes originator on `SET_DONE` |
| `TA_EV_CTRL_VOLUME` | 0x401 | `ta_ctrl_volume_t` mode NONE/REL/ABS | model 0..100; change -> `NET_SET` volume; unchanged -> echo only |
| `TA_EV_CTRL_NEXT` | 0x402 | empty | counted only |
| `TA_EV_CTRL_PREV` | 0x403 | empty | counted only |
| `TA_EV_CTRL_SET_ACTIVE` | 0x404 | `ta_ctrl_set_active_t` | posts `DRAW_SET_SHAPE_STACK` + `NET_SET_DIALECT`; arms `CTRL_POLL` every `TA_MPD_POLL_MS`; optional echo |
| `TA_EV_CTRL_POLL` | 0x405 | empty | posts `NET_POLL` unless one in flight (`polls_skipped`) |

MPDController rules (`ta_controller.c`):

- **One SET in flight.** A second TOGGLE / VOLUME while a `NET_SET` awaits
  `SET_DONE` is coalesced: the volume model keeps moving, and on `SET_DONE`
  the pending toggle (first) or the latest level (second) is sent as one
  `NET_SET`. The latest originator's `reply_to` gets the echo.
- **Settled -> refresh.** When `SET_DONE` arrives with nothing queued, MPD
  posts one `NET_POLL` so chrome follows the player.
- **session_id** of the ControlEvent is carried on every Net post and echo.
- Controllers never touch `player_http`; the only Net path is the registry.
- Volume model seeds at `TA_MPD_VOL_DEFAULT` (50) until an absolute set
  or a `POLL_DONE` with known volume (`!= 0xFF`).

`SonosController` stays a counting stub (no Net traffic).

Names: `MPDController`, `SonosController`.

---

### 3.5 Scheduler

**Start:** `ta_sched_start()`. Fake time: `ta_sched_advance_ms` /
`TA_EV_SCHED_TICK` body.

| Type | Value | Body | Meaning |
|------|-------|------|---------|
| `TA_EV_SCHED_START` | 0x500 | `ta_sched_start_t` (`fire_to`, `fire_type`, `period_ms`, `flags`) | arm slot |
| `TA_EV_SCHED_STOP` | 0x501 | empty | clear all slots |
| `TA_EV_SCHED_TICK` | 0x502 | `ta_sched_tick_t.advance_ms` | advance fake clock and fire due slots |

Convenience arms (post START):

| API | Fire type | Period |
|-----|-----------|--------|
| `ta_sched_arm_clock_1hz(dst, session)` | `TA_EV_DRAW_UPDATE` (CADENCE) | 1000 ms periodic |
| `ta_sched_arm_scroll(dst, session, every_ms)` | `TA_EV_DRAW_SCROLL_OX` (`has_ox=1`, ox++) | periodic |
| `ta_sched_arm_oneshot(dst, session, delay, fire_type)` | caller-chosen | one-shot |
| `ta_sched_arm_periodic(dst, session, every_ms, fire_type)` | caller-chosen (MPD uses `TA_EV_CTRL_POLL`) | periodic |

Overdue policy: one fire, then `next = now + period` (no catch-up burst).
16 slots; oneshots preferred front of table.

---

### 3.6 ISR ingress (as-built: into Draw only)

Not a TaskActor. Types allowed on the FromISR path only. **PLAN** wants
rotary pooled time/delta into a **Rotary** EventRedirector (not Draw) --
see section 9; this table is still what ships today:

| Type | Value | Body |
|------|-------|------|
| `TA_EV_ISR_TOUCH` | 0x100 | `ta_isr_touch_t` (`x`, `y`) |
| `TA_EV_ISR_ROTARY` | 0x101 | `ta_isr_rotary_t` (`steps`, `vel_q8`) |

Any other type is **rejected** by `ta_isr_mail_push_from_isr` (no Wi-Fi,
paint, or Net from ISR). Capacity 8; full => drop + error log, never block.

---

## 4. Type range map (quick)

| Range | Owner |
|-------|-------|
| 0x000.. | Foundation (`NOP`, `LOG`, `SET_ROUTE`) |
| 0x100.. | ISR mail (`TOUCH`, `ROTARY`) |
| 0x200.. | Draw |
| 0x300.. | Net (+ DONE at 0x310..) |
| 0x400.. | ControlEvents (via Controller) |
| 0x500.. | Scheduler |

---
