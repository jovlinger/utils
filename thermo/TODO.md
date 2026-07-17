# Thermo TODO

(for visitors: This file predates the todo skill; this would normally live in the .todo repository)

Living backlog for work **not started** or only lightly scoped. In-progress state:
[`BOOKMARK.md`](BOOKMARK.md). Stable reference: per-directory `README.md`.

Numbered sections are stable IDs you can reference in commits or issues.

## 1. Time: clocks and timers

- **Capture IR sequences** (per `public/daikin-arc452a9-ir-protocol.md`: `scribble/ir_capture.py -t 200000`, logs under `scribble/captures/`) to **support or contradict** the working theory that **remote clock** and **timer on/off** targets are encoded as **minutes past midnight** (`int`; theory often summarized as **0..1440**, while `ARC452A9` currently treats sane timer values as **0..1439** inclusive). Resolve edge cases: **00:00**, **24:00** / **1440**, and **next-day wrap** on-wire.
- Run **single-variable diffs**: set clock only, set timer on only, set timer off only, and combined; map changes to F3 bytes `0x0a`--`0x0c` and byte 5 timer bits.
- When the model is confirmed or revised, update **`public/daikin-arc452a9-ir-protocol.md`** and, if needed, `State` / JSON field names (e.g. `timer_*_time` as `HH:MM` vs internal minute-of-day).
