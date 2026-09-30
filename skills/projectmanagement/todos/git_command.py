"""The one place this tool shells out to git, so a test can replace it wholesale.

Every git invocation goes through the ``Git`` returned by :func:`get_git`.
``RealGit`` runs the binary and is what the CLI uses. ``FakeGit`` answers from a
table of registered responses and records what was asked, so a test can drive
the tool with no repository and no subprocess: a real git call costs about 11 ms,
a ``FakeGit`` call costs microseconds, and one CLI command makes about seven of
them.

Install a fake for the duration of a test with ``set_git(FakeGit())`` and drop it
with ``reset_git()``, the same shape ``todo_store.get_store`` / ``reset_store``
already use for the ticket store.

``run`` is deliberately policy-free: it never raises on a non-zero exit and it
turns an OSError into a failed ``CompletedProcess``, because each caller has its
own idea of what a git failure means -- ``repo_root`` raises ``TodoError``,
``git_fetch_if_remote`` shrugs, ``head_sha`` returns None.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

CompletedGit = subprocess.CompletedProcess


class Git(ABC):
    """A git command runner."""

    @abstractmethod
    def run(
        self,
        root: Optional[Path],
        *args: str,
        env: Optional[Mapping[str, str]] = None,
        check: bool = False,
    ) -> CompletedGit:
        """Run ``git *args`` with *root* as the working directory.

        By default never raises for a git-level failure: a non-zero exit, a
        missing binary and an unreachable *root* all come back as a
        ``CompletedProcess`` whose ``returncode`` is non-zero. ``check=True``
        raises ``CalledProcessError`` on a non-zero exit, as ``subprocess.run``
        does.
        """

    @staticmethod
    def _checked(result: CompletedGit, check: bool) -> CompletedGit:
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )
        return result


class RealGit(Git):
    """Runs the real git binary. The CLI's implementation."""

    def run(
        self,
        root: Optional[Path],
        *args: str,
        env: Optional[Mapping[str, str]] = None,
        check: bool = False,
    ) -> CompletedGit:
        argv: List[str] = ["git", *args]
        try:
            result = subprocess.run(
                argv,
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=dict(env) if env is not None else None,
            )
        except OSError as exc:
            # *root* may be an unreachable working directory, or git may be
            # missing; either is a normal git failure to every caller here.
            result = CompletedGit(argv, returncode=1, stdout="", stderr=str(exc))
        return self._checked(result, check)


class UnexpectedGitCall(AssertionError):
    """A strict FakeGit was asked something no test registered."""


class FakeGit(Git):
    """Answers git from a registered table and records every call.

    Responses are matched on an argument PREFIX, longest first, so a test can
    stub ``("rev-parse",)`` once and not care about the flags that follow. This
    is the difference that makes it usable where an exact ``cmd + args`` match is
    not: the tool embeds per-test temp paths and shas in its git arguments.

    An unregistered call returns a failed ``CompletedProcess``, which every
    caller already handles as "git said no". Pass ``strict=True`` to raise
    :class:`UnexpectedGitCall` instead, for a test that means to pin down
    exactly which git commands a path issues.
    """

    def __init__(self, *, strict: bool = False) -> None:
        self._responses: List[Tuple[Tuple[str, ...], CompletedGit]] = []
        self.calls: List[Tuple[Optional[Path], Tuple[str, ...]]] = []
        self.strict = strict

    def expect(
        self,
        *args: str,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> "FakeGit":
        """Register a response for any call whose arguments start with *args*.

        Re-registering the same prefix replaces the earlier answer, so a harness
        can restate a changing fact (the current branch, say) mid-test.
        """
        prefix = tuple(args)
        self._responses = [pair for pair in self._responses if pair[0] != prefix]
        self._responses.append(
            (prefix, CompletedGit(["git", *args], returncode, stdout, stderr))
        )
        # Longest prefix wins, so a specific stub beats a general one whatever
        # order the test registered them in.
        self._responses.sort(key=lambda pair: len(pair[0]), reverse=True)
        return self

    def run(
        self,
        root: Optional[Path],
        *args: str,
        env: Optional[Mapping[str, str]] = None,
        check: bool = False,
    ) -> CompletedGit:
        self.calls.append((root, tuple(args)))
        for prefix, response in self._responses:
            if args[: len(prefix)] == prefix:
                return self._checked(
                    CompletedGit(
                        ["git", *args],
                        response.returncode,
                        response.stdout,
                        response.stderr,
                    ),
                    check,
                )
        if self.strict:
            raise UnexpectedGitCall(f"no FakeGit response for: git {' '.join(args)}")
        return self._checked(
            CompletedGit(["git", *args], returncode=1, stdout="", stderr=""), check
        )

    def commands(self) -> List[str]:
        """The recorded calls as ``git ...`` strings, in order, for assertions."""
        return [" ".join(("git", *args)) for _, args in self.calls]


_GIT: Optional[Git] = None


def get_git() -> Git:
    """The process-wide git runner, defaulting to the real binary."""
    global _GIT
    if _GIT is None:
        _GIT = RealGit()
    return _GIT


def set_git(git: Git) -> None:
    """Install *git* as the runner every call site will use."""
    global _GIT
    _GIT = git


def reset_git() -> None:
    """Drop any installed runner, so the next call goes back to RealGit."""
    global _GIT
    _GIT = None
