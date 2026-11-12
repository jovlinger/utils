# CASE: ReadyNAS Frontview SMART vs smartctl

- Date: 2026-10-29
- Hosts / gear: nas.local (ReadyNAS padre, Linux 2.6.17.14); disks `/dev/hdc`, `/dev/hde`
- Status: open

## 1. Symptoms

- Frontview shows one disk with SMART attributes and the other with no SMART at all.
- Operator wants to reuse the enclosure with fresh disks, but only if host-side health reporting can be trusted.
- Chassis LM75 temp sensor also missing (`The LM75 can not be found`); fan reads via `/proc/sys/dev/hwmon/fan_0`.

## 2. Evidences

- Real block devices in `/proc/partitions`: `/dev/hdc` and `/dev/hde` (~1 TB each).
- `sudo smartctl -i/-H/-A` works on **both** disks (smartctl 5.42 local build).
- `/dev/hde` = WDC WD10EVDS-63U8B0 `WD-WCAV5C386158` -- matches Frontview dump (incl. Load_Cycle_Count raw 1048347, POH 40039). Overall: PASSED; realloc/pending/uncorrectable = 0; attribute 193 VALUE=001.
- `/dev/hdc` = WDC WD1003FBYX-01Y7B1 `WD-WCAW36620168` (RE4) -- Frontview "no SMART", but CLI: SMART Enabled, PASSED; Load_Cycle_Count 0; POH 8067; realloc/pending/uncorrectable = 0.
- Anti-evidence: "both drives deeply pre-fail / enclosure cannot read SMART" is false. Media-fail counters are clean on both; the silent disk is readable via smartctl. The EVDS wear is load-cycle exhaustion (WD AV-GP park behavior), not reallocated sectors.

## 3. Analysis

Frontview's per-disk SMART page is an incomplete/buggy view over the same ATA SMART data `smartctl` reads on IDE nodes `hdc`/`hde`. Trust the CLI path for enclosure reuse validation; do not trust Frontview's "no SMART" as "disk or bus cannot do SMART."

The EVDS is worn out on head-load cycles (VALUE pegged at 001) despite PASSED and zero reallocs -- replace it for reliability, not because SMART is unread. The RE4 looks healthy by attribute table.

## 4. Remediation

- Validate health with `sudo smartctl -i -H -A /dev/hdc` and same for `/dev/hde` (SSH as a sudoer; ReadyNAS sudo prompts `Password:`).
- Why: Frontview can omit SMART for a disk that still answers ATA SMART; CLI is the ground truth for "can this enclosure report drive health after a disk swap?"
- After installing fresh disks, re-run the same `smartctl` commands on the new device nodes before trusting the array; optionally ignore Frontview SMART UI entirely.
- Replace the EVDS regardless of PASSED -- Load_Cycle_Count past ~300k-600k is classic WD Green/AV park wear; VALUE=001 means the attribute is exhausted.

## Discussion

- sudo expect match must accept capital `Password:` (not only lowercase SSH `password:`).
- Chassis core temp via LM75 is a separate failure from disk SMART.
- Cursor transcript search (all `~/.cursor/projects/*/agent-transcripts`, serials `WCAV5C386158` / `WCAW36620168`, ReadyNAS/Frontview): no prior agent session told the operator both ReadyNAS disks were "seriously pre-fail." The phrase in chat came from the operator (2026-10-29). Nearby SMART work was QNAP (`qnap.local`, session `session:76d515b3`), different hardware. Likely confusion with smartctl's attribute TYPE column labeled `Pre-fail` (means "this attribute can cause failure," not "drive is failing now") and/or EVDS load-cycle wear described as discard-worthy.
- 2026-10-29: first logged SMART short self-tests -- both `Completed without error` (`hdc` lifetime 8067 h, `hde` 40040 h). No prior self-test log entries existed on either disk.
