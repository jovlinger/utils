# Shared TaskActor sources

Flat symlinks under this directory point at
`spinme/host/{event,shape,actor,base}/*` so PlatformIO and host tests share one
tree. Link **names** stay flat (`ta_event.c`, ...); only the target path has the
subdir.

Recreate after clone:

```bash
cd spinme/firmware/waveshare-knob-touch-lcd-1.8/src/ta_host
HOST=../../../../host
link() { ln -sfn "$HOST/$1/$2" "$2"; }

rm -f ta_*.c ta_*.h

# event/
for f in ta_event.c ta_event.h ta_event_bodies.gen.h \
         ta_draw_events.c ta_draw_events.h \
         ta_net_events.c ta_net_events.h \
         ta_sched_events.c ta_sched_events.h \
         ta_net_http_event.c ta_net_http_event.h; do
  link event "$f"
done

# shape/
for f in ta_draw_glass.c ta_draw_glass.h ta_draw_update.c ta_draw_update.h \
         ta_draw_phase1.c ta_draw_phase1.h ta_draw_phase2.c ta_draw_phase2.h \
         ta_follow_chrome.c ta_follow_chrome.h ta_hit_dispatch.c ta_hit_dispatch.h \
         ta_text.c ta_text.h ta_shape_l2r.c ta_shape_l2r.h \
         ta_uilayout.c ta_uilayout.h ta_stack_compose.c ta_stack_compose.h \
         ta_chrome_icons.c ta_chrome_icons.h ta_shape_swap.c ta_shape_swap.h \
         ta_shape_draw.c ta_shape_draw.h ta_wire.c ta_wire.h \
         ta_artwork.c ta_artwork.h ta_kv_editor.c ta_kv_editor.h \
         ta_viewport.c ta_viewport.h ta_under_image.c ta_under_image.h \
         ta_pack66_png.c ta_pack66_png.h ta_glyph_bin.c ta_glyph_bin.h; do
  link shape "$f"
done

# actor/
for f in ta_registry.c ta_registry.h ta_controller.c ta_controller.h \
         ta_router.c ta_router.h ta_logger.c ta_logger.h \
         ta_net_sntp.c ta_net_sntp.h ta_input_isr.c ta_input_isr.h \
         ta_actor.c ta_actor.h ta_boot.c ta_boot.h \
         ta_kv_actor.c ta_kv_actor.h ta_log_accept.c ta_log_accept.h \
         ta_log_rings.c ta_log_rings.h \
         ta_all.c ta_all.h ta_net_mpd.c ta_net_mpd.h \
         ta_net_kv_http.c ta_net_kv_http.h ta_debug.c ta_debug.h \
         ta_test_actor.c ta_test_actor.h ta_http_actor.c ta_http_actor.h \
         ta_net_backend.h; do
  link actor "$f"
done

# base/
for f in ta_init.c ta_init.h ta_queue.c ta_queue.h ta_kv.c ta_kv.h \
         ta_runtime_cfg.c ta_runtime_cfg.h ta_isr_mail.c ta_isr_mail.h \
         ta_sync.h; do
  link base "$f"
done
```

Build with `-DSPINME_TA_DEVICE=1` (see `platformio.ini`) for FreeRTOS sync.
