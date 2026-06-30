# vox2stp Bookmark

Status as of 2026-06-14 13:20 local time:

We are investigating why the rendered STEP file imports but fails to slice in
Bambu/Orca-style tooling. Current suspicion is stray geometry excursions well
above or below the expected base and trace Z layers.

Expected vertical envelope:

- Base solids should stay inside `base_z0_mm..base_z1_mm`.
- Copper traces and labels should stay near `trace_z0_mm..trace_z1_mm`, with
  labels extending only by `label_height_mm`.
- No generated vertex or solid should appear outside the computed board X/Y
  footprint or outside the intended Z envelope.

Current follow-up work is isolated in worktree:

`/Users/johan/github.com/jovlinger/utils-vox2stp-font-envelope`

Branch:

`vox2stp-font-envelope`

That worktree contains uncommitted changes that add:

- curved label geometry via `vox2stl` letter mesh reuse
- `TriangleMeshSolid` support for label solids
- generated mesh bounds and envelope reporting
- writer-side bounds validation for out-of-envelope vertices
- tests covering label mesh detail and bounds rejection

Main checkout status before writing this bookmark was clean at commit
`231987d Add vox2stp STEP generation pipeline`.

Next resume step:

Run the full `vox2stp` command on the failing `.vox`, inspect the printed
envelope, then validate the generated STEP through the local OCCT/Gmsh path.
If it still fails to slice, locate which emitted solid or vertex violates the
expected Z envelope before changing the writer again.
