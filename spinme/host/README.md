# spinme host tests (off-device)

Fast C99 tests for the TaskActor / Draw redesign. No hardware, no `pio`.

Exhaustive actor/event/shape/ISR catalog and flow diagrams:
[`../EXPOSITION.md`](../EXPOSITION.md).

```bash
cd spinme/host
make test
```

Add a new unit as `test_<name>.c`, list the binary under `TESTS` in the
Makefile, and keep the production sources next to the tests (or under
`../src/` as the tree grows). Do not treat `../uimk2/test_*` as the contract
for the new design -- those remain the old zlist path until retired.

## Glass contract

`test_draw_glass_contract` covers update/phase1/phase2/under-image rules and
is part of the normal green `make test` suite.

## ISR ingress

`ta_isr_mail_*` is the host stand-in for FreeRTOS `xQueueSendFromISR` into
**Draw** only. The FromISR path takes no task mutex, never blocks, and rejects
non-touch/rotary event types (no Wi-Fi / paint / Net in ISR). On device, map
`ta_isr_mail_push_from_isr` to a Draw queue FromISR send; the task drains and
then enqueues ControlEvents to the Controller Router as a normal producer.
