# On-device drivers (post-flash / post-OTA)

These run on the **build machine** and drive the board over HTTP after
`pio run -t upload` (or a KV OTA of an actor blob).

Gateway (as-built Net):

```text
POST /event/<actor>/<eventname>
Content-Type: application/x-www-form-urlencoded
```

Test actor path (either event name works):

```text
POST /event/Test/TestRun
POST /event/Test/run_test
```

Form fields:

| Field | Meaning |
|-------|---------|
| `mode` | `one` (default), `suite`, `timing`, or `0`/`1`/`2` |
| `selector` | short name (`smoke`) or suite (`all`, `ui`, ...) |
| `name` | alias for `selector` |
| `reply_to` | optional TaskActor for `TA_EV_TEST_DONE` |

HTTP response body (from `TA_EV_NET_HTTP_REPLY`):

```text
status=0&n_ran=1&n_fail=0&elapsed_ms=12&selector=smoke
```

On **device**, only built-in probes run today (`smoke` = ok). Full
`./build/test_*` fork suites are PC-side (`make test` / Test actor without
`SPINME_TA_DEVICE`).

## Usage

```bash
# Board address (mDNS or IP)
export SPINME_HOST=spinme.local   # or 192.168.x.y

./run_test.sh smoke
./run_test.sh --mode suite ui
./run_test.sh --mode timing smoke
./run_suite.sh smoke
```
