"""Frozen AC for 8bf724f7: the `ALL` positional-selector sentinel replacing --all.

FROZEN by the orchestrator; the implementor MUST NOT modify this file (it is the
read-only oracle). Skipped until the implementation WorkItem enables it.

Contract:
  * `doctor ALL` audits the whole corpus (the multi-todo shape carrying
    ``audited``), replacing the removed `doctor --all`.
  * `log ALL` renders every root (a forest), replacing `log --all`.
  * The `--all` flag is GONE from both: `doctor --all` / `log --all` are
    rejected by argparse (exit 2, "unrecognized arguments").
  * `ls` / `search` are unchanged -- they take no selector (inherent all).
  * `ALL` is uppercase, matching the `--states=ALL` macro convention.
"""

from __future__ import annotations

import json
import unittest

from test_todo import TodoCase


class AllSentinelEndTest(TodoCase):
    def _seed_two(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        self.write_ticket(
            "aaaaaaaa-alpha", "a" * 64, summary="Alpha ticket",
            extra={"State": {"ready": {}}},
        )
        self.write_ticket(
            "bbbbbbbb-beta", "b" * 64, summary="Beta ticket",
            extra={"State": {"ready": {}}},
        )

    def test_doctor_ALL_audits_whole_corpus(self) -> None:
        self._seed_two()
        proc = self.todo("doctor", "ALL")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertGreaterEqual(payload["audited"], 2)
        self.assertTrue(payload["ok"])

    def test_log_ALL_shows_every_root(self) -> None:
        self._seed_two()
        proc = self.todo("log", "ALL")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Alpha ticket", proc.stdout)
        self.assertIn("Beta ticket", proc.stdout)

    def test_old_all_flag_is_rejected(self) -> None:
        self._git("commit", "--allow-empty", "-qm", "seed")
        for argv in (("doctor", "--all"), ("log", "--all")):
            proc = self.todo(*argv)
            self.assertEqual(proc.returncode, 2, f"{argv}: {proc.stdout}{proc.stderr}")
            err = (proc.stderr + proc.stdout).lower()
            # argparse rejects --all: as an unknown flag, or (now that the
            # selector is a required positional) as the missing selector.
            self.assertTrue(
                "unrecognized arguments" in err or "required: selector" in err, err
            )

    def test_ls_still_takes_no_selector(self) -> None:
        self._seed_two()
        proc = self.todo("ls")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Alpha ticket", proc.stdout)


if __name__ == "__main__":
    unittest.main()
