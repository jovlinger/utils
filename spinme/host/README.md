# spinme host tests (off-device)

Fast C99 tests for the TaskActor / Draw redesign. No hardware, no `pio`.

```bash
cd spinme/host
make test
```

Add a new unit as `test_<name>.c`, list the binary under `TESTS` in the
Makefile, and keep the production sources next to the tests (or under
`../src/` as the tree grows). Do not treat `../uimk2/test_*` as the contract
for the new design -- those remain the old zlist path until retired.
