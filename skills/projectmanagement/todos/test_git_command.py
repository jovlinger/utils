"""The git seam: FakeGit's matching and recording, RealGit's failure handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CalledProcessError

import pytest

import git_command


class FakeGitTest(unittest.TestCase):
    """FakeGit answers from registered prefixes and records what was asked."""

    def test_longest_registered_prefix_wins(self) -> None:
        git = git_command.FakeGit()
        git.expect("rev-parse", stdout="general\n")
        git.expect("rev-parse", "--show-toplevel", stdout="specific\n")
        self.assertEqual("specific\n", git.run(None, "rev-parse", "--show-toplevel").stdout)
        self.assertEqual("general\n", git.run(None, "rev-parse", "HEAD").stdout)

    def test_registration_order_does_not_decide_the_match(self) -> None:
        git = git_command.FakeGit()
        git.expect("rev-parse", "--show-toplevel", stdout="specific\n")
        git.expect("rev-parse", stdout="general\n")
        self.assertEqual("specific\n", git.run(None, "rev-parse", "--show-toplevel").stdout)

    def test_a_prefix_stub_covers_trailing_arguments_it_never_named(self) -> None:
        """Why prefixes: the tool puts per-test temp paths and shas in its arguments."""
        git = git_command.FakeGit()
        git.expect("show", stdout="{}\n")
        result = git.run(None, "show", "deadbeef0123:TODO.json")
        self.assertEqual("{}\n", result.stdout)

    def test_unregistered_call_fails_rather_than_inventing_output(self) -> None:
        git = git_command.FakeGit()
        result = git.run(None, "status")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_strict_mode_raises_on_an_unregistered_call(self) -> None:
        git = git_command.FakeGit(strict=True)
        with self.assertRaises(git_command.UnexpectedGitCall):
            git.run(None, "status")

    def test_check_raises_calledprocesserror_like_subprocess_does(self) -> None:
        git = git_command.FakeGit()
        git.expect("remote", returncode=2, stderr="boom")
        self.assertEqual(2, git.run(None, "remote").returncode)
        with self.assertRaises(CalledProcessError) as caught:
            git.run(None, "remote", check=True)
        self.assertEqual(2, caught.exception.returncode)

    def test_check_is_satisfied_by_a_zero_exit(self) -> None:
        git = git_command.FakeGit()
        git.expect("remote", stdout="origin\n")
        self.assertEqual("origin\n", git.run(None, "remote", check=True).stdout)

    def test_calls_are_recorded_in_order_with_their_root(self) -> None:
        git = git_command.FakeGit()
        git.expect("rev-parse", stdout="x\n")
        git.run(Path("/a"), "rev-parse", "HEAD")
        git.run(Path("/b"), "branch", "--show-current")
        self.assertEqual(
            ["git rev-parse HEAD", "git branch --show-current"], git.commands()
        )
        self.assertEqual([Path("/a"), Path("/b")], [root for root, _ in git.calls])

    def test_returned_args_name_the_actual_call_not_the_stub(self) -> None:
        git = git_command.FakeGit()
        git.expect("show", stdout="{}\n")
        self.assertEqual(
            ["git", "show", "abc:TODO.json"], git.run(None, "show", "abc:TODO.json").args
        )


class GitBackendSelectionTest(unittest.TestCase):
    """get_git / set_git / reset_git, the seam the CLI and the tests share."""

    def tearDown(self) -> None:
        git_command.reset_git()

    def test_default_backend_is_the_real_binary(self) -> None:
        git_command.reset_git()
        self.assertIsInstance(git_command.get_git(), git_command.RealGit)

    def test_default_backend_is_cached(self) -> None:
        git_command.reset_git()
        self.assertIs(git_command.get_git(), git_command.get_git())

    def test_set_git_replaces_the_backend_for_every_call_site(self) -> None:
        fake = git_command.FakeGit()
        git_command.set_git(fake)
        self.assertIs(fake, git_command.get_git())

    def test_reset_git_restores_the_real_binary(self) -> None:
        git_command.set_git(git_command.FakeGit())
        git_command.reset_git()
        self.assertIsInstance(git_command.get_git(), git_command.RealGit)


class RealGitTest(unittest.TestCase):
    """RealGit turns every git-level failure into a non-zero CompletedProcess."""

    pytestmark = pytest.mark.integration

    def test_reports_a_non_repository_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = git_command.RealGit().run(Path(d), "rev-parse", "--show-toplevel")
            self.assertNotEqual(0, result.returncode)

    def test_unreachable_root_is_a_failed_result_not_an_oserror(self) -> None:
        missing = Path(tempfile.gettempdir()) / "todo-git-command-absent"
        result = git_command.RealGit().run(missing, "rev-parse", "HEAD")
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(result.stderr)

    def test_check_raises_on_a_real_failure(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(CalledProcessError):
                git_command.RealGit().run(Path(d), "rev-parse", "HEAD", check=True)

    def test_succeeds_in_a_real_repository(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            git = git_command.RealGit()
            self.assertEqual(0, git.run(root, "init", "-q").returncode)
            result = git.run(root, "rev-parse", "--show-toplevel", check=True)
            self.assertEqual(Path(result.stdout.strip()).name, root.name)


if __name__ == "__main__":
    unittest.main()
