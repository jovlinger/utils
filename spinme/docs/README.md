# spinme exposition (split)

The old monolithic [`../EXPOSITION.md`](../EXPOSITION.md) is a **stub**. The
design catalog lives here as separate docs.

## When someone says "update exposition"

1. Open tickets remain SoT (`Body` / Notes / WorkItems). Edit code and the
   **matching file below**, not a resurrected single EXPOSITION blob.
2. Pick the section that owns the topic (table). If two sections touch it,
   update both and keep cross-links honest.
3. Keep [`../AGENTS.md`](../AGENTS.md) and [`../README.md`](../README.md)
   pointing at this index if paths change.
4. After closed-ticket drift: sync **these** docs to as-built code (same
   rule as before).

| Doc | Owns |
|-----|------|
| [`concepts.md`](concepts.md) | Authority table, KV/boot/OTA face, Log, high-level pointers |
| [`events-and-plumbing.md`](events-and-plumbing.md) | Envelope, codecs, queues, selective take, init lifetime |
| [`taskactors.md`](taskactors.md) | Registry cast, per-actor APIs, Draw/Net/Controller surfaces |
| [`shapes-and-drawing.md`](shapes-and-drawing.md) | Shape tags, pack66 alpha, UILayout, glass path **without flicker** |
| [`isr-and-flows.md`](isr-and-flows.md) | ISR mail, hit walk, product sequence diagrams |
| [`host-map-and-gaps.md`](host-map-and-gaps.md) | `host/` file map, as-built vs PLAN gaps |

Directional product PLAN (not the catalog): [`../PLAN.md`](../PLAN.md).

Other files under `docs/` (for example Volumio probe notes) are unrelated
to this exposition split; do not fold them into the catalog table above.

## ASCII

Human-readable docs in this tree stay 7-bit ASCII (no em/en dashes, no
emoji).
