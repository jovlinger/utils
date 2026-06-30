---
name: thermo-updates
description: Keep thermo DMZ and onboard platforms up-to-date by auditing live versions with the manage CLI and planning rollout work with todos plus frequentcommits. Use when the user asks about thermo update status, OTA strategy, DMZ upgrades, or onboard firmware rollout.
disable-model-invocation: true
---

# Thermo Updates

Use this skill to keep thermo DMZ and onboard systems current in a controlled way.

## Scope

- DMZ runtime and image provenance.
- Onboard platforms (Pi Zero 2W, Pico2W, ESP32-S3).
- OTA feasibility, rollout steps, and rollback notes per platform.

## Subskill 1: Up-to-date audit with `manage`

Goal: decide WHETHER components are up-to-date before proposing upgrade work.

1. Set DMZ connectivity context.
   - Confirm `DMZ_URL`.
   - If machine auth is required, set `ZONE_PRIVATE_KEY` or `ZONE_PRIVATE_KEY_PATH`.
2. Pull DMZ diagnostics through `manage`.
   - Run `manage healthz` (maps to `/ui/diagnostics`).
   - Record `version` payload from diagnostics (`build_id`, `git_sha`, and source fields when present).
3. Pull zone state through `manage`.
   - Run `manage zones`.
   - Inspect each zone payload for firmware/app version hints in sensors or command state.
4. Compare observed live values with desired target values.
   - Desired target is normally the current branch/release intent provided by the user.
   - If target values are not explicit, mark status as unknown and request target baseline.
5. Emit per-component status:
   - `up-to-date`
   - `out-of-date`
   - `unknown` (missing telemetry or no agreed target)

Minimum command set:

```bash
manage healthz
manage zones
```

## Subskill 2: Plan OTA work with `todos` + `frequentcommits`

Do not proceed if either skill is unavailable:

- `todos`
- `frequentcommits`

Workflow:

1. Confirm both skills are present and loaded.
2. Create a dedicated planning branch ticket with `todo.py init`.
3. Place the work in a dedicated worktree using the convention:
   - `~/.todo-worktrees/<repo>_<Id[0:8]>_<branch>`
4. Seed `WorkItems` so each platform has its own strategy track:
   - DMZ
   - Pi Zero 2W
   - Pico2W
   - ESP32-S3
5. For each track, capture:
   - OTA feasibility (`full`, `partial`, `manual-only`, or `unknown`)
   - Required infra and auth
   - Rollout sequence
   - Rollback path
   - Hard blockers
6. Follow frequentcommits policy:
   - Keep only one head work item active.
   - Add tests/checks for each completed chunk when code changes are involved.
   - Commit frequently with why-focused messages.

## Output contract

When reporting status or plan progress, include:

- Worktree path
- Ticket Id and branch
- Per-component feasibility state
- Next open work item

