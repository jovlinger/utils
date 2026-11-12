# spinme host library + unit tests

| Dir | Contents |
|-----|----------|
| `event/` | TaskEvent envelope/bodies, Draw/Net/Sched event APIs |
| `shape/` | Shapes, glass draw pipeline, glyphs, pack66, chrome |
| `actor/` | Registry, boot, controllers, Net/Log/KV, Test |
| `base/` | Queue, KV store, init, runtime_cfg, ISR mail, sync |
| `tests/local/` | PC unit + golden tests (`make test`) |
| `tests/ondevice/` | Post-flash/OTA: `POST /event/Test/TestRun` against the board |

See `tests/README.md`.

```bash
make test
./tests/ondevice/run_test.sh smoke   # needs SPINME_HOST / board
```
