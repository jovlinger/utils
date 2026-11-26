#!/usr/bin/env python3
"""Protocol guard: deploy must not claim success on getState alone.

Docker prove covers Walk.cxx. SHD deploy previously stopped at getState=200
while Volumio browse hung on a stale MpdClient after MPD restart. This test
locks the required verify steps into the shell scripts so a future edit that
drops them fails make test locally (and in CI), without needing the SHD.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEPLOY = (ROOT / "scripts" / "deploy-dontwalk-shd.sh").read_text(encoding="ascii")
VERIFY = (ROOT / "scripts" / "verify-dontwalk-shd.sh").read_text(encoding="ascii")


class DeployVerifyProtocolTest(unittest.TestCase):
    def test_deploy_invokes_verify_script(self) -> None:
        self.assertIn("verify-dontwalk-shd.sh", DEPLOY)
        # Must not treat curl getState as the sole post-install gate.
        tail = DEPLOY.split("systemctl start mpd")[-1]
        self.assertIn("verify-dontwalk-shd.sh", tail)

    def test_verify_restarts_volumio_and_checks_browse(self) -> None:
        self.assertIn("systemctl restart volumio", VERIFY)
        self.assertIn("api/v1/browse", VERIFY)
        self.assertIn("music-library/NAS/gmk/files/_tags", VERIFY)
        self.assertIn("PROOF_OK", VERIFY)
        self.assertIn("NAS/gmk/files", VERIFY)
        # Must poll browse, not only getState (getState can 200 first).
        self.assertIn("browse never ready", VERIFY)
        self.assertIn("browse_files=", VERIFY)


if __name__ == "__main__":
    unittest.main()
