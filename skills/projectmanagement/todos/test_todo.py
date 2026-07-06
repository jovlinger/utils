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
        self.assertEqual(first["summary"], "first item")
        self.assertTrue(first["done"])
        # work-item-done records the HEAD sha (the unit's code commit) on the item.
        self.assertEqual(len(first["commits"]), 1)
        self.assertRegex(first["commits"][0], r"\A[0-9a-f]{40}\Z")
        self.assertEqual(
            second, {"summary": "second item", "done": False, "commits": []}
        )


class UpdateTests(TodoCase):
    def test_update_jsonpath_on_other_branch(self) -> None:
        tid = self.mint()
        branch = f"{tid[:8]}-target"
        self.write_ticket(branch, tid, summary="target")
        self._git("checkout", "-q", "-b", "other-branch")
        self._git("commit", "--allow-empty", "-qm", "seed")
        proc = self.todo("update", tid[:8], "Body.raw", "patched body")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "patched body")
        self._git("checkout", branch)
        proc2 = self.todo("read", "self")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(json.loads(proc2.stdout)["Body"]["raw"], "patched body")

    def test_update_reads_stdin_when_value_is_dash(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-target", tid)
        proc = subprocess.run(
            [sys.executable, str(TODO_PY), "update", tid[:8], "Summary.raw", "-"],
            cwd=str(self.repo),
            input="from stdin\n",
            capture_output=True,
            text=True,
            check=False,
            env=self._env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "from stdin")
        proc2 = self.todo("read-path", "self", "Summary.raw")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(proc2.stdout.strip(), "from stdin")

    def test_read_path_prints_scalar_from_self(self) -> None:
        tid = self.mint()
        self.write_ticket("plain-current-branch", tid, summary="read me")
        proc = self.todo("read-path", "self", "Summary.raw")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "read me")

    def test_read_path_prints_json_values_as_json(self) -> None:
        tid = self.mint()
        self.write_ticket("state-branch", tid)
        proc = self.todo("read-path", "self", "State")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"init": {}})

    def test_set_path_updates_current_branch(self) -> None:
        tid = self.mint()
        self.write_ticket("path-current-branch", tid)
        proc = self.todo("set-path", "self", "Body.raw", "patched body")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "patched body")
        proc2 = self.todo("read-path", "self", "Body.raw")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(proc2.stdout.strip(), "patched body")

    def test_set_path_accepts_json_null(self) -> None:
        tid = self.mint()
        self.write_ticket("null-current-branch", tid)
        proc = self.todo("set-path", "self", "AC", "null")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "null")
        proc2 = self.todo("read-path", "self", "AC")
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
        proc2 = self.todo("read-path", "self", "State")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(
            json.loads(proc2.stdout),
            {"done": {"last_commit": "finish child"}},
        )

        proc3 = self.todo("set-state", "merged", "--merged-into=parent-branch")
        self.assertEqual(proc3.returncode, 0, proc3.stderr)
        proc4 = self.todo("read-path", "self", "State")
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
        child_proc = self.todo("read-path", "self", "State")
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
        sha = ticket["WorkItems"][0]["commits"][0]

        proc = self.todo("web", "--dump-html", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Recorded work-item sha renders as a clickable commit link in the info pane.
        self.assertIn("commit=" + sha, proc.stdout)
        self.assertIn(sha[:8], proc.stdout)
        # Every todo Id is a re-root link (openable as a new top-level timeline).
        self.assertIn("/?root=" + ticket["Id"], proc.stdout)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
