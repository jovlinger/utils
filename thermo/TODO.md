# Thermo TODO

Living backlog for heat-pump / IR / onboard work. Numbered sections are stable IDs you can reference in commits or issues.

## 1. Time: clocks and timers

- **Capture IR sequences** (per `public/daikin-arc452a9-ir-protocol.md`: `scribble/ir_capture.py -t 200000`, logs under `scribble/captures/`) to **support or contradict** the working theory that **remote clock** and **timer on/off** targets are encoded as **minutes past midnight** (`int`; theory often summarized as **0..1440**, while `ARC452A9` currently treats sane timer values as **0..1439** inclusive). Resolve edge cases: **00:00**, **24:00** / **1440**, and **next-day wrap** on-wire.
- Run **single-variable diffs**: set clock only, set timer on only, set timer off only, and combined; map changes to F3 bytes `0x0a`–`0x0c` and byte 5 timer bits.
- When the model is confirmed or revised, update **`public/daikin-arc452a9-ir-protocol.md`** and, if needed, `State` / JSON field names (e.g. `timer_*_time` as `HH:MM` vs internal minute-of-day).

## 2. Onboard: repeated desired state must not repeat IR

**Layman's terms:** (1) The sync path may **repeat the same instruction** every few seconds — that’s fine. **Onboard** must remember what it **already sent to the AC** and **not** hit IR again when the instruction is unchanged. (2) **Only onboard** should turn that instruction into “heat 22°” / IR bytes. **DMZ and twoway** should **carry** the payload, not **interpret** it — today twoway guesses meaning from `lolidk` (e.g. `3000` → AUTO on), which is the wrong place and produces nonsense before onboard gets a say.

**Intended responsibility:** **DMZ** stores and echoes a zone command as an **opaque** blob (today mostly `lolidk`; later maybe richer JSON **still not** parsed for IR on the server). **Twoway** POSTs sensors, gets the response, and forwards the command fields to onboard **without** mapping them to `State`. **Short polling** stays until twoway↔DMZ becomes long poll. **Onboard** is the **only** place that parses command → `heatpumpirctl.State` and decides IR.

**Bug 1 — onboard:** **`app.set_daikin`** (`thermo/onboard/app.py`) always calls **`send_daikin_state`** after `State.from_json` without comparing to the **last IR-applied** logical `State`. Identical desired state → **at most one** IR per change (normalize/compare, then no-op).

**Bug 2 — DMZ + twoway (no parsing job):** **Neither layer should parse the command into heat-pump state.** Today **`twoway._lolidk_to_state`** expands `lolidk` into full `State` JSON before **`POST /daikin`** — that policy does not belong there (or on DMZ). Pass **`lolidk` (or command dict) through**; **onboard** owns validation, defaults, and `lolidk` → `State`. DMZ today mostly stores `lolidk` opaquely — keep it that way; do not add IR interpretation there.

**Evidence (example):** DMZ log shows `POST /zone/<zone>/sensors` every few seconds; each `200` echoes the same `command.lolidk` (e.g. `3000`). Twoway forwards that to onboard each time — **expected**. Pi logs show **`SET_DAIKIN`** and **`POST /daikin` 200** ~every 5s with the **same** summary → **onboard** is re-driving IR. DMZ **HTTP 500** on sensors later stopped twoway before `/daikin` → beeping stopped; unrelated root cause.

**Mechanical pathway (for the record):**

1. **Twoway** (`poll_once`): POST sensors → DMZ; on 200, currently POSTs `{"command": _lolidk_to_state(lolidk)}` to **`/daikin`** — **transport should be opaque** (`lolidk` or raw `command` dict), parsing removed from twoway.

2. **DMZ:** Persists command until changed; response includes it every time — **no IR parsing** (opaque `lolidk` is fine).

3. **Onboard `set_daikin`:** Should accept opaque command, **parse to `State` here only**, then compare to last IR’d state before **`send_daikin_state`**.

4. **Incident detail:** **`_lolidk_to_state("3000")`** (`twoway.py`) defaulting to AUTO-on illustrates **bug 2** (wrong layer + bad fallback), not something DMZ/twoway should fix by tweaking the fallback alone — move parsing to onboard and delete/retire twoway’s decoder.

**Operational note:** When debugging incidents like this, **interpret logs while fresh** and **copy Pi Zero (onboard) logs quickly** — they tend to rotate or be harder to recover than central DMZ logs.

**Pi log grab (2026-03-22):** From a dev machine on the LAN: `ssh pizero.local` with the same bundle as `thermo/onboard/DEBUG.md` / `install/README.md` (`docker logs --tail 500 thermo-onboard`, `tail` of `/var/log/thermo-onboard/onboard.log`, `journalctl -u onboard`). Saved under **`thermo/debuglogs/`** with a dated filename and retention header: `2026-03-22T230004Z_pizero-twoway-sticky-lolidk.txt` (directory is gitignored except `README.md`; see `thermo/debuglogs/README.md`).

That snapshot **confirms** onboard behavior: after each successful DMZ sensors POST, twoway hits **`/daikin`** ~every 5s and **`app: SET_DAIKIN: power=ON mode=AUTO temp=25C…`** runs each time (same decoded state from `lolidk` fallback). Repeated **`warning: …/tmp/….txt:440: trailing space ignored`** appears alongside each IR send (likely `ir-ctl` stderr). DMZ **HTTP 500** on sensors later stopped twoway before `/daikin` → IR stopped. `journalctl -u onboard` was empty at pull time (service vs container mismatch per `DEBUG.md`).


## 33. cleanup

all other scripts use setup_venv, which ends up with .venv/. Only this directory uses pipenv which ends up in env/.   Move thermo to also use .venv and possibly the common script. 
