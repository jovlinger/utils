# Events and plumbing

**Source of truth:** `spinme/taskevent/` (Python). Every event is a
`TaskEvent` subclass with:

| Codec | API | Notes |
|-------|-----|-------|
| Packed LE binary body | `write_binary` / `read_binary` | Portable wire / ESP32-friendly; field order matches C members |
| C struct typedef | classmethod `to_c_struct()` | Emits `typedef struct { ... } ta_*_t;` for the type |
| C literal | instance `to_c_literal()` | Compound-literal text for one object's value |
| Text | `write_text` / `read_text` | `event=` / `type_id=` / `field=` lines |
| Form | `to_form` / `from_form` | `application/x-www-form-urlencoded`; flat events only (may raise); lists = repeated keys |

`EventEnvelope` wraps `src` + `session_id` + `enqueue_time_ms` + body.
Host body typedefs are generated into `host/event/ta_event_bodies.gen.h` by
`taskevent/gen_c_header.py` and included from `host/event/ta_event.h`
(**passed by value** in MVP). ABI padding may differ from the packed LE wire
body. Update Python first, regenerate the `.gen.h`, then this doc. Host C
sources are split under `host/{event,shape,actor,base}/`.

### Common header (every queue slot)

`reply_to` is **not** on the common header (and is the exception, not the
default -- see Completions). Receipt time is.

```c
#define TA_NAME_MAX 24
#define TA_TEXT_MAX 96

typedef uint16_t ta_event_type_t;
typedef uint32_t ta_session_id_t;
typedef uint32_t ta_time_ms_t; /* ms; host monotonic / device esp_timer */

typedef struct ta_event_envelope {
    char src[TA_NAME_MAX];
    ta_session_id_t session_id;
    ta_time_ms_t enqueue_time_ms; /* stamped by queue owner on push */
    ta_event_t event;             /* tagged body; see below */
} ta_event_envelope_t;
```

| Field | Role |
|-------|------|
| `src` | Producer actor name |
| `session_id` | Correlates a multi-step conversation |
| `enqueue_time_ms` | Filled by the **queue owner** on arrival; dwell = now - enqueue |
| `event` | Discriminated body (`type` + union) |

### Typed body (`ta_event_t`)

Naming: `ta_<recipient>_<verb>_<noun>_t` (recipient namespace / actor face),
matching `taskevent.types` class names (`LogEmitLine` <->
`ta_log_emit_line_t`). No byte-blob / `legacy` arm -- every op has a named
union member in `host/event/ta_event.h` (Net poll/set/albumart, Draw
update/paint/scroll/text/informs, ControlEvents, Scheduler start/tick, ISR
touch/rotary, Logger line, ...).

POLL_DONE carries `coord_inform_playerstate` (volume/playing filled today;
artist/album/song when Net has them).

### Events only (no fn ptrs)

All TaskActor communication is **events** -- requests, responses, and
informs. UI (touch / rotate) and Scheduler produce events; actors post
events to look up Config/KV, drive Net, and update Draw. There are no
function-pointer callbacks on the wire.

**Who gets a response?** The **event contract** decides:

- **Default:** if the contract says there is a response, it goes to
  envelope **`src`** (the sender). Response `type` / body are implied by
  the request (e.g. POLL -> `TA_EV_NET_POLL_DONE` with
  `coord_inform_playerstate`).
- **No response:** many contracts fire-and-forget (or only produce
  side-effect events to other actors). Example: a rotary turn may post
  one event to Net (update player volume) and another to Draw (target
  volume chrome) and send **nothing** back to the originator.
- **Response and side-effects:** allowed -- one DONE/inform to `src`
  plus other posts (Draw update, Log, ...).
- **`reply_to` is the exception:** only when the completion must land
  somewhere other than `src` (true proxy). Prefer omitting it; as-built
  code still carries `reply_to` on some request bodies until migrated.

Scheduler arms use `ta_sched_start_t` (`fire_to` + `fire_type`) -- that is
the timer's **fire destination**, not a completion `reply_to`.

### Interaction sketch (names)

As-built registry name for the face that owns player model + Net dialect
policy is **`MPDController`** (behind the **Controller** EventRedirector).
PLAN/chat may say **Coordinator** for that role -- same slot until renamed.

```text
Scheduler --CTRL_POLL--> Controller --> MPDController
MPDController --net_poll_playerstate (src=MPD)--> Net
Net --POLL_DONE / coord_inform_playerstate (to src)--> MPDController
MPDController --draw_inform_songinfo / volume / currpos--> Draw
```

Rotary path (PLAN): ISR -> Rotary redirector -> MPDVolume posts **side
effects** (Net SET + Draw inform target volume) and typically **no**
response to the ISR/Draw originator.

### Foundation type ids

| Type | Value | Meaning |
|------|-------|---------|
| `TA_EV_NOP` | 0 | No-op (empty body) |
| `TA_EV_LOG` | 1 | `ta_log_emit_line_t` |
| `TA_EV_SET_ROUTE` | 2 | `ta_ctrl_set_route_t` (target name) |

---

## 2. Plumbing (not TaskActors, but every post goes through them)

### Registry (`ta_registry`)

| API | Role |
|-----|------|
| `ta_registry_register(name, enqueue_fn)` | Bind actor name to enqueue |
| `ta_registry_lookup(name)` | Get fn or NULL |
| `ta_registry_post(name, ev)` | Lookup + call enqueue (mutex not held across handler) |

### Queue (`ta_queue`)

MP/SC (host pthread stand-in; device FreeRTOS). Circular buffer of
`ta_event_envelope_t`.

| API (as-built) | Role |
|----------------|------|
| `ta_queue_push` | Producer; stamps `enqueue_time_ms`; drop if full (`drops++`) |
| `ta_queue_peek_wait` / `try_peek` / `pop` | Consumer FIFO head |

#### Ordering guarantee (normative -- one rule only)

An event is **fully processed before any outgoing message it generates**
is visible to other actors (handler runs to completion, then posts).

There is **no** FIFO requirement among *unprocessed* messages on one
actor's queue: any still-queued envelope may be taken next. Causality
between actors comes only from the "process before emit" rule above.

#### Selective take (normative; degraded / filter)

When the consumer processes a slot that is **not** the front, it
**swaps** that slot with the front, then advances head (same as a
normal pop of the chosen message). Remaining order of other pending
slots is otherwise unchanged.

**Scan API:** `ta_queue_try_peek_verb` / `ta_queue_try_take_verb` walk
pending slots oldest-first with a match callback (e.g. only informs while
degraded). Take swaps the match with the front, then pops. No match =>
caller idles until a push. FIFO `peek`/`pop` head remain for normal drain.

Separate `ta_shape_lock_*` for shape/pixel protocol (not the queue mutex).

### Init + TaskActor lifetime (normative; `todo:afc1dc50`)

**Base bin loader** (USB-wired physical update only; not OTA'd): brings up
enough of the image to run the **small init loader**.

**Image init loader** boot procedure:

1. Locate the **KV** region (prepopulated by the static build; writable).
2. Get the **start-roster** key -> list of TaskActor **names**.
3. For each name: get that name's KV blob -> **load** (ESP flash map/cache
   where it already helps) -> call the actor's **`init()`** entry point.

**Exactly two loadable entry points (v1):**

| Entry | Role |
|-------|------|
| `init()` | Local setup; **register** name in the registry; start forever event loop (never returns until exit). |
| `exit()` | Inverse: leave the loop; **unregister** / remove from registry; release what init acquired. |

Reload / OTA after KV mutation: **`exit()` all** running actors, then run the
boot procedure again on the (possibly new) roster -- or reboot into the same
init loader.

As-built host still uses a sync entry list (`ta_init_add_entry` /
`ta_init_run_entries` + `*_start()` register then return). Treat
roster/load/`init`/`exit` as ticket-normative until implemented.

### Degraded / filter mode (normative)

Actors may run **degraded** while waiting on outside setup (e.g. config
get replies, Net dialect ready). In degraded mode the actor **filters**
incoming queue messages:

- Accept and handle the informs / replies needed to finish setup.
- Defer (leave queued) everything else via selective take: only the
  accepted message is swapped out; others stay until the actor leaves
  degraded mode and drains normally.

Once required outside info is in hand, the actor leaves degraded mode
and processes the full queue (any order among pending, still subject to
"process before emit").

### Config / KV (ours; `todo:afc1dc50` + `todo:720ac539`)

**One store** -- not a parallel NVS + SPIFFS + custom trio for the same job.
Owned by the **KvConfig** TaskActor (`get` / `set` / `list` / `delete`).

**Layout (sorted typed):** singly linked list of packed entries, keys ascending,
O(n) get:

```
entry { packed; next; key[keylen]; value[vallen] }
```

`packed` = `keylen:8 | vallen:20 | type:4` (low to high). Item size is
`8 + keylen + vallen`. Types: bool / int / str / blob / executable / bitmap;
see `host/base/ta_kv.h`. Store and form `KvSet` clamp value length to
`TA_KV_VAL_MAX` (1024) today; the 20-bit field is the on-disk width.

**Prepopulated but writable:** the static build emits a factory KV image
(default roster + per-name actor blobs). Runtime mutates the same region.

**Allocator:** KV owns placement for (possibly large) blobs; replace/delete
leaves **holes**; v1 is **first-fit**. Compacting GC deferred until first-fit
hurts.

**Well-known keys (boot + runtime):**

| Key | Default (factory image) | Consumer at startup |
|-----|-------------------------|---------------------|
| `actors_to_start` | `Draw\nNet\n` | `ta_boot_from_kv` |
| Per-name actor blob | e.g. `Draw`=`draw-v1` | boot stub load |
| `current_controller` | `MPD` | Router / Config |
| `logtarget` | `tcp://qnap.local:514` | Log QuLog drain (preferred) |
| `log_receiver_url` | `tcp://qnap.local:514` | Log init fallback |
| `mpd_host` | `miniDSP-SHD.local` | player_http DNS |
| `ntp_host` | `pool.ntp.org` | Net SNTP (`configTime`) |
| `timezone` | `EST5EDT,M3.2.0/2,M11.1.0/2` | Net SNTP (`TZ` / `tzset`) |
| `screen_blank_s` | `30` | Draw idle backlight-off |
| `title_scroll_step` | `2` | Draw title ox step (px) |
| `title_scroll_ms` | `40` | Scheduler scroll arm period |

Seeded by `ta_kv_install_factory` -> `ta_runtime_cfg_put_factory`.
`ta_runtime_cfg_load` copies into a process cache (missing key => default).

`timezone` is a POSIX TZ string (not a bare UTC offset) so DST rules stay with
the zone. A future `timezone_offset_min` key is optional if a UI only edits
minutes.

**Net HTTP KV set:** Net owns the on-device REST intake for both **TaskActor
code** and runtime config strings (`ta_net_kv_http_put`):

```text
PUT /kv/<key>
Content-Length: <n>

<n bytes of body>
```

Base **bin** loader (whole firmware) stays USB-only; it is not replaced by
this path.

### Piecemeal **code** upgrade (TaskActor images via `PUT /kv/<key>`)

Each roster name is also a KV key whose blob is that actor's **loadable
code image** (ELF or platform image once mapping works; stub bytes on host
today). Upgrading one TaskActor means replacing that one blob over HTTP,
then reloading actors -- not reflashing the whole device.

```text
# Example: replace Draw's code only
PUT /kv/Draw
Content-Length: <sizeof draw image>
<draw image bytes>

# Then on device (or via a follow-up control):
ta_boot_exit_all()
ta_boot_from_kv()    # re-reads actors_to_start; loads each name's blob; init
```

**Rules:**

1. **One actor at a time.** `PUT /kv/Draw` does not touch `Net`,
   `Scheduler`, or config keys. After exit-all + boot, only the new Draw
   image is what changed in the running set (other blobs reload unchanged).
2. **Key == registry / roster name.** The body is opaque code for that
   actor. Config keys (`mpd_host`, `timezone`, ...) use the same REST face
   but carry short strings, not executables.
3. **Roster edits** (`PUT /kv/actors_to_start`) add/remove which names boot;
   each name still needs its own code key if it is to load.
4. **Reload barrier.** A successful code PUT stores the blob; it does not
   hot-patch a running task. `exit` all, then `boot_from_kv`, is the
   activation step (can be automatic after PUT later).
5. **Factory reset** rewrites roster + default config (+ tiny stub actor
   blobs). It is the recovery path if a bad image bricks one actor.

**Config vs code on the same API:** same `PUT /kv/<key>`, different key
classes. Code keys are actor names on the roster; config keys are the
well-known settings table above. Config can apply on
`ta_runtime_cfg_load` / `perform_init` without exit-all; **code** always
needs the boot barrier.

**As-built gaps (section 9):** blob size cap is still small for real ELF;
loader map/relocate is stubbed on device. The REST + KV + exit/boot loop is
the intended piecemeal code-upgrade shape.

---
