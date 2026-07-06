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
        # Embedding vector under Summary is elided to [first, last].
        self.assertEqual(len(elided["Summary"]["hash"]), 2)

        proc = self.todo("read", "self", "-v")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        full = json.loads(proc.stdout)
        self.assertGreater(len(full["Summary"]["hash"]), 2)

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
        proc = self.todo("chunk-add", "--summary=first item")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("work-item-add", "--summary=second item")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        proc3 = self.todo("chunk-done")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)

        ticket = self.read_self()
        work_items = ticket["WorkItems"]
        self.assertEqual(len(work_items), 2)
        first, second = work_items
        # chunk-done completes the cursor (first not-done) item as a typed code item.
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

    def test_jq_projects_ticket_through_binary(self) -> None:
        if shutil.which("jq") is None:
            self.skipTest("jq binary is not installed")
        tid = self.mint()
        self.write_ticket("jq-current-branch", tid, summary="jq summary")
        proc = self.todo("jq", "self", ".Summary.raw")
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
        proc = self.todo("set-state", "done", "--last-commit=finish child")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc2 = self.todo("get-json-path", "self", "State")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(
            json.loads(proc2.stdout),
            {"done": {"last_commit": "finish child"}},
        )

        proc3 = self.todo("set-state", "merged", "--merged-into=parent-branch")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)
        proc4 = self.todo("get-json-path", "self", "State")
        self.assertEqual(proc4.returncode, 0, proc4.stderr)
        self.assertEqual(
            json.loads(proc4.stdout),
            {"merged": {"merged_into": "parent-branch"}},
        )


class WaitTests(TodoCase):
    def test_wait_for_done_succeeds_immediately(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-done", tid)
        proc = self.todo("set-state", "done")
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
        proc2 = self.todo("set-state", "done")
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
        proc = self.todo("search", "oauth bearer token")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(oauth_id[:8], proc.stdout)
        self.assertNotIn(other_id[:8], proc.stdout)


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
    def test_web_dump_html_renders_done_todo_graph_and_diff(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        self._git("remote", "add", "origin", "git@github.com:jovlinger/utils.git")
        init = self.todo("init", "--summary=Viewer parent")
        self.assertEqual(init.returncode, 0, init.stderr)
        (self.repo / "app.txt").write_text("before\n", encoding="utf-8")
        self._git("add", "app.txt")
        self._git("commit", "-qm", "add app evidence")
        app_hash = self._git("rev-parse", "HEAD").stdout.strip()
        done = self.todo("set-state", "done")
        self.assertEqual(done.returncode, 0, done.stderr)

        proc = self.todo("web", "--dump-html", "--commit", app_hash, "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Viewer parent", proc.stdout)
        self.assertIn("add app evidence", proc.stdout)
        self.assertIn(app_hash, proc.stdout)
        self.assertIn(str(self.repo), proc.stdout)
        self.assertIn("+before", proc.stdout)
        self.assertIn("https://github.com/jovlinger/utils/commit/" + app_hash, proc.stdout)

    def test_web_dump_html_ignores_parent_todo_on_child_branch(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        parent_id = self.mint()
        child_id = self.mint()
        parent_branch = f"{parent_id[:8]}-parent"
        child_branch = f"{child_id[:8]}-child"
        self._git("checkout", "-q", "-b", parent_branch)
        parent = {
            "Id": parent_id,
            "Branch": parent_branch,
            "State": {"init": {}},
            "Summary": {"raw": "parent viewer"},
            "Subtodos": [
                {
                    "Id": child_id,
                    "Branch": child_branch,
                    "State": "init",
                    "Summary": "child viewer",
                }
            ],
        }
        (self.repo / "TODO.json").write_text(json.dumps(parent), encoding="utf-8")
        self._git("add", "TODO.json")
        self._git("commit", "-qm", "parent todo")

        # Child branch inherits parent TODO.json (common mistake); viewer must not loop.
        self._git("checkout", "-q", "-b", child_branch)

        proc = self.todo("web", "--dump-html", parent_id[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("parent viewer", proc.stdout)
        self.assertIn("child viewer", proc.stdout)
        # One root lane (parent) plus one subtodo lane (child), no deeper recursion.
        self.assertEqual(proc.stdout.count('class="lane-title"'), 2)

    def test_web_dump_html_renders_open_todo(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Open viewer")
        self.assertEqual(init.returncode, 0, init.stderr)
        proc = self.todo("web", "--dump-html", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Open viewer", proc.stdout)
        self.assertIn('class="lane root"', proc.stdout)
        self.assertIn("&middot; init</div>", proc.stdout)
        # No commit selected: the bottom pane shows the default "more info" view.
        self.assertIn("More info", proc.stdout)

    def test_web_dump_html_links_work_item_commits_and_reroot(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        init = self.todo("init", "--summary=Track commits")
        self.assertEqual(init.returncode, 0, init.stderr)
        add = self.todo("work-item-add", "--summary=do the thing")
        self.assertEqual(add.returncode, 0, add.stderr)
        done = self.todo("work-item-done")
        self.assertEqual(done.returncode, 0, done.stderr)

        ticket = self.read_self()
        sha = ticket["WorkItems"][0]["sha"]

        proc = self.todo("web", "--dump-html", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Recorded work-item sha renders as a clickable commit link in the info pane.
        self.assertIn("commit=" + sha, proc.stdout)
        self.assertIn(sha[:8], proc.stdout)
        # Every todo Id is a re-root link (openable as a new top-level timeline).
        self.assertIn("/?root=" + ticket["Id"], proc.stdout)


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
        self.assertEqual(todo.elide_embedding_vectors([0.1, 0.2, 0.3, 0.9]), [0.1, 0.9])

    def test_elide_leaves_short_and_non_numeric_lists(self) -> None:
        self.assertEqual(todo.elide_embedding_vectors([1, 2]), [1, 2])
        self.assertEqual(todo.elide_embedding_vectors(["a", "b", "c"]), ["a", "b", "c"])
        self.assertEqual(todo.elide_embedding_vectors([True, False, True]), [True, False, True])

    def test_elide_recurses_into_nested_dicts(self) -> None:
        self.assertEqual(
            todo.elide_embedding_vectors({"Summary": {"raw": "s", "hash": [1, 2, 3, 4]}}),
            {"Summary": {"raw": "s", "hash": [1, 4]}},
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


class MissingRepoCwdTests(unittest.TestCase):
    """A subtodo can record a repo path (Scope.path_to_project) from another
    machine that is absent here; git calls must not crash on the missing cwd."""

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

    def test_code_workitem_dirty_requires_message_and_commits(self) -> None:
        self._init()
        self.todo("work-item-add", "--summary=code it")
        (self.repo / "f.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(self.todo("work-item-done").returncode, 1)  # dirty, no -m
        proc = self.todo("work-item-done", "-m", "feat: f")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        item = self.read_self()["WorkItems"][0]
        self.assertEqual(item["kind"], "code")
        self.assertTrue(item["done"])
        self.assertEqual(item["sha"], self._head())

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
