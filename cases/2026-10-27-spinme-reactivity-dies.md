# CASE: Spinme glass clock/scroll/reactivity freezes

- Date: 2026-10-27
- Hosts / gear: Waveshare ESP32-S3-Knob-Touch-LCD-1.8, `spinme` uimk2 on `master` (post `blit-tile-alpha`)
- Status: remediated

## 1. Symptoms

Clock digits, title scroll, and other glass reactivity sometimes stop entirely
while the last painted frame still sits on the panel (or the panel goes dark).
Touch or a knob detent often brings motion back.

## 2. Evidences

- `UIMK2_EV_UPDATE_RENDER_DRAW` is the only path that runs shape `update` then
  paint. SCROLL and CLOCKTEXT dirty only inside `uimk2_zlist_update` during
  that event (`uimk2_zlist.c`).
- `UIMK2_EV_CLOCK` only writes `z->clock_tick` / `clock_sec` via
  `uimk2_zlist_set_clock`; it does not mark dirty and does not render.
- `perm_live` gates `UIMK2_SCH_UPDATE_RENDER_DRAW` on `h->backlight`
  (`uimk2_host.c`). After `UIMK2_EV_SCREEN_OFF`, URD stops. Poll is disarmed
  the same way. The CLOCK permanent slot stays live but cannot move pixels.
- Screen-off is a one-off armed for `SCREEN_OFF_EVERY` (30 s) on wake /
  volume / press. A successful player poll does **not** re-arm it
  (`arm_screen_off` comment and `UIMK2_EV_PLAYER_POLL` handler).
- Core B (`main.cpp` `core_b_task`) is a forever loop: sample `millis()`,
  `uimk2_host_run`, drain the ring (with `apply_poll` / toggle / volume HTTP
  inline), then `ulTaskNotifyTake` for up to `min(wait, 1000)` ms. There is
  no FreeRTOS/`esp_timer` tick that drives the soft schedule.
- `apply_poll` does getState, then optionally albumart fetch + ROM TJpgDec NN
  (~0.7 s decode observed) on the same task before the next `host_run`.
- Prior cousin: `cases/2026-10-16-spinme-ui-lag-dns.md` -- blocking DNS on
  Volumio HTTP stalls the same Core B path for many seconds.
- Anti-evidence: the soft scheduler itself is not "broken" in host tests;
  URD/clock fire on cadence when `host_run` is called with advancing `now`
  and backlight is on. A frozen glass with backlight still high is not
  explained by screen-off alone -- look for a stuck `apply_poll` / HTTP.

## 3. Analysis

Glass motion is not driven by a wall-clock interrupt. It is driven by Core B
calling `uimk2_host_run` often enough while the backlight flag is true, which
pushes URD events that update SCROLL/CLOCKTEXT and paint.

Two mechanisms match "everything died":

1. **Idle screen-off (most likely when idle ~30 s).** No detent/touch for
   30 s -> SCREEN_OFF -> backlight false -> URD and poll stop. The CLOCK
   scheduler may still enqueue, but nothing paints. The panel shows the last
   frame or goes dark via `apply_backlight`. A tap or detent posts
   screen_on, re-arms URD, and motion returns.
2. **Core B blocked in player I/O (intermittent multi-second freezes).**
   Poll (and albumart decode) run synchronously on the worker. While that
   runs, `host_run` does not. Clock and scroll hold their last values until
   the HTTP/decode returns. A hung DNS/connect looks like permanent death
   until it times out.

The forever loop is interruptible sleep (`ulTaskNotifyTake`), not a blind
`delay`, but the due-time math still only runs when the task wakes and is
not stuck in HTTP. ESP32 has `esp_timer` and FreeRTOS software timers that
could notify Core B on a fixed period; the product design kept a portable
soft list so host tests need no RTOS timer.

## 4. Remediation

Why this restores motion:

- Mechanism (2): `player_http` is a non-blocking start/select/read/close state
  machine. Core B only queues getState/toggle/volume/albumart and calls
  `player_http_tick` (select with zero timeout). DNS stays boot-only.
  Albumart JPEG decode runs on a short-lived side task so URD is not held.
- Mechanism (1) is unchanged: idle screen-off still gates URD on backlight.
  Re-arming screen-off on poll is a separate product choice.

Confirm with serial: backlight on + continuing `player poll` / clock motion
during albumart fetch.

## Discussion

Tempting wrong theory: "the CLOCK scheduler is broken." The CLOCK slot is
mostly redundant with URD (URD already copies `now` into `clock_tick` before
update). Killing URD kills the visible clock even if CLOCK keeps firing.

Tempting wrong theory: "we need a hardware RTC for the schedule." Absolute
time for HH:MM:SS already comes from `millis()`; the stall is missing URD
cadence, not missing a crystal.
