# CASE: Spinme TaskActor 1:1 FreeRTOS stacks (watch)

- Date: 2026-11-01
- Hosts / gear: Waveshare ESP32-S3-Knob-Touch-LCD-1.8; spinme redesign
  (`spinme/PLAN.md` TaskActors; `todo:2370717b`)
- Status: open

## 1. Symptoms

(Contingency -- not observed yet.) After TaskActors land as **one FreeRTOS
task per actor**, internal SRAM is tight or exhausted: boot fails to create
tasks, stacks overflow (canaries / Guru Meditation), Wi-Fi / LWIP starve for
heap, or adding another Controller / Router tip over the budget. Glass or Net
may still look fine until the Nth actor starts.

## 2. Evidences

- PLAN decision (2026-11-01): MVP scheduling is **naive 1:1** TaskActor to
  FreeRTOS task; each blocks on an empty event queue. n:m deferred until
  stacks prove expensive (`spinme/PLAN.md` "Scheduling: naive 1:1").
- Planned cast is small but multiplies stacks: Init, Config, Scheduler, Draw,
  Net, Controller Router, MPDController, SonosController shell, plus IDF/Wi-Fi
  tasks already on the chip.
- ESP32-S3 internal SRAM is shared with intentional spinme buffers (UILayout,
  clock/scroll pixels, DMA band) and IDF -- task stacks are a competing
  claim, not free.
- Anti-evidence (why not jump to n:m now): no measurement yet that 1:1 is
  too fat; blocked tasks are cheap on CPU; Net blocking on its own task is
  correct under 1:1. Do not treat "actors feel like goroutines" as proof that
  1:1 failed.

## 3. Analysis

FreeRTOS tasks each own a stack whether runnable or blocked. Actor count times
per-task stack size is a static SRAM tax. An n:m executor (few workers
round-robin many run-to-completion actors) cuts that tax but must keep
**blocking** work (sockets, long QSPI waits) off shared workers or one stall
freezes every actor on that worker. Draw still wants a dedicated wake path
from ISR.

So failure mode of 1:1 is **memory**, not the re-active event model. The
programming model (enqueue ADTs, peek/handle/pop) can stay; only the carrier
mapping changes.

## 4. Remediation

If symptoms above appear:

1. **Measure first** -- per-task stack high-water marks, heap free at boot
   after all actors register, largest stacks (Draw/Net vs thin Router).
   Why: n:m is unnecessary if trimming stack sizes or merging idle shells
   fixes it.
2. **Trim** -- shrink stacks for pure forwarders (Router, Init); defer
   starting stub Controllers until needed. Why: cheapest fix under 1:1.
3. **Then hybrid n:m** -- keep **Draw** and **Net** as dedicated FreeRTOS
   tasks; run Router / Controllers / Config / Scheduler on one (or two)
   cooperative executor task(s). Why: preserves ISR->Draw and blocking Net;
   cuts stack count where handlers are run-to-completion.
4. Update `spinme/PLAN.md` scheduling section and `todo:2370717b` when this
   CASE moves to remediated.

## Discussion

Cousin failures: glass freeze from **blocking on the UI path**
(`cases/2026-10-27-spinme-reactivity-dies.md`, `2026-10-16-spinme-ui-lag-dns.md`)
-- that is not this CASE; do not "fix" 1:1 stacks by putting Net on the Draw
task. This CASE is only the **SRAM / task-create** cost of many 1:1 actors.
