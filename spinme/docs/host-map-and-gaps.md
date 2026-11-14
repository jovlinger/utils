# Host file map and as-built gaps

Library sources live under four subdirs. Tests:

| Path | Role |
|------|------|
| `tests/local/` | PC unit + goldens (`test_xy_timed_redraw`: digits 0-9 / letters a-j, **bit-identical** PNG vs `screenshots/xy_timed/`; `test_screenshots`: pixel RGB) |
| `tests/ondevice/` | Post-flash/OTA: `POST /event/test/testrun` (alias `run_test`); `get_debug` |

Firmware `src/ta_host/` keeps flat symlink names into the library trees.

| Subdir | Area | Examples |
|--------|------|----------|
| `event/` | Envelope + domain event types | `ta_event.*`, `ta_draw_events.*`, `ta_net_events.*`, `ta_sched_events.*`, `ta_net_http_event.*` |
| `shape/` | Glass / layout / draw / PNG | `ta_draw_glass.*`, `ta_shape_*`, `ta_text.*`, `ta_uilayout.*`, `ta_pack66_png.*`, `ta_stack_compose.*` |
| `actor/` | Actors + net backends | `ta_registry.*`, `ta_controller.*`, `ta_router.*`, `ta_boot.*`, `ta_net_*`, `ta_log_accept.*`, `ta_test_actor.*` |
| `base/` | Shared fabric | `ta_init.*`, `ta_queue.*`, `ta_kv.*`, `ta_runtime_cfg.*`, `ta_isr_mail.*`, `ta_sync.h` |

**Test actor:** `TA_EV_TEST_RUN` / `TA_EV_TEST_GET_DEBUG` / `TA_EV_TEST_DONE`
(`0x600` / `0x601` / `0x610`). Canonical name `test`.
PC forks `./build/test_<selector>`; device runs built-in probes (`smoke`).
HTTP form: `mode`, `selector`/`name`. Offers `TA_EV_NET_HTTP_REPLY` for the
Net gateway wait.

Run: `(cd spinme/host && make test)`.

---

## 9. As-built vs PLAN (gaps + tracking)

### Shipped (faithful in the exposition docs when marked as-built)

- Host TaskActor suite + device fabric boot (Draw glass owner, ISR mail,
  MPDController -> Net -> `player_http`, Scheduler clock/scroll/poll,
  calm Q8 artwork -> pack66 base).
- Dual-stack product path demoted (`retired/uimk2_paint/`); END smoke in
  `host/SMOKE.md` (`todo:3135a46a` done).
- Controller facade is a select-N **Router** (`ta_router`); Draw is the sole
  glass owner. Socket ownership moves to per-protocol actors
  (`todo:b946f61f`); as-built Net is transitional.
- Dead-simple KV image (`ta_kv`), factory roster, first-fit holes, and
  host boot (`ta_boot_from_kv` / `ta_actor_init` / `ta_actor_exit`) on
  `todo:afc1dc50`. ELF load is still a stub; `PUT /kv/<key>` is `ta_net_kv_http_put`.
- **Event envelope** (`ta_event_envelope_t`): `src` / `session_id` /
  `enqueue_time_ms` (queue-stamped) + typed `ta_event_t` body. Completions
  default to `src`; `reply_to` is exceptional. No legacy blob arm. MVP
  passes envelopes by value; measure copy cost later.

### PLAN ratified, not yet implemented (do not read as as-built)

| Gap | PLAN intent | Tracking |
|-----|-------------|----------|
| **Rotary EventRedirector** | ISR decode stays under actors; pooled time/delta always -> **Rotary** redirector, not Draw | Follow-on (not yet minted as its own todo); notes on `todo:3135a46a` |
| **MPDVolume** | Sole MVP Rotary target; Net player-state + Draw Update Screen at **50% alpha** target volume | Same; PLAN cast section |
| **Routing vs ownership** | EventRedirector routes events; Draw owns glass; **per-protocol** socket actors (Http/Ntp/QuLog/Mpd) replace monolithic Net | `todo:b946f61f` (supersedes PLAN "Net always owns TCP/IP") |
| **Net-owned NTP timesource** | Volumio `getState` has no wall ToD; Net owns SNTP via `ta_net_sntp_after_wifi` (player_http only calls that after WiFi) | `todo:15b92eaa`; device clock smoke still open |
| **Log QuLog rings + Test get_debug** | Three-ring PSRAM store; RFC-5424 TCP ACK drain; `/event/test/get_debug` | `todo:cff5c240` |
| **Richer POLL_DONE fields** | Net fills volume/playing; artist/album/song /
  seek still unused on the wire | Follow-on when getState mapping expands |
| **Coordinator rename** | Chat/PLAN "Coordinator" == as-built `MPDController` | Rename optional |
| **Fork + forever `ta.init()`** | Host `ta_actor_init` registers and loops on a thread until `ta_actor_exit`; device boot still sync `*_start()` | `todo:afc1dc50` host path shipped; device fork still open |
| **Degraded filter + selective queue take** | Process-before-emit only ordering; `peek_verb` for inform (etc.); out-of-order take = swap with front; defer non-setup msgs until setup informs land | Follow-on; queue is FIFO `pop` today |
| **SonosController** | Sibling route target / dialect; stub only | Deferred; non-goal of `todo:3135a46a` |
| **Delete retired paint tree** | `retired/uimk2_paint/` and optionally `uimk2/` still on disk | Needs explicit user OK to delete |

### Permanent non-goals

- Function-pointer callbacks on events: **not supported**; responses are
  events (usually to `src`; `reply_to` only for proxy).
- LVGL: out (`PLAN.md`).
- Gaussian calm path: removed; Q8 quadratic only.
