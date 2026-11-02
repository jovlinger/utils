# Shared TaskActor sources

Symlinks into `spinme/host/*.c` so firmware and host tests compile one tree.

Recreate after clone:

```bash
cd spinme/firmware/waveshare-knob-touch-lcd-1.8/src/ta_host
for f in ta_event.c ta_init.c ta_registry.c ta_queue.c ta_logger.c \
         ta_router.c ta_controller.c ta_draw_events.c ta_net_events.c \
         ta_sched_events.c; do
  ln -sf ../../../../host/$f "$f"
done
```

Build with `-DSPINME_TA_DEVICE=1` (see `platformio.ini`) for FreeRTOS sync.
