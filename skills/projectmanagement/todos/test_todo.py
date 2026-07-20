#!/usr/bin/env python3
"""Black-box tests for todo.py: drive it as a binary (argv / stdout / exit code).

No imports of todo.py internals -- every case runs the script as a subprocess in
a throwaway git repo, exactly as an agent would invoke it. Run with:

    python3 -m unittest test_todo -v
    # or
    ./test_todo.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Dict, Optional

TODO_PY: Path = Path(__file__).resolve().parent / "todo.py"
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo  # noqa: E402  (direct import for unit-level regression tests)

# Offline by default so an accidental real fetch can never reach out or prompt.
ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


class TodoCase(unittest.TestCase):
    """Base: a fresh temp git repo per test, plus subprocess helpers."""

    def setUp(self) -> None:
        self.repo: Path = Path(tempfile.mkdtemp(prefix="todo-test-"))
        self._db_dir: Path = Path(tempfile.mkdtemp(prefix="todo-db-"))
        # Mark TODO_DIR populated so resolve_todo_dir does not fall through to
        # $HOME/.todo when that store already exists.
        (self._db_dir / "config.json").write_text("{}\n", encoding="utf-8")
        self._env: Dict[str, str] = {
            **ENV,
            "TODO_DIR": str(self._db_dir),
        }
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Tester")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self._db_dir, ignore_errors=True)

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, text=True,
            check=True, env=ENV,
        )

    def todo(
        self, *args: str, cwd: Optional[Path] = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run todo.py as a binary; return the completed process (never raises)."""
        return subprocess.run(
            [sys.executable, str(TODO_PY), *args],
            cwd=str(cwd or self.repo), capture_output=True, text=True,
            check=False, env=self._env,
        )

    def read_self(self) -> Dict[str, Any]:
        """Return the current branch ticket via the binary."""
        proc = self.todo("read", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def write_ticket(
        self,
        branch: str,
        ticket_id: str,
        summary: str = "x",
        *,
        body: str = "",
        extra: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> None:
        """Create *branch*, import a seed ticket into sqlite, optionally commit."""
        self._git("checkout", "-q", "-b", branch)
        ticket: Dict[str, Any] = {
            "Id": ticket_id,
            "Branch": branch,
            "State": {"init": {}},
            "Summary": {"raw": summary},
        }
        if body:
            ticket["Body"] = {"raw": body}
        if extra:
            ticket.update(extra)
        seed = self.repo / f"seed-{ticket_id[:8]}.json"
        seed.write_text(json.dumps(ticket), encoding="utf-8")
        proc = self.todo("import-json", f"--from-json={seed}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seed.unlink()  # transient import input; keep the worktree clean
        if commit:
            self._git("commit", "--allow-empty", "-qm", f"ticket {ticket_id[:8]}")

    def mint(self) -> str:
        """Mint an Id via the binary and assert the shape, returning it."""
        proc = self.todo("mint")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket_id = proc.stdout.strip()
        self.assertRegex(ticket_id, HEX64)
        return ticket_id


class MintTests(TodoCase):
    def test_mint_prints_64_lowercase_hex(self) -> None:
        self.assertRegex(self.mint(), HEX64)

    def test_mint_is_unique_across_calls(self) -> None:
        self.assertNotEqual(self.mint(), self.mint())

    def test_mint_outside_git_repo_errors_cleanly(self) -> None:
        nongit = Path(tempfile.mkdtemp(prefix="todo-nongit-"))
        try:
            proc = self.todo("mint", cwd=nongit)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("not a git repository", proc.stderr)
            self.assertEqual(proc.stdout, "")
        finally:
            shutil.rmtree(nongit, ignore_errors=True)


class MintSetInitFlowTests(TodoCase):
    """The two-phase flow: mint (pre-init) -> set --id -> init (promote)."""

    def _branch_exists(self, name: str) -> bool:
        return bool(self._git("branch", "--list", name).stdout.strip())

    def _read_id(self, tid: str) -> Dict[str, Any]:
        proc = self.todo("read", tid)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_mint_creates_pre_init_record(self) -> None:
        tid = self.mint()
        rec = self._read_id(tid)
        self.assertEqual(list(rec["State"].keys()), ["pre-init"])
        self.assertEqual(rec["Branch"], tid[:8])  # placeholder until set
        # mint must not create a git branch
        self.assertFalse(self._branch_exists(tid[:8]))

    def test_set_by_id_fills_fields_and_finalizes_branch(self) -> None:
        tid = self.mint()
        proc = self.todo("set", "--id", tid, "--summary", "persist the local db")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rec = self._read_id(tid)
        self.assertEqual(rec["Summary"]["raw"], "persist the local db")
        self.assertEqual(list(rec["State"].keys()), ["pre-init"])  # still collecting
        self.assertTrue(rec["Branch"].startswith(f"{tid[:8]}-"))
        self.assertIn("persist", rec["Branch"])
        # set --id must not create a git branch (sqlite-only)
        self.assertFalse(self._branch_exists(rec["Branch"]))

    def test_init_promotes_pre_init_to_branch(self) -> None:
        # An initial commit so the parent branch is born (--stay-on-parent can
        # check it back out). Real repos always have history here.
        self._git("commit", "--allow-empty", "-qm", "root")
        tid = self.mint()
        self.todo("set", "--id", tid, "--summary", "persist the local db")
        branch = self._read_id(tid)["Branch"]
        proc = self.todo("init", "--id", tid, "--stay-on-parent")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self._branch_exists(branch))
        rec = self._read_id(tid)
        self.assertEqual(list(rec["State"].keys()), ["init"])
        self.assertEqual(rec["Branch"], branch)

    def test_init_fresh_create_still_works(self) -> None:
        proc = self.todo("init", "--summary", "one shot fresh todo")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(self._branch_exists(out["Branch"]))
        self.assertEqual(list(self._read_id(out["Id"])["State"].keys()), ["init"])

    def test_ensure_worktree_is_stub(self) -> None:
        tid = self.mint()
        self.todo("set", "--id", tid, "--summary", "persist the local db")
        proc = self.todo("ensure_worktree", tid)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertFalse(out["created"])
        self.assertTrue(out["stub"])
        self.assertIn("worktrees", out["worktree"])


class ReadTests(TodoCase):
    def test_read_committed_by_8hex_prefix(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-demo", tid)
        proc = self.todo("read", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], tid)

    def test_read_by_full_digest(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-demo", tid)
        proc = self.todo("read", tid)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], tid)

    def test_read_four_char_prefix_ok(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-demo", tid)
        proc = self.todo("read", tid[:4])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_read_three_char_prefix_rejected(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-demo", tid)
        proc = self.todo("read", tid[:3])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("at least 4 hex", proc.stderr)

    def test_read_missing_id(self) -> None:
        proc = self.todo("read", "deadbeef")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no todo found", proc.stderr)

    def test_read_ambiguous_prefix_lists_locations(self) -> None:
        self.write_ticket("abcd0001-a", "abcd0001" + "f" * 56)
        self.write_ticket("abcd0002-b", "abcd0002" + "e" * 56)
        proc = self.todo("read", "abcd")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("ambiguous", proc.stderr)
        self.assertIn("abcd0001-a", proc.stderr)
        self.assertIn("abcd0002-b", proc.stderr)

    def test_read_orders_fields_and_elides_vectors(self) -> None:
        init = self.todo("init", "--summary=Vector demo", "--body=some text")
        self.assertEqual(init.returncode, 0, init.stderr)
        add = self.todo("work-item-add", "--summary=wi one")
        self.assertEqual(add.returncode, 0, add.stderr)

        elided = self.read_self()
        keys = list(elided.keys())
        self.assertEqual(keys[:3], ["Id", "Summary", "Body"])
        self.assertEqual(keys[-1], "WorkItems")
        # Embedding under Summary is a list-of-arrays (one vector per chunk);
        # each chunk vector is elided to its first two elements.
        self.assertEqual(len(elided["Summary"]["hash"]), 1)
        self.assertEqual(len(elided["Summary"]["hash"][0]), 2)

        proc = self.todo("read", "self", "-v")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        full = json.loads(proc.stdout)
        self.assertGreater(len(full["Summary"]["hash"][0]), 2)

    def test_longer_prefix_disambiguates(self) -> None:
        self.write_ticket("abcd0001-a", "abcd0001" + "f" * 56)
        self.write_ticket("abcd0002-b", "abcd0002" + "e" * 56)
        proc = self.todo("read", "abcd0001")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], "abcd0001" + "f" * 56)

    def test_worktree_uncommitted_is_found(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-wt", tid, commit=False)
        proc = self.todo("read", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], tid)

    def test_worktree_edit_takes_precedence_over_commit(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-demo", tid, summary="committed")
        proc = self.todo("set", "--summary=worktree-edit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("read", tid[:8])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(json.loads(proc2.stdout)["Summary"]["raw"], "worktree-edit")

    def test_read_self_uses_current_branch_without_id_in_name(self) -> None:
        tid = self.mint()
        self.write_ticket("feature-without-id", tid, summary="current branch")
        proc = self.todo("read", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], tid)

    def test_curr_aliases_self(self) -> None:
        tid = self.mint()
        self.write_ticket("another-feature-name", tid, summary="current branch")
        proc = self.todo("read", "curr")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], tid)


class LocalFirstTests(TodoCase):
    def test_read_does_not_fetch_unreachable_remote(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-demo", tid)
        self._git("remote", "add", "origin", "https://invalid.invalid/nope.git")
        proc = self.todo("read", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["Id"], tid)
        self.assertNotIn("fetch failed", proc.stderr)


class CliTests(TodoCase):
    def test_no_subcommand_is_usage_error(self) -> None:
        proc = self.todo()
        self.assertEqual(proc.returncode, 2)

    def test_unknown_subcommand_is_usage_error(self) -> None:
        proc = self.todo("frobnicate")
        self.assertEqual(proc.returncode, 2)


class InitTests(TodoCase):
    def test_init_creates_branch_and_todo(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("init", "--summary=Fix sensor", "--ac=reads fresh")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("Id", payload)
        self.assertIn("Branch", payload)
        branch = payload["Branch"]
        proc2 = self.todo("read", payload["Id"][:8])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        ticket = json.loads(proc2.stdout)
        self.assertEqual(ticket["Summary"]["raw"], "Fix sensor")
        self.assertEqual(ticket["State"], {"init": {}})
        self._git("checkout", branch)
        proc3 = self.todo("read", "self")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)
        self.assertEqual(json.loads(proc3.stdout)["Id"], payload["Id"])
        self.assertFalse((self.repo / "TODO.json").is_file())

    def test_init_refuses_second_ticket_on_branch(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("init", "--summary=One")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("init", "--summary=Two")
        self.assertEqual(proc2.returncode, 1)
        self.assertIn("already exists", proc2.stderr)

    def test_init_then_set_state_in_one_call(self) -> None:
        """init accepts set's args and applies them; --state lands post-init."""
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("init", "--summary=Groom me", "--state=pre")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket = json.loads(self.todo("read", json.loads(proc.stdout)["Id"][:8]).stdout)
        self.assertEqual(ticket["State"], {"pre": {}})

    def test_init_noninteractive_EDIT_creates_nothing(self) -> None:
        """A non-tty EDIT value aborts with exit 1 and leaves no todo/branch."""
        self._git("commit", "--allow-empty", "-qm", "seed")
        head_before = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        proc = self.todo("init", "--summary=EDIT")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("interactive terminal", proc.stderr)
        # no branch switched to / created, no ticket in the store
        self.assertEqual(
            self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), head_before
        )
        self.assertEqual(self.todo("ls").stdout.strip(), "")


class SetStateViaSetTests(TodoCase):
    def test_set_state_flag_replaces_set_state_subcommand(self) -> None:
        """`set --state` transitions State; the old `set-state` subcommand is gone."""
        self._git("commit", "--allow-empty", "-qm", "seed")
        branch = json.loads(self.todo("init", "--summary=Do it").stdout)["Branch"]
        self._git("checkout", "-q", branch)
        proc = self.todo("set", "--state", "working", "--owner=agent")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_self()["State"], {"working": {"owner": "agent"}})
        # the removed subcommand must not resolve anymore
        gone = self.todo("set-state", "done")
        self.assertNotEqual(gone.returncode, 0)


class RmTests(TodoCase):
    def test_rm_soft_deletes_from_store(self) -> None:
        """`todo rm` tombstones the todo; it is no longer readable by id."""
        self._git("commit", "--allow-empty", "-qm", "seed")
        payload = json.loads(self.todo("init", "--summary=Delete me").stdout)
        tid = payload["Id"]
        rm = self.todo("rm", tid[:8])
        self.assertEqual(rm.returncode, 0, rm.stderr)
        self.assertIn("removed: soft", rm.stdout)
        self.assertNotEqual(self.todo("read", tid[:8]).returncode, 0)


class AddSubtodoTests(TodoCase):
    def test_add_subtodo_from_json_registers_on_parent(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        parent_id = self.mint()
        self._git("checkout", "-q", "-b", "parent-branch")
        parent = {
            "Id": parent_id,
            "Branch": "parent-branch",
            "create_dt": "2026-06-23T00:00:00Z",
            "update_dt": "2026-06-23T00:00:00Z",
            "State": {"init": {}},
            "Scope": {"path_to_project": str(self.repo), "branch": "parent-branch"},
            "Summary": {"raw": "parent"},
            "Body": {"raw": ""},
            "AC": "children merged",
            "Subtodos": [],
        }
        parent_seed = self.repo / "parent.json"
        parent_seed.write_text(json.dumps(parent), encoding="utf-8")
        proc_parent = self.todo("import-json", f"--from-json={parent_seed}")
        self.assertEqual(proc_parent.returncode, 0, proc_parent.stderr)
        self._git("commit", "--allow-empty", "-qm", "parent todo")

        child_id = self.mint()
        child_path = self.repo / "child.json"
        child_path.write_text(
            json.dumps(
                {
                    "Id": child_id,
                    "Branch": f"{child_id[:8]}-child-demo",
                    "Summary": {"raw": "child work"},
                    "Body": {"raw": "do child"},
                    "AC": "child done",
                    "WorkItems": [],
                }
            ),
            encoding="utf-8",
        )
        proc = self.todo("add-subtodo", f"--from-json={child_path}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._git("checkout", "parent-branch")
        parent_ticket = self.read_self()
        self.assertEqual(len(parent_ticket["Subtodos"]), 1)
        self.assertEqual(parent_ticket["Subtodos"][0]["Id"], child_id)
        proc2 = self.todo("read", child_id[:8])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)


class FieldAndWorkItemTests(TodoCase):
    def test_set_updates_top_level_editable_fields(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-fields", tid)
        proc = self.todo(
            "set",
            "--summary=Renamed ticket",
            "--body=More detail",
            "--ac=All checks pass",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket = self.read_self()
        self.assertEqual(ticket["Summary"]["raw"], "Renamed ticket")
        self.assertEqual(ticket["Body"]["raw"], "More detail")
        self.assertEqual(ticket["AC"], "All checks pass")

    def test_work_item_aliases_add_and_done_items(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-work-items", tid)
        proc = self.todo("work-item-add", "--summary=first item")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("work-item-add", "--summary=second item")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        proc3 = self.todo("work-item-done")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)

        ticket = self.read_self()
        work_items = ticket["WorkItems"]
        self.assertEqual(len(work_items), 2)
        first, second = work_items
        # work-item-done completes the cursor (first not-done) item as a typed code item.
        self.assertEqual(first["kind"], "code")
        self.assertEqual(first["summary"], "first item")
        self.assertTrue(first["done"])
        self.assertRegex(first["sha"], r"\A[0-9a-f]{40}\Z")
        self.assertEqual(second, {"kind": "task", "summary": "second item", "done": False})


class PathTests(TodoCase):
    def _set_json_path(self, *args: str, stdin: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TODO_PY), "set-json-path", *args],
            cwd=str(self.repo), input=stdin, capture_output=True, text=True,
            check=False, env=self._env,
        )

    def test_set_json_path_on_other_branch(self) -> None:
        tid = self.mint()
        branch = f"{tid[:8]}-target"
        self.write_ticket(branch, tid, summary="target")
        self._git("checkout", "-q", "-b", "other-branch")
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self._set_json_path(tid[:8], "Body.raw", stdin='"patched body"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "patched body")
        self._git("checkout", branch)
        proc2 = self.todo("read", "self")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(json.loads(proc2.stdout)["Body"]["raw"], "patched body")

    def test_get_json_path_prints_scalar_from_self(self) -> None:
        tid = self.mint()
        self.write_ticket("plain-current-branch", tid, summary="read me")
        proc = self.todo("get-json-path", "self", "Summary.raw")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "read me")

    def test_get_json_path_prints_json_values_as_json(self) -> None:
        tid = self.mint()
        self.write_ticket("state-branch", tid)
        proc = self.todo("get-json-path", "self", "State")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"init": {}})

    def test_get_json_path_no_such_path_reports_worked_missing_options(self) -> None:
        tid = self.mint()
        self.write_ticket("missing-path-branch", tid, summary="have summary")
        proc = self.todo("get-json-path", "self", "Summary.bogus")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        err = proc.stderr
        self.assertIn("path Summary no such field bogus.", err)
        self.assertIn("available:", err)
        self.assertIn("raw", err)

    def test_set_json_path_updates_current_branch(self) -> None:
        tid = self.mint()
        self.write_ticket("path-current-branch", tid)
        proc = self._set_json_path("self", "Body.raw", stdin='"patched body"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "patched body")
        proc2 = self.todo("get-json-path", "self", "Body.raw")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(proc2.stdout.strip(), "patched body")

    def test_set_json_path_accepts_json_null(self) -> None:
        tid = self.mint()
        self.write_ticket("null-current-branch", tid)
        proc = self._set_json_path("self", "AC", stdin="null")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "null")
        proc2 = self.todo("get-json-path", "self", "AC")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(json.loads(proc2.stdout), None)

    def test_jq_subcommand_removed_use_read_pipe(self) -> None:
        """Filtering is `todo read | jq`, not a todo.py jq subcommand."""
        tid = self.mint()
        self.write_ticket("jq-pipe-branch", tid, summary="jq summary")
        gone = self.todo("jq", "self", ".Summary.raw")
        self.assertNotEqual(gone.returncode, 0, gone.stdout + gone.stderr)
        self.assertIn("invalid choice: 'jq'", gone.stderr)
        if shutil.which("jq") is None:
            self.skipTest("jq binary is not installed")
        read = self.todo("read", "self")
        self.assertEqual(read.returncode, 0, read.stderr)
        proc = subprocess.run(
            ["jq", ".Summary.raw"],
            input=read.stdout,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), "jq summary")

    def test_read_migrates_chunks_and_subtickets(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-legacy",
            tid,
            extra={"Chunks": [{"summary": "one", "done": False}], "Subtickets": []},
        )
        proc = self.todo("read", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        loaded = json.loads(proc.stdout)
        self.assertIn("WorkItems", loaded)
        self.assertIn("Subtodos", loaded)
        self.assertNotIn("Chunks", loaded)
        self.assertNotIn("Subtickets", loaded)


class StateTests(TodoCase):
    def test_set_state_done_then_merged(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-leaf", tid)
        proc = self.todo("set", "--state", "done", "--last-commit=finish child")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("get-json-path", "self", "State")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(
            json.loads(proc2.stdout),
            {"done": {"last_commit": "finish child"}},
        )

        proc3 = self.todo("set", "--state", "merged", "--merged-into=parent-branch")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)
        proc4 = self.todo("get-json-path", "self", "State")
        self.assertEqual(proc4.returncode, 0, proc4.stderr)
        self.assertEqual(
            json.loads(proc4.stdout),
            {"merged": {"merged_into": "parent-branch"}},
        )

    def test_set_state_done_records_actual_summary(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-leaf", tid)
        proc = self.todo(
            "set", "--state", "done", "--actual-summary=rewrote the parser instead of patching it"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = self.todo("get-json-path", "self", "ActualSummary")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(got.stdout.strip(), "rewrote the parser instead of patching it")
        # doctor accepts the new whitelisted field
        doc = self.todo("doctor", "self")
        self.assertEqual(doc.returncode, 0, doc.stdout)


class WaitTests(TodoCase):
    def test_wait_for_done_succeeds_immediately(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-done", tid)
        proc = self.todo("set", "--state", "done")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("wait-for", tid[:8], "--timeout=0", "--interval=0")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(json.loads(proc2.stdout)["State"], "done")

    def test_wait_for_times_out_when_state_missing(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-init", tid)
        proc = self.todo("wait-for", tid[:8], "--timeout=0", "--interval=0")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("timed out waiting for done", proc.stderr)

    def test_wait_and_merge_merges_done_child(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        parent_id = self.mint()
        self._git("checkout", "-q", "-b", "parent-branch")
        parent = {
            "Id": parent_id,
            "Branch": "parent-branch",
            "State": {"init": {}},
            "Summary": {"raw": "parent"},
            "Subtodos": [],
        }
        parent_seed = self.repo / "parent.json"
        parent_seed.write_text(json.dumps(parent), encoding="utf-8")
        proc_parent = self.todo("import-json", f"--from-json={parent_seed}")
        self.assertEqual(proc_parent.returncode, 0, proc_parent.stderr)
        self._git("commit", "--allow-empty", "-qm", "parent todo")

        child_id = self.mint()
        proc = self.todo(
            "add-subtodo",
            f"--id={child_id}",
            f"--branch={child_id[:8]}-child",
            "--summary=child",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._git("checkout", f"{child_id[:8]}-child")
        proc2 = self.todo("set", "--state", "done")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self._git("checkout", "parent-branch")

        proc3 = self.todo("wait-and-merge", child_id[:8], "--timeout=0", "--interval=0")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)
        parent_ticket = self.read_self()
        self.assertEqual(parent_ticket["Subtodos"][0]["State"], "merged")
        self._git("checkout", f"{child_id[:8]}-child")
        child_proc = self.todo("get-json-path", "self", "State")
        self.assertEqual(child_proc.returncode, 0, child_proc.stderr)
        self.assertEqual(
            json.loads(child_proc.stdout),
            {"merged": {"merged_into": "parent-branch"}},
        )

    def test_merge_subtodo_uses_child_actual_summary(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=parent feature")
        self.assertEqual(init.returncode, 0, init.stderr)
        parent_branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

        child_id = self.mint()
        add = self.todo(
            "add-subtodo", f"--id={child_id}", f"--branch={child_id[:8]}-child", "--summary=planned title"
        )
        self.assertEqual(add.returncode, 0, add.stderr)
        self._git("checkout", f"{child_id[:8]}-child")
        # child finishes and records how it actually panned out
        done = self.todo("set", "--state", "done", "--actual-summary=actually landed via a rewrite")
        self.assertEqual(done.returncode, 0, done.stderr)
        self._git("checkout", parent_branch)

        merge = self.todo("merge-subtodo", child_id[:8])
        self.assertEqual(merge.returncode, 0, merge.stderr)

        # parent's merge_subtodo work item carries the ActualSummary, not the plan
        parent = self.read_self()
        merge_items = [
            wi for wi in parent["WorkItems"] if wi.get("kind") == "merge_subtodo"
        ]
        self.assertEqual(len(merge_items), 1, parent["WorkItems"])
        self.assertIn("actually landed via a rewrite", merge_items[0]["summary"])
        self.assertNotIn("planned title", merge_items[0]["summary"])
        # and the parent-branch merge commit subject too
        subject = self._git("log", "-1", "--format=%s").stdout.strip()
        self.assertIn("actually landed via a rewrite", subject)


class DoctorTests(TodoCase):
    def test_doctor_passes_for_minimal_ticket(self) -> None:
        tid = self.mint()
        self.write_ticket("doctor-ok", tid)
        proc = self.todo("doctor")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_doctor_fails_unknown_top_level_field(self) -> None:
        tid = self.mint()
        self.write_ticket("doctor-bad", tid, extra={"Surprise": True})
        proc = self.todo("doctor", "self")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("unknown top-level fields: Surprise", payload["findings"])

    def test_doctor_warns_unmerged_subtodo_while_parent_open(self) -> None:
        tid = self.mint()
        child = self.mint()
        self.write_ticket(
            f"{tid[:8]}-parent",
            tid,
            extra={"Subtodos": [{"Id": child, "Branch": "c", "State": "working"}]},
        )
        proc = self.todo("doctor", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(
            any(child[:8] in w and "not merged" in w for w in payload["warnings"]),
            payload["warnings"],
        )

    def test_doctor_fails_unmerged_subtodo_when_parent_done(self) -> None:
        tid = self.mint()
        child = self.mint()
        self.write_ticket(
            f"{tid[:8]}-parent",
            tid,
            extra={
                "State": {"done": {}},
                "Subtodos": [{"Id": child, "Branch": "c", "State": "done"}],
            },
        )
        proc = self.todo("doctor", "self")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(child[:8] in f and "must merge" in f for f in payload["findings"]),
            payload["findings"],
        )

    def test_doctor_passes_when_all_subtodos_merged_and_parent_done(self) -> None:
        tid = self.mint()
        child = self.mint()
        self.write_ticket(
            f"{tid[:8]}-parent",
            tid,
            extra={
                "State": {"done": {}},
                "Subtodos": [{"Id": child, "Branch": "c", "State": "merged"}],
            },
        )
        proc = self.todo("doctor", "self")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_doctor_finds_wait_dependency_cycle(self) -> None:
        first_id = self.mint()
        second_id = self.mint()
        self.write_ticket(
            f"{first_id[:8]}-first",
            first_id,
            summary="first",
            extra={
                "WorkItems": [
                    {
                        "summary": "wait for second",
                        "done": False,
                        "execution": {"wait_for": [second_id[:8]]},
                    }
                ]
            },
        )
        self.write_ticket(
            f"{second_id[:8]}-second",
            second_id,
            summary="second",
            extra={
                "WorkItems": [
                    {
                        "summary": "wait for first",
                        "done": False,
                        "execution": {"wait_for": [first_id[:8]]},
                    }
                ]
            },
        )
        proc = self.todo("doctor", first_id[:8])
        self.assertEqual(proc.returncode, 1)
        findings = json.loads(proc.stdout)["findings"]
        self.assertTrue(any("wait dependency cycle" in finding for finding in findings))


class LogTests(TodoCase):
    def test_log_renders_parent_and_subtodo_tree(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Parent feature")
        self.assertEqual(init.returncode, 0, init.stderr)
        parent_id = json.loads(init.stdout)["Id"]
        add = self.todo("add-subtodo", "--summary=child one")
        self.assertEqual(add.returncode, 0, add.stderr)

        proc = self.todo("log", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertTrue(
            any(ln.startswith("* ") and parent_id[:8] in ln and "Parent feature" in ln for ln in lines),
            proc.stdout,
        )
        child_lines = [ln for ln in lines if "child one" in ln]
        self.assertEqual(len(child_lines), 1, proc.stdout)
        self.assertFalse(child_lines[0].startswith("* "), proc.stdout)
        self.assertIn("*", child_lines[0])

    def test_log_all_includes_root_ticket(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Solo ticket")
        self.assertEqual(init.returncode, 0, init.stderr)
        proc = self.todo("log", "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Solo ticket", proc.stdout)

    def test_log_unknown_selector_errors(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("log", "deadbeef")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no todo found", proc.stderr)

    def test_log_verbose_lists_branch_commits(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Verbose parent")
        self.assertEqual(init.returncode, 0, init.stderr)
        plain = self.todo("log", "self")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertNotIn("chore(todo)", plain.stdout)
        verbose = self.todo("log", "self", "-v")
        self.assertEqual(verbose.returncode, 0, verbose.stderr)
        self.assertIn("chore(todo): init ticket", verbose.stdout)


class SearchTests(TodoCase):
    def _emb_rows(self) -> list:
        """Return (ticket_id, field_path, embedder) rows straight from sqlite."""
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            return conn.execute(
                "SELECT ticket_id, field_path, embedder FROM embeddings"
            ).fetchall()
        finally:
            conn.close()

    def test_search_finds_oauth_bearer_ticket(self) -> None:
        oauth_id = self.mint()
        other_id = self.mint()
        self.write_ticket(
            f"{oauth_id[:8]}-oauth",
            oauth_id,
            summary="oauth bearer token refresh",
            body="Handle oauth bearer token rotation for API clients.",
        )
        self.write_ticket(f"{other_id[:8]}-other", other_id, summary="unrelated database work")
        # --embedder hash keeps this hermetic (apple is unavailable on CI) and
        # gives a hard 0-similarity cutoff so the unrelated ticket is excluded.
        proc = self.todo("search", "oauth bearer token", "--embedder", "hash")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(oauth_id[:8], proc.stdout)
        self.assertNotIn(other_id[:8], proc.stdout)

    def test_cheap_embedder_autopopulated_on_write(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="alpha beta gamma")
        self.assertIn((tid, "Summary.raw", "hash"), self._emb_rows())

    def test_raw_change_clears_stale_expensive_vector(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="first summary text")
        # Inject a stale expensive vector as if a prior search had backfilled it.
        stale = "apple_nlce:x:r1:pool=mean:norm=l2:v1"
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        conn.execute(
            "INSERT INTO embeddings(ticket_id, field_path, embedder, vector) VALUES (?,?,?,?)",
            (tid, "Summary.raw", stale, b"\x00\x00\x00\x00"),
        )
        conn.commit()
        conn.close()
        proc = self.todo("set", "--summary", "completely different text", "--no-commit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        embedders = {emb for _t, _f, emb in self._emb_rows()}
        self.assertNotIn(stale, embedders)  # cleared on raw change
        self.assertIn("hash", embedders)  # cheap repopulated

    def test_no_clear_keeps_stale_vector(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="first summary text")
        stale = "apple_nlce:x:r1:pool=mean:norm=l2:v1"
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        conn.execute(
            "INSERT INTO embeddings(ticket_id, field_path, embedder, vector) VALUES (?,?,?,?)",
            (tid, "Summary.raw", stale, b"\x00\x00\x00\x00"),
        )
        conn.commit()
        conn.close()
        proc = self.todo(
            "set", "--summary", "completely different text", "--no-commit", "--no-clear"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(stale, {emb for _t, _f, emb in self._emb_rows()})  # kept

    def test_search_backfills_missing_and_dry_run_does_not(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="alpha beta gamma")
        # mock is not cheap, so it is not populated on write.
        self.assertNotIn("mock", {emb for _t, _f, emb in self._emb_rows()})
        # dry-run must not write any mock vector...
        proc = self.todo("search", "alpha", "--embedder", "mock", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("mock", {emb for _t, _f, emb in self._emb_rows()})
        # ...a normal search backfills it.
        proc = self.todo("search", "alpha", "--embedder", "mock")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("mock", {emb for _t, _f, emb in self._emb_rows()})

    def test_search_reports_embedding_refresh_progress_to_stderr(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="alpha beta gamma",
            body="a second field to embed",
        )
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            conn.executescript(
                """
                CREATE TABLE ticket_write_audit (ticket_id TEXT);
                CREATE TRIGGER audit_ticket_update AFTER UPDATE ON tickets
                BEGIN
                    INSERT INTO ticket_write_audit(ticket_id) VALUES (NEW.id);
                END;
                """
            )
            conn.commit()
        finally:
            conn.close()

        proc = self.todo("search", "alpha", "--embedder", "mock")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "refreshing embeddings..Done\n")
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            stored_todo = json.loads(
                conn.execute("SELECT data FROM tickets WHERE id = ?", (tid,)).fetchone()[0]
            )
            writes = conn.execute(
                "SELECT COUNT(*) FROM ticket_write_audit WHERE ticket_id = ?", (tid,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIn("mock", stored_todo["Summary"])
        self.assertIn("mock", stored_todo["Body"])
        self.assertEqual(writes, 1)

        # A fully populated index needs no refresh and emits no progress line.
        again = self.todo("search", "alpha", "--embedder", "mock")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stderr, "")

    def test_read_shows_expensive_embedder_backfilled_by_search(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="alpha beta gamma")
        before = json.loads(self.todo("read", tid[:8]).stdout)
        self.assertNotIn("mock", before["Summary"])
        proc = self.todo("search", "alpha", "--embedder", "mock")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # mock is written only to the sqlite index (never inline at save time);
        # read must merge it in from there, elided like any other embedder.
        after = json.loads(self.todo("read", tid[:8]).stdout)
        self.assertEqual(len(after["Summary"]["mock"][0]), 2)

    def test_search_unknown_embedder_errors(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="alpha")
        proc = self.todo("search", "alpha", "--embedder", "bogus")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("bogus", proc.stderr)

    def test_embedders_lists_non_hidden_only(self) -> None:
        proc = self.todo("embedders")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hash", proc.stdout)
        self.assertIn("apple", proc.stdout)
        for hidden in ("mock", "null", "st"):
            self.assertNotIn(hidden, proc.stdout)


class ParentPromptTests(TodoCase):
    def _base_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _init(self, summary: str, body: str = "") -> str:
        proc = self.todo("init", f"--summary={summary}", f"--body={body}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["Id"]

    def _set_parents(self, *parents: str) -> None:
        args = ["set"]
        for parent in parents:
            args += ["--parent", parent]
        proc = self.todo(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def _read(self, sel: str) -> Dict[str, Any]:
        proc = self.todo("read", sel)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_set_parent_inserts_info_backlink(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        parent_id = self._init("parent", body="why we are here")
        self._git("checkout", base)
        child_id = self._init("child", body="do the thing")
        self._set_parents(parent_id[:8])
        # Child records the parent ref...
        child = self._read(child_id[:8])
        self.assertEqual([p["Id"] for p in child["Parent"]], [parent_id])
        # ...and the parent now carries a follow-only INFO back-link to the child.
        parent = self._read(parent_id[:8])
        subtodos = parent.get("Subtodos", [])
        self.assertEqual(len(subtodos), 1, subtodos)
        self.assertEqual(subtodos[0]["Id"], child_id)
        self.assertEqual(subtodos[0]["State"], "INFO")
        self.assertEqual(subtodos[0]["Summary"], "child")

    def test_set_parent_make_it_so_replaces_and_drops_old_info(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        a_id = self._init("alpha", body="a")
        self._git("checkout", base)
        b_id = self._init("beta", body="b")
        self._git("checkout", base)
        child_id = self._init("child", body="c")
        self._set_parents(a_id[:8])
        self.assertEqual(
            [p["Id"] for p in self._read(child_id[:8])["Parent"]], [a_id]
        )
        self.assertEqual(self._read(a_id[:8])["Subtodos"][0]["State"], "INFO")

        # Make-it-so to B alone: A loses INFO, B gains it.
        self._set_parents(b_id[:8])
        child = self._read(child_id[:8])
        self.assertEqual([p["Id"] for p in child["Parent"]], [b_id])
        self.assertEqual(self._read(a_id[:8]).get("Subtodos", []), [])
        b = self._read(b_id[:8])
        self.assertEqual(len(b["Subtodos"]), 1)
        self.assertEqual(b["Subtodos"][0]["Id"], child_id)
        self.assertEqual(b["Subtodos"][0]["State"], "INFO")

    def test_set_parent_blank_clears(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        parent_id = self._init("parent", body="ctx")
        self._git("checkout", base)
        child_id = self._init("child", body="task")
        self._set_parents(parent_id[:8])
        clear = self.todo("set", "--parent=")
        self.assertEqual(clear.returncode, 0, clear.stderr)
        self.assertEqual(self._read(child_id[:8]).get("Parent", []), [])
        self.assertEqual(self._read(parent_id[:8]).get("Subtodos", []), [])

    def test_info_backlink_excluded_from_merge_completeness(self) -> None:
        # A parent with only an INFO back-link can go done without a hard finding.
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        parent_id = self._init("parent", body="ctx")
        self._git("checkout", base)
        self._init("child", body="task")
        self._set_parents(parent_id[:8])
        self._git("checkout", f"{parent_id[:8]}-parent")
        self.assertEqual(self.todo("set", "--state", "done").returncode, 0)
        doc = self.todo("doctor", "self")
        self.assertEqual(doc.returncode, 0, doc.stdout)
        self.assertTrue(json.loads(doc.stdout)["ok"])

    def _strip_subtodos(self, parent_id: str) -> None:
        """Mimic a legacy one-way link: remove the auto-inserted back-link."""
        empty = self.repo / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        proc = self.todo("set-json-path", parent_id[:8], "Subtodos", "--file", str(empty), "--no-commit")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        empty.unlink()
        self.assertEqual(self._read(parent_id[:8]).get("Subtodos", []), [])

    def test_doctor_repairs_backlink_and_dry_run_does_not_write(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        parent_id = self._init("parent", body="ctx")
        self._git("checkout", base)
        child_id = self._init("child", body="task")
        self._set_parents(parent_id[:8])
        self._strip_subtodos(parent_id)

        # --dry-run reports the intended repair but does not write it
        dry = self.todo("doctor", child_id[:8], "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        payload = json.loads(dry.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertTrue(any(child_id[:8] in r for r in payload["repairs"]), payload["repairs"])
        self.assertEqual(self._read(parent_id[:8]).get("Subtodos", []), [])

        # a real run re-establishes the INFO back-link
        fix = self.todo("doctor", child_id[:8])
        self.assertEqual(fix.returncode, 0, fix.stderr)
        self.assertTrue(any(child_id[:8] in r for r in json.loads(fix.stdout)["repairs"]))
        parent = self._read(parent_id[:8])
        self.assertEqual(parent["Subtodos"][0]["Id"], child_id)
        self.assertEqual(parent["Subtodos"][0]["State"], "INFO")

    def test_doctor_all_sweeps_corpus_and_repairs(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        parent_id = self._init("parent", body="ctx")
        self._git("checkout", base)
        self._init("child", body="task")
        self._set_parents(parent_id[:8])
        self._strip_subtodos(parent_id)

        proc = self.todo("doctor", "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertGreaterEqual(payload["audited"], 2)
        self.assertTrue(payload["ok"])
        # the corpus sweep visited the child and repaired the parent
        parent = self._read(parent_id[:8])
        self.assertEqual(parent["Subtodos"][0]["State"], "INFO")

    def test_set_accepts_multiple_parents(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        a_id = self._init("alpha", body="a")
        self._git("checkout", base)
        b_id = self._init("beta", body="b")
        self._git("checkout", base)
        child_id = self._init("child", body="c")
        self._set_parents(a_id[:8], b_id[:8])
        child = self._read(child_id[:8])
        self.assertEqual({p["Id"] for p in child["Parent"]}, {a_id, b_id})
        self.assertEqual(self._read(a_id[:8])["Subtodos"][0]["State"], "INFO")
        self.assertEqual(self._read(b_id[:8])["Subtodos"][0]["State"], "INFO")

    def test_prompt_concatenates_chain_root_first(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        gp_id = self._init("grandparent", body="GP-WHY")
        self._git("checkout", base)
        parent_id = self._init("parent", body="PARENT-WHY")
        self._set_parents(gp_id[:8])
        self._git("checkout", base)
        child_id = self._init("child", body="CHILD-TASK")
        self._set_parents(parent_id[:8])
        proc = self.todo("prompt", child_id[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertLess(out.index("GP-WHY"), out.index("PARENT-WHY"))
        self.assertLess(out.index("PARENT-WHY"), out.index("CHILD-TASK"))

    def test_prompt_defaults_to_self(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        self._init("solo", body="SELF-BODY")  # leaves us on the new todo branch
        proc = self.todo("prompt")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SELF-BODY", proc.stdout)

    def test_prompt_notes_unresolvable_parent(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        self._init("orphan", body="ORPHAN")  # on the orphan todo branch (self)
        # Hand-graft a dangling parent ref; prompt should note it, not crash.
        ref = self.repo / "parent.json"
        ref.write_text(json.dumps([{"Id": "deadbeefdeadbeef", "Branch": "gone"}]))
        proc = self.todo(
            "set-json-path", "self", "Parent", "--file", str(ref), "--no-commit"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ref.unlink()
        proc = self.todo("prompt", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not found", proc.stdout)
        self.assertIn("ORPHAN", proc.stdout)

    def test_add_subtodo_parent_is_list_and_prompt_walks_up(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        parent_id = self._init("parent feature", body="parent why")
        add = self.todo("add-subtodo", "--summary=child one", "--body=child body")
        self.assertEqual(add.returncode, 0, add.stderr)
        child_id = json.loads(add.stdout)["Id"]
        child = self._read(child_id[:8])
        self.assertIsInstance(child["Parent"], list)
        self.assertEqual(child["Parent"][0]["Id"], parent_id)
        proc = self.todo("prompt", child_id[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("parent why", proc.stdout)
        self.assertIn("child body", proc.stdout)

    def test_set_parent_does_not_remove_tracked_subtodo(self) -> None:
        # add-subtodo leaves a mergeable Subtodos row; set --parent elsewhere
        # must not strip that tracked entry from the structural parent.
        self._git("commit", "--allow-empty", "-qm", "seed")
        base = self._base_branch()
        parent_id = self._init("parent feature", body="parent why")
        add = self.todo("add-subtodo", "--summary=child one", "--body=child body")
        self.assertEqual(add.returncode, 0, add.stderr)
        add_out = json.loads(add.stdout)
        child_id = add_out["Id"]
        child_branch = add_out["Branch"]
        self._git("checkout", base)
        other_id = self._init("other ctx", body="ctx")
        self._git("checkout", child_branch)
        self._set_parents(other_id[:8])
        parent = self._read(parent_id[:8])
        self.assertEqual(len(parent["Subtodos"]), 1)
        self.assertEqual(parent["Subtodos"][0]["Id"], child_id)
        self.assertNotEqual(parent["Subtodos"][0]["State"], "INFO")
        other = self._read(other_id[:8])
        self.assertEqual(other["Subtodos"][0]["State"], "INFO")
        self.assertEqual(other["Subtodos"][0]["Id"], child_id)


class ImportJsonTests(TodoCase):
    def test_import_json_scan_refs_imports_committed_legacy_files(self) -> None:
        tid = self.mint()
        branch = f"{tid[:8]}-legacy-ref"
        self._git("checkout", "-q", "-b", branch)
        ticket = {
            "Id": tid,
            "Branch": branch,
            "State": {"init": {}},
            "Summary": {"raw": "legacy git blob"},
        }
        (self.repo / "TODO.json").write_text(json.dumps(ticket), encoding="utf-8")
        self._git("add", "TODO.json")
        self._git("commit", "-qm", "legacy todo json")

        proc = self.todo("import-json", "--scan-refs")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertGreaterEqual(payload["imported"], 1)

        read_proc = self.todo("read", tid[:8])
        self.assertEqual(read_proc.returncode, 0, read_proc.stderr)
        self.assertEqual(json.loads(read_proc.stdout)["Summary"]["raw"], "legacy git blob")


class WebViewerTests(TodoCase):
    def test_web_dump_html_renders_done_todo_with_message_and_diff(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        self._git("remote", "add", "origin", "git@github.com:jovlinger/utils.git")
        init = self.todo("init", "--summary=Viewer parent")
        self.assertEqual(init.returncode, 0, init.stderr)
        self.todo("work-item-add", "--summary=add evidence")
        (self.repo / "app.txt").write_text("before\n", encoding="utf-8")
        done = self.todo("work-item-done", "-m", "add app evidence")
        self.assertEqual(done.returncode, 0, done.stderr)
        sha = self.read_self()["WorkItems"][0]["sha"]

        proc = self.todo("web", "--dump-html", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("Viewer parent", out)  # summary section
        self.assertIn('class="wi', out)  # a clickable work-item box
        self.assertIn(sha[:8], out)  # short sha shown on the box
        self.assertIn("add app evidence", out)  # commit message embedded for the fold
        self.assertIn("+before", out)  # unified diff embedded for the fold
        self.assertIn("https://github.com/jovlinger/utils/commit/" + sha, out)
        self.assertIn(str(self.repo), out)

    def test_web_dump_html_renders_open_todo(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Open viewer")
        self.assertEqual(init.returncode, 0, init.stderr)
        self.todo("work-item-add", "--summary=do the thing")
        proc = self.todo("web", "--dump-html", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("Open viewer", out)
        self.assertIn("Work items", out)  # labeled section
        self.assertIn("do the thing", out)  # not-done work item box
        self.assertIn("state-tag", out)
        self.assertIn("Click a work item", out)  # default fold hint

    def test_web_dump_html_links_subtodo_to_referencing_work_item(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Parent viewer")
        self.assertEqual(init.returncode, 0, init.stderr)
        parent_id = json.loads(init.stdout)["Id"]
        add = self.todo("add-subtodo", "--summary=child viewer")
        self.assertEqual(add.returncode, 0, add.stderr)
        parent = json.loads(self.todo("read", parent_id[:8]).stdout)
        child_id = parent["Subtodos"][0]["Id"]

        proc = self.todo("web", "--dump-html", parent_id[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("Parent viewer", out)
        self.assertIn("child viewer", out)  # subtodo box + embedded read-only repr
        # The subtodo box carries the full id; the start_subtodo work item references it.
        self.assertIn(f'data-st="{child_id}"', out)
        self.assertIn(f'data-subtodo="{child_id}"', out)

    def test_web_dump_html_no_selector_shows_search_page(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        alpha = self.mint()
        beta = self.mint()
        self.write_ticket(f"{alpha[:8]}-a", alpha, summary="Alpha todo")
        self.write_ticket(f"{beta[:8]}-b", beta, summary="Beta todo")

        proc = self.todo("web", "--dump-html")  # no selector -> search landing page
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("search todos (vector search)", out)  # search box placeholder
        self.assertIn("Alpha todo", out)
        self.assertIn("Beta todo", out)
        self.assertIn(alpha, out)  # ids embedded for client-side links

    def test_web_dump_html_shows_parent_link(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Parent feature")
        self.assertEqual(init.returncode, 0, init.stderr)
        parent_id = json.loads(init.stdout)["Id"]
        add = self.todo("add-subtodo", "--summary=child one")
        self.assertEqual(add.returncode, 0, add.stderr)
        child_id = json.loads(self.todo("read", parent_id[:8]).stdout)["Subtodos"][0]["Id"]

        proc = self.todo("web", "--dump-html", child_id[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("<h2>Parent</h2>", out)
        self.assertIn(f'href="/?id={parent_id}"', out)  # parent link navigates to the parent todo

    def test_web_worktree_todo_collapses_to_repo(self) -> None:
        # A shared origin gives main checkout and worktree the same repo identity,
        # so a todo born in a worktree is discoverable from the main checkout.
        self._git("commit", "--allow-empty", "-qm", "seed")
        self._git("remote", "add", "origin", "git@github.com:jovlinger/utils.git")
        wt = Path(tempfile.mkdtemp(prefix="todo-wt-"))
        self.addCleanup(shutil.rmtree, wt, ignore_errors=True)
        self._git("worktree", "add", "-q", str(wt), "-b", "wt-branch")

        init = self.todo("init", "--summary=born in worktree", cwd=wt)
        self.assertEqual(init.returncode, 0, init.stderr)
        tid = json.loads(init.stdout)["Id"]

        proc = self.todo("web", "--dump-html")  # search page, scoped to the MAIN checkout
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("born in worktree", proc.stdout)
        self.assertIn(tid, proc.stdout)


class ReadFormattingUnitTests(unittest.TestCase):
    """Pure-function tests for read's field ordering and vector elision."""

    def test_order_ticket_fields_first_and_last(self) -> None:
        ticket = {
            "WorkItems": [], "State": {}, "Body": {"raw": "b"}, "Id": "x",
            "Subtodos": [], "Summary": {"raw": "s"}, "AC": "", "Scope": {},
        }
        keys = list(todo.order_ticket_fields(ticket).keys())
        self.assertEqual(keys[:3], ["Id", "Summary", "Body"])
        self.assertEqual(keys[-2:], ["Subtodos", "WorkItems"])
        self.assertEqual(keys[3:-2], ["AC", "Scope", "State"])  # middle stays sorted

    def test_order_ticket_fields_puts_raw_first_in_summary(self) -> None:
        ordered = todo.order_ticket_fields({"Id": "x", "Summary": {"hash": [1, 2, 3], "raw": "s"}})
        self.assertEqual(list(ordered["Summary"].keys()), ["raw", "hash"])

    def test_elide_shortens_numeric_vectors(self) -> None:
        self.assertEqual(todo.elide_embedding_vectors([0.1, 0.2, 0.3, 0.9]), [0.1, 0.2])

    def test_elide_leaves_short_and_non_numeric_lists(self) -> None:
        self.assertEqual(todo.elide_embedding_vectors([1, 2]), [1, 2])
        self.assertEqual(todo.elide_embedding_vectors(["a", "b", "c"]), ["a", "b", "c"])
        self.assertEqual(todo.elide_embedding_vectors([True, False, True]), [True, False, True])

    def test_elide_recurses_into_nested_dicts(self) -> None:
        self.assertEqual(
            todo.elide_embedding_vectors({"Summary": {"raw": "s", "hash": [1, 2, 3, 4]}}),
            {"Summary": {"raw": "s", "hash": [1, 2]}},
        )


class RepoIdentityUnitTests(unittest.TestCase):
    """Pure-function tests for the stable repo identity derivation."""

    def test_url_shapes_canonicalize_to_same_identity(self) -> None:
        want = "github.com/jovlinger/utils"
        self.assertEqual(todo.repo_identity_from_url("https://github.com/jovlinger/utils.git"), want)
        self.assertEqual(todo.repo_identity_from_url("https://github.com/jovlinger/utils"), want)
        self.assertEqual(todo.repo_identity_from_url("git@github.com:jovlinger/utils.git"), want)
        self.assertEqual(todo.repo_identity_from_url("ssh://git@github.com/jovlinger/utils.git"), want)

    def test_host_is_lowercased_and_owner_preserved(self) -> None:
        self.assertEqual(
            todo.repo_identity_from_url("git@GitHub.com:easternlabs/opportunity.git"),
            "github.com/easternlabs/opportunity",
        )

    def test_unidentifiable_urls_return_none(self) -> None:
        self.assertIsNone(todo.repo_identity_from_url(""))
        self.assertIsNone(todo.repo_identity_from_url("   "))
        self.assertIsNone(todo.repo_identity_from_url("not a url"))


class JsonPathUnitTests(unittest.TestCase):
    """Unit tests for get_at_path / set_at_path error detail."""

    def test_get_at_path_missing_nested_field(self) -> None:
        root: Dict[str, Any] = {"Summary": {"raw": "hi", "hash": []}}
        with self.assertRaises(todo.TodoError) as ctx:
            todo.get_at_path(root, "Summary.bogus")
        msg = str(ctx.exception)
        self.assertEqual(
            msg,
            "path Summary no such field bogus. available: hash,raw",
        )

    def test_get_at_path_missing_root_field(self) -> None:
        root: Dict[str, Any] = {"Id": "abc", "State": {"init": {}}}
        with self.assertRaises(todo.TodoError) as ctx:
            todo.get_at_path(root, "Nope")
        msg = str(ctx.exception)
        self.assertTrue(msg.startswith("path <root> no such field Nope. available:"))
        self.assertIn("Id", msg)
        self.assertIn("State", msg)

    def test_get_at_path_list_index_oob(self) -> None:
        root: Dict[str, Any] = {"WorkItems": [{"summary": "a"}, {"summary": "b"}]}
        with self.assertRaises(todo.TodoError) as ctx:
            todo.get_at_path(root, "WorkItems.9.summary")
        self.assertEqual(
            str(ctx.exception),
            "path WorkItems no such field 9. available: 0,1",
        )

    def test_set_at_path_list_index_oob(self) -> None:
        root: Dict[str, Any] = {"WorkItems": [{"summary": "a"}]}
        with self.assertRaises(todo.TodoError) as ctx:
            todo.set_at_path(root, "WorkItems.3.summary", "x")
        self.assertEqual(
            str(ctx.exception),
            "path WorkItems no such field 3. available: 0",
        )


class SetJsonPathTests(TodoCase):
    def _stdin(self, args: list[str], text: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TODO_PY), *args],
            cwd=str(self.repo), input=text, capture_output=True, text=True,
            check=False, env=self._env,
        )

    def test_set_json_path_from_stdin_replaces_work_items(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-sjp", tid)
        plan = [{"kind": "task", "summary": "a", "done": False}]
        proc = self._stdin(["set-json-path", "self", "WorkItems"], json.dumps(plan))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_self()["WorkItems"], plan)

    def test_set_json_path_from_file(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-sjp", tid)
        value_file = self._db_dir / "val.json"  # outside the repo -> tree stays clean
        value_file.write_text('"patched body"', encoding="utf-8")
        proc = self.todo("set-json-path", "self", "Body.raw", "--file", str(value_file))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_self()["Body"]["raw"], "patched body")

    def test_set_json_path_invalid_json_exits_1(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-sjp", tid)
        proc = self._stdin(["set-json-path", "self", "Body.raw"], "not json {")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not valid JSON", proc.stderr)

    def test_set_no_longer_accepts_work_items_file(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-sjp", tid)
        proc = self.todo("set", "--work-items-file", "plan.json")
        self.assertNotEqual(proc.returncode, 0)


class WorkItemModelUnitTests(unittest.TestCase):
    """Pure-function tests for the WorkItem cursor and invariant helpers."""

    def test_cursor_and_is_done(self) -> None:
        t = {"WorkItems": [{"kind": "code", "done": True, "sha": "a"}, {"kind": "task", "done": False}]}
        self.assertEqual(todo.cursor_index(t), 1)
        self.assertFalse(todo.is_done(t))
        done_todo = {"WorkItems": [{"kind": "code", "done": True, "sha": "a"}]}
        self.assertIsNone(todo.cursor_index(done_todo))
        self.assertTrue(todo.is_done(done_todo))
        self.assertTrue(todo.is_done({"WorkItems": []}))

    def test_next_action_finish_when_done(self) -> None:
        done_todo = {"WorkItems": [{"kind": "code", "done": True, "sha": "a"}]}
        nxt = todo.next_action(done_todo)
        self.assertEqual(nxt["action"], "finish")
        self.assertIn("set --state done", nxt["command"])
        self.assertIn("actual-summary", nxt["command"])

    def test_next_action_defaults_plain_task_to_work_item_done(self) -> None:
        t = {"WorkItems": [{"kind": "task", "summary": "do X", "done": False}]}
        self.assertEqual(todo.next_action(t)["action"], "work-item-done")

    def test_next_action_follows_execution_primitive(self) -> None:
        add = {"WorkItems": [{"done": False, "execution": {"primitive": "add-subtodo"}}]}
        self.assertEqual(todo.next_action(add)["action"], "add-subtodo")
        barrier = {
            "WorkItems": [
                {"done": False, "execution": {"mode": "barrier", "wait_for": ["abcd1234", "ef567890"]}}
            ]
        }
        nxt = todo.next_action(barrier)
        self.assertEqual(nxt["action"], "wait-and-merge")
        self.assertIn("abcd1234", nxt["command"])

    def test_last_sha(self) -> None:
        self.assertEqual(todo.last_sha({"WorkItems": [{"sha": "deadbeef"}]}), "deadbeef")
        self.assertIsNone(todo.last_sha({"WorkItems": [{"kind": "task", "done": False}]}))
        self.assertIsNone(todo.last_sha({"WorkItems": []}))

    def test_mark_cursor_done_converts_and_carries_summary(self) -> None:
        t = {"WorkItems": [{"kind": "task", "summary": "do X", "done": False}]}
        self.assertEqual(todo.mark_cursor_done(t, todo.code_workitem("sha1")), 0)
        self.assertEqual(
            t["WorkItems"][0], {"kind": "code", "summary": "do X", "sha": "sha1", "done": True}
        )

    def test_mark_cursor_done_appends_when_no_open_item(self) -> None:
        t = {"WorkItems": [{"kind": "code", "done": True, "sha": "a"}]}
        self.assertEqual(todo.mark_cursor_done(t, todo.merge_subtodo_workitem("sub", "s2", "m")), 1)
        self.assertEqual(t["WorkItems"][1]["kind"], "merge_subtodo")

    def test_workitem_findings_catch_invariant_violations(self) -> None:
        after_open = {"WorkItems": [{"kind": "task", "done": False}, {"kind": "code", "done": True, "sha": "a"}]}
        self.assertTrue(any("follows a not-done" in f for f in todo.workitem_findings(after_open)))
        last_start = {"WorkItems": [{"kind": "start_subtodo", "done": True, "subtodo_id": "x"}]}
        self.assertTrue(any("start_subtodo" in f for f in todo.workitem_findings(last_start)))
        no_sha = {"WorkItems": [{"kind": "code", "done": True}]}
        self.assertTrue(any("missing a sha" in f for f in todo.workitem_findings(no_sha)))
        well_formed = {
            "WorkItems": [
                {"kind": "start_subtodo", "done": True, "subtodo_id": "x"},
                {"kind": "code", "done": True, "sha": "a"},
            ]
        }
        self.assertEqual(todo.workitem_findings(well_formed), [])


class BacklinkUnitTests(unittest.TestCase):
    """Pure-function tests for INFO back-link helpers."""

    def _child(self) -> Dict[str, Any]:
        return {"Id": "c" * 64, "Branch": "cccccccc-child", "Summary": {"raw": "do it"}}

    def test_info_backlink_entry_is_marked_info(self) -> None:
        entry = todo.info_backlink_entry(self._child())
        self.assertEqual(entry["State"], "INFO")
        self.assertEqual(entry["Summary"], "do it")
        self.assertEqual(entry["Id"], "c" * 64)

    def test_upsert_appends_then_refreshes_but_keeps_real_entry(self) -> None:
        parent: Dict[str, Any] = {"Subtodos": []}
        self.assertTrue(todo.upsert_info_backlink(parent, self._child()))
        self.assertEqual(parent["Subtodos"][0]["State"], "INFO")
        # idempotent: same child, no change
        self.assertFalse(todo.upsert_info_backlink(parent, self._child()))
        # refreshes the best-effort summary on an existing INFO entry
        moved = {"Id": "c" * 64, "Branch": "new-branch", "Summary": {"raw": "renamed"}}
        self.assertTrue(todo.upsert_info_backlink(parent, moved))
        self.assertEqual(parent["Subtodos"][0]["Summary"], "renamed")
        # never downgrades a real tracked subtodo entry to INFO
        real: Dict[str, Any] = {"Subtodos": [{"Id": "c" * 64, "State": "working", "Summary": "x"}]}
        self.assertFalse(todo.upsert_info_backlink(real, self._child()))
        self.assertEqual(real["Subtodos"][0]["State"], "working")

    def test_remove_info_backlink_only_drops_info(self) -> None:
        parent: Dict[str, Any] = {
            "Subtodos": [
                {"Id": "c" * 64, "State": "INFO", "Summary": "x"},
                {"Id": "d" * 64, "State": "working", "Summary": "y"},
            ]
        }
        self.assertTrue(todo.remove_info_backlink(parent, "c" * 64))
        self.assertEqual(len(parent["Subtodos"]), 1)
        self.assertEqual(parent["Subtodos"][0]["Id"], "d" * 64)
        # tracked entry for the same id is left alone
        tracked: Dict[str, Any] = {
            "Subtodos": [{"Id": "c" * 64, "State": "working", "Summary": "x"}]
        }
        self.assertFalse(todo.remove_info_backlink(tracked, "c" * 64))
        self.assertEqual(tracked["Subtodos"][0]["State"], "working")

    def test_unmerged_subtodos_skips_info(self) -> None:
        parent = {"Subtodos": [{"Id": "a" * 64, "State": "INFO"}, {"Id": "b" * 64, "State": "working"}]}
        labels = todo.unmerged_subtodos(parent)
        self.assertEqual(len(labels), 1)
        self.assertIn("b" * 8, labels[0])


class MissingRepoCwdTests(unittest.TestCase):
    """git calls against an absent/foreign cwd must fail cleanly, not crash."""

    MISSING = Path("/no/such/repo/todo-missing-cwd")

    def test_run_git_reports_failure_for_missing_repo(self) -> None:
        result = todo.run_git(self.MISSING, "status", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_run_git_raises_todoerror_when_checked(self) -> None:
        with self.assertRaises(todo.TodoError):
            todo.run_git(self.MISSING, "status")

    def test_read_todo_at_ref_returns_none_for_missing_repo(self) -> None:
        # Force legacy (git-only) mode so this exercises the git-show path (the
        # reported crash) without opening the default sqlite db, which would
        # cache global todo-dir resolution and leak into other test modules.
        with unittest.mock.patch.dict(os.environ, {"TODO_USE_JSON": "1"}):
            self.assertIsNone(todo.read_todo_at_ref(self.MISSING, "some-branch"))

    def test_branch_exists_false_for_missing_repo(self) -> None:
        self.assertFalse(todo.branch_exists(self.MISSING, "main"))


class WorkItemInvariantTests(TodoCase):
    """CLI-level tests for the typed WorkItem invariants, cursor, and properties."""

    def _init(self, summary: str = "Effort") -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("init", f"--summary={summary}")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def test_init_captures_base_sha(self) -> None:
        self._init()
        self.assertRegex(self.read_self()["BaseSha"], r"\A[0-9a-f]{40}\Z")

    def test_code_workitem_dirty_commits_with_message(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=code it")
        (self.repo / "f.txt").write_text("x\n", encoding="utf-8")
        proc = self.todo("work-item-done", "-m", "feat: f")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        item = self.read_self()["WorkItems"][0]
        self.assertEqual(item["kind"], "code")
        self.assertTrue(item["done"])
        self.assertEqual(item["sha"], self._head())
        self.assertEqual(self._git("log", "-1", "--format=%s").stdout.strip(), "feat: f")

    def test_code_workitem_dirty_no_message_commits_with_summary(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=code it")
        (self.repo / "f.txt").write_text("x\n", encoding="utf-8")
        proc = self.todo("work-item-done")  # dirty, no -m: auto-commit
        self.assertEqual(proc.returncode, 0, proc.stderr)
        item = self.read_self()["WorkItems"][0]
        self.assertTrue(item["done"])
        self.assertEqual(item["sha"], self._head())
        # post-condition: branch is fully committed
        self.assertEqual(self._git("status", "--porcelain").stdout.strip(), "")
        self.assertEqual(self._git("log", "-1", "--format=%s").stdout.strip(), "code it")

    def test_code_workitem_clean_sha_mismatch_exits_1(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=code it")
        proc = self.todo("work-item-done", "--sha", "0" * 40)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not match HEAD", proc.stderr)
        ok = self.todo("work-item-done", "--sha", self._head())
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.read_self()["WorkItems"][0]["sha"], self._head())

    def test_cursor_insert_replace_delete_read(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=A")
        self.todo("work-item-insert", "--summary=B")  # B lands at the cursor, pushes A down
        self.assertEqual([w["summary"] for w in self.read_self()["WorkItems"]], ["B", "A"])
        read = json.loads(self.todo("work-item-read").stdout)
        self.assertEqual(read["index"], 0)
        self.assertEqual(read["item"]["summary"], "B")
        self.assertEqual(read["next"]["action"], "work-item-done")  # open plain task
        self.todo("work-item-replace", "--summary=B2")
        self.assertEqual(self.read_self()["WorkItems"][0]["summary"], "B2")
        self.todo("work-item-delete")
        self.assertEqual([w["summary"] for w in self.read_self()["WorkItems"]], ["A"])

    def test_is_done_and_last_sha_subcommands(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=code it")
        self.assertEqual(self.todo("is-done").returncode, 1)  # open item
        self.assertEqual(self.todo("work-item-done").returncode, 0)  # clean tree -> HEAD
        self.assertEqual(self.todo("is-done").returncode, 0)
        self.assertEqual(self.todo("last-sha").stdout.strip(), self._head())

    def test_add_subtodo_records_start_subtodo_item(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=fire A")
        proc = self.todo("add-subtodo", "--summary=child A")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        item = self.read_self()["WorkItems"][0]
        self.assertEqual(item["kind"], "start_subtodo")
        self.assertTrue(item.get("subtodo_id"))

    def test_doctor_flags_start_subtodo_as_last_item(self) -> None:
        self._init()
        self.todo("add-subtodo", "--summary=child A")  # only item: a done start_subtodo
        payload = json.loads(self.todo("doctor").stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("start_subtodo" in f for f in payload["findings"]))

    def test_doctor_warns_softly_for_unresolvable_base_sha(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=x")
        # inject a string sha that is absent from this repo
        subprocess.run(
            [sys.executable, str(TODO_PY), "set-json-path", "self", "BaseSha"],
            cwd=str(self.repo), input='"%s"' % ("deadbeef" * 5), capture_output=True,
            text=True, check=False, env=self._env,
        )
        payload = json.loads(self.todo("doctor").stdout)
        self.assertTrue(payload["ok"])  # soft: does not fail doctor
        self.assertTrue(any("BaseSha" in w for w in payload["warnings"]))


class BaseDirRepoDirTests(TodoCase):
    def test_basedir_prints_resolved_todo_dir(self) -> None:
        self.todo("init", "--summary=seed the db")  # ensure the db dir is materialized
        proc = self.todo("basedir")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path(proc.stdout.strip()), self._db_dir.resolve())

    def test_repodir_prints_ticket_repo(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        self.todo("init", "--summary=a todo")
        proc = self.todo("repodir", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path(proc.stdout.strip()).resolve(), self.repo.resolve())

    def test_repodir_unknown_id_errors(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("repodir", "deadbeef")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no todo found", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
