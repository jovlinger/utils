from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List
from unittest import TestCase

# Subprocess timeout: if real `bwrap` runs (stub not first on PATH), avoid hanging forever.
_RUN_RAW_TIMEOUT_SEC: float = 30.0


def _trace(msg: str) -> None:
    if os.environ.get("DMZ_LAUNCHER_TEST_TRACE", "").strip() not in ("", "0", "false", "no"):
        print(f"[DMZ_LAUNCHER_TEST_TRACE] {msg}", flush=True)


class DMZDeploymentLauncherFormatTest(TestCase):
    def _find_subsequence(self, args: List[str], subseq: List[str]) -> int:
        """
        Return the first index where `subseq` occurs as a contiguous subsequence.
        """
        if not subseq:
            return 0
        for i in range(0, len(args) - len(subseq) + 1):
            if args[i : i + len(subseq)] == subseq:
                return i
        return -1

    def _run_raw_with_bwrap_stub(
        self,
        script_path: Path,
        rootfs_dir: Path,
        *,
        debug: bool,
    ) -> List[str]:
        """
        Execute `install/run_raw.sh` with a stub `bwrap` so we can inspect
        the exact command line passed into the bubblewrap sandbox.
        """

        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            stub_bin = tmpdir / "stubbin"
            stub_bin.mkdir(parents=True, exist_ok=True)
            captured_args_path = tmpdir / "captured_args.txt"

            bwrap_stub = stub_bin / "bwrap"
            bwrap_stub.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "set -eu",
                        ": \"${BWRAP_ARGS_FILE:?}\"",
                        "printf '%s\\n' \"$@\" > \"$BWRAP_ARGS_FILE\"",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            bwrap_stub.chmod(0o755)

            env = dict(os.environ)
            env["PATH"] = f"{stub_bin}:{env.get('PATH', '')}"
            env["BWRAP_ARGS_FILE"] = str(captured_args_path)
            # `thermo/dmz/install/run_raw.sh` only toggles debug mode based on the
            # `--debug` CLI argument (it overwrites any DEBUG env var).

            argv = [
                "/bin/sh",
                str(script_path),
                str(rootfs_dir),
                *(["--debug"] if debug else []),
            ]
            _trace(f"run_raw argv={argv!r}")
            _trace(f"PATH head (stub first): {env['PATH'][:200]!r}...")

            try:
                proc = subprocess.run(
                    argv,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=_RUN_RAW_TIMEOUT_SEC,
                )
            except subprocess.TimeoutExpired as e:
                self.fail(
                    f"run_raw.sh subprocess timed out after {_RUN_RAW_TIMEOUT_SEC}s "
                    f"(often means real bwrap ran instead of stub — check PATH). "
                    f"cmd={argv!r} stderr_so_far={getattr(e, 'stderr', None)!r}"
                )

            _trace(f"run_raw rc={proc.returncode} stderr={proc.stderr[:500]!r}")
            self.assertTrue(
                captured_args_path.exists(),
                msg=f"bwrap stub did not write args: {captured_args_path}",
            )

            lines = captured_args_path.read_text(encoding="utf-8").splitlines()
            _trace(f"captured {len(lines)} bwrap argv lines")
            return lines

    def test_run_raw_execs_run_with_stdout_logged_with_expected_arguments(self) -> None:
        dmz_dir = Path(__file__).resolve().parent.parent
        script_path = dmz_dir / "install" / "run_raw.sh"
        self.assertTrue(script_path.exists(), msg=f"Missing script: {script_path}")

        with tempfile.TemporaryDirectory() as rootfs_dir_str:
            rootfs_dir = Path(rootfs_dir_str)
            (rootfs_dir / "app").mkdir(parents=True, exist_ok=True)

            args = self._run_raw_with_bwrap_stub(
                script_path,
                rootfs_dir,
                debug=False,
            )

        # Validate the bubblewrap/tini/sh chain and delimiters:
        #   bwrap ... --chdir /app -- /sbin/tini -s -- sh -c '<...>'
        # In your failure log, the `--` most likely refers to these delimiters.
        expected_chain = ["--chdir", "/app", "--", "/sbin/tini", "-s", "--", "sh", "-c"]
        chain_idx = self._find_subsequence(args, expected_chain)
        self.assertNotEqual(
            chain_idx,
            -1,
            msg=f"Expected chain not found.\nExpected subseq:\n{expected_chain}\nActual args:\n{args}",
        )
        sh_c_command = args[chain_idx + len(expected_chain)]

        expected = (
            "exec python ./run-with-stdout-logged.py /tmp/dmz.log 1048576 2097152 "
            "sh ./run.sh"
        )
        self.assertIn(
            expected,
            sh_c_command,
            msg=f"Embedded command did not match.\nExpected substring:\n{expected}\nActual sh -c:\n{sh_c_command}",
        )

    def test_run_raw_debug_does_not_use_run_with_stdout_logged(self) -> None:
        dmz_dir = Path(__file__).resolve().parent.parent
        script_path = dmz_dir / "install" / "run_raw.sh"
        self.assertTrue(script_path.exists(), msg=f"Missing script: {script_path}")

        with tempfile.TemporaryDirectory() as rootfs_dir_str:
            rootfs_dir = Path(rootfs_dir_str)
            (rootfs_dir / "app").mkdir(parents=True, exist_ok=True)

            args = self._run_raw_with_bwrap_stub(
                script_path,
                rootfs_dir,
                debug=True,
            )

        joined = "\n".join(args)
        self.assertNotIn(
            "run-with-stdout-logged.py",
            joined,
            msg=f"DEBUG mode should not exec run-with-stdout-logged.py.\nArgs:\n{joined}",
        )

