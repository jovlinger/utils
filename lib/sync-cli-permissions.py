#!/usr/bin/env python3
"""Merge portable project CLI permissions with Shell allows from global config.

Cursor CLI bug: when .cursor/cli.json has a permissions section, project allow
rules replace (not merge with) ~/.cursor/cli-config.json. "Always allow" writes
only to the global file, so shell grants never stick until they also appear here.

Run after approving new shell commands in the CLI:

    ./lib/sync-cli-permissions.py

See AGENTS.md (CLI permissions).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

UTILS_ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONFIG = UTILS_ROOT / ".cursor" / "cli.json"
GLOBAL_CONFIG = Path.home() / ".cursor" / "cli-config.json"

# Workspace-relative; Cursor scopes these to the current project root on any host.
PORTABLE_ALLOW = [
    "Write(**)",
    "Read(**)",
    "WebSearch(*)",
    "WebFetch(*)",
    # Broad first-token patterns (portable across machines).
    "Shell(git)",
    "Shell(cd)",
    "Shell(make)",
    "Shell(python3)",
    "Shell(rg)",
    "Shell(grep)",
    "Shell(find)",
    "Shell(cat)",
    "Shell(head)",
    "Shell(tail)",
    "Shell(sort)",
    "Shell(awk)",
    "Shell(sed)",
    "Shell(jq)",
    "Shell(curl)",
    "Shell(gh)",
    "Shell(wc)",
    "Shell(mkdir)",
    "Shell(rm)",
    "Shell(chmod)",
    "Shell(test)",
    "Shell(echo)",
    "Shell(printf)",
    "Shell(pwd)",
    "Shell(ls)",
    "Shell(bash)",
    "Shell(sh)",
    "Shell(sleep)",
    "Shell(timeout)",
    "Shell(xargs)",
    "Shell(tr)",
    "Shell(comm)",
    "Shell(du)",
    "Shell(df)",
    "Shell(stat)",
    "Shell(file)",
    "Shell(which)",
    "Shell(uname)",
    "Shell(true)",
    "Shell(kill)",
    "Shell(pkill)",
    "Shell(ps)",
    "Shell(pgrep)",
    "Shell(readlink)",
    "Shell(ln)",
    "Shell(touch)",
    "Shell(mktemp)",
    "Shell(sudo)",
    "Shell(go)",
    "Shell(sqlite3)",
    "Shell(mount)",
    "Shell(findmnt)",
    "Shell(namei)",
    "Shell(read)",
    "Shell(basename)",
    "Shell(type)",
    "Shell(continue)",
    "Shell(systemctl status)",
    "Shell(systemctl is-active)",
    "Shell(lsblk)",
    "Shell(lsattr)",
    "Shell(postingest)",
    "Shell(detest)",
    "Shell(./binlinks/todo)",
    "Shell(./binlinks/detest)",
    "Shell(./binlinks/importtags)",
    "Shell(./binlinks/shadup)",
    "Shell(./create_pipenv.sh)",
    "Shell(./importtags)",
    "Shell(./env/bin/pytest)",
    "Shell(.venv/bin/pytest)",
    "Shell(.venv/bin/python)",
    "Shell(shadup/.venv/bin/pytest)",
    "Shell(shadup/importtags)",
    "Shell(shadup/shadup)",
    "Shell(binlinks/todo)",
    "Shell(skills/projectmanagement/todos/todo.py)",
]


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def is_portable_shell(entry: str) -> bool:
    if not entry.startswith("Shell("):
        return False
    inner = entry[len("Shell(") : -1]
    if inner.startswith(('"', "'")):
        inner = inner[1:-1]
    return not inner.startswith("/")


def shell_allows_from_global(global_cfg: dict) -> list[str]:
    allow = global_cfg.get("permissions", {}).get("allow", [])
    return sorted(
        {
            entry
            for entry in allow
            if entry.startswith("Shell(") and is_portable_shell(entry)
        }
    )


def merge_allows(portable: list[str], synced: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for entry in portable + synced:
        if entry not in seen:
            seen.add(entry)
            merged.append(entry)
    return merged


def build_config(global_cfg: dict) -> dict:
    synced = shell_allows_from_global(global_cfg)
    return {
        "permissions": {
            "allow": merge_allows(PORTABLE_ALLOW, synced),
            "deny": [],
        }
    }


def main() -> int:
    global_cfg = load_json(GLOBAL_CONFIG)
    project_cfg = build_config(global_cfg)

    PROJECT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with PROJECT_CONFIG.open("w", encoding="utf-8") as fh:
        json.dump(project_cfg, fh, indent=2)
        fh.write("\n")

    allow = project_cfg["permissions"]["allow"]
    shell_count = sum(1 for entry in allow if entry.startswith("Shell("))
    print(f"Wrote {PROJECT_CONFIG}")
    print(f"  {len(allow)} allow entries ({shell_count} Shell)")
    if not GLOBAL_CONFIG.is_file():
        print(f"  (no global config at {GLOBAL_CONFIG})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
