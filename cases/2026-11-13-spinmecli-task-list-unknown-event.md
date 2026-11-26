# CASE: spinmecli task list -> HTTP 400 unknown event

- Date: 2026-11-13
- Hosts / gear: BlackAir.local -> ESP32 spinme at 192.168.88.45
- Status: open

## 1. Symptoms

```text
$ spinmecli --host 192.168.88.45 task list
spinmecli: list_tasks HTTP 400
unknown event
```

`task --help` works. `kvconfig/kvlist` on the same board returns HTTP 200.

## 2. Evidences

- `POST /event/controller/list_tasks` -> body `unknown event`, HTTP 400 (curl).
- `POST /event/controller/debugall` -> HTTP 201 accepted (controller present).
- `POST /event/kvconfig/kvlist` -> HTTP 200 (KvConfig flash is live).
- Host `test_net_http_event` already expects `list_tasks` -> 200 when the
  tree under test includes the form map + router handler.
- Anti-evidence: not a spinmecli route/ifscope failure (HTTP reaches the board).

## 3. Analysis

`spinmecli task list` POSTs `list_tasks` then `list_events` per actor. The
flashed image returns 400 at form parse time (`build_event_from_form` has no
`list_tasks` arm), so Controller never runs `handle_list_tasks`. Typical cause:
device was flashed from a branch tip that lacked the uncommitted/main
`list_tasks` HTTP wiring (e.g. KvConfig worktree flash) while the CLI on PATH
already expects that event.

## 4. Remediation

1. Keep host CLI + HTTP unit tests green (`list_tasks` mapped, 400 body pinned).
2. Flash a build whose `ta_net_http_event.c` maps `list_tasks` and whose
   Controller handles `TA_EV_LIST_TASKS`.
3. Re-run `spinmecli --host <ip> task list` (expect actor lines with CSV events).

## Discussion

Cousin of "CLI ahead of firmware." Prefer host tests that assert both the happy
`list_tasks` path and the exact `unknown event` 400 string so a mismatched flash
is obvious from CLI stderr.
