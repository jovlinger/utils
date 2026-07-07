#!/usr/bin/env python3
"""Unit tests for the Apple embedder sidecar manager.

These exercise the Python side (lazy start, handshake, fingerprint, error and
crash handling, registry wiring) against a fake sidecar that speaks the same
JSON-lines protocol as the real Swift binary. No Swift or macOS is required, so
the suite runs on CI/Linux too.
"""

from __future__ import annotations

import math
import os
import stat
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import todo_embed
from todo_embed_apple import AppleEmbedder, AppleEmbedderError

# A stand-in for apple_embedder/nlce-embed. Behavior switches on $FAKE_MODE:
#   normal (default) -- info + deterministic normalized embed vectors
#   error            -- info ok, every embed replies {"error": ...}
#   crash            -- info ok, the very first embed (tracked in $FAKE_CRASH_MARKER)
#                       exits without a reply to force one respawn; later embeds work
_FAKE = '''#!/usr/bin/env python3
import hashlib, json, math, os, struct, sys

DIM = 4

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

def vector_for(text):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vals = list(struct.unpack("<4f", digest[:16]))
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]

mode = os.environ.get("FAKE_MODE", "normal")
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    op = req.get("op")
    if op == "info":
        emit({"model": "test-en", "revision": 3, "dim": DIM})
    elif op == "embed":
        if mode == "error":
            emit({"error": "boom"})
        elif mode == "crash":
            marker = os.environ.get("FAKE_CRASH_MARKER", "")
            n = 0
            if marker and os.path.exists(marker):
                with open(marker) as f:
                    n = int(f.read() or "0")
            if n == 0:
                if marker:
                    with open(marker, "w") as f:
                        f.write("1")
                sys.exit(1)
            emit({"vector": vector_for(req.get("text", ""))})
        else:
            emit({"vector": vector_for(req.get("text", ""))})
    else:
        emit({"error": "unknown op"})
'''


class AppleEmbedderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix="nlce-fake-")
        self._bin = os.path.join(self._dir, "fake-nlce")
        Path(self._bin).write_text(_FAKE, encoding="utf-8")
        os.chmod(self._bin, os.stat(self._bin).st_mode | stat.S_IEXEC | stat.S_IXGRP)
        self._embedders: list[AppleEmbedder] = []

    def tearDown(self) -> None:
        for emb in self._embedders:
            emb.close()

    def _make(self) -> AppleEmbedder:
        emb = AppleEmbedder(bin_path=self._bin)
        self._embedders.append(emb)
        return emb

    def test_lazy_start(self) -> None:
        emb = self._make()
        self.assertIsNone(emb._proc)  # constructing must not spawn
        vec = emb.embed("hello world")
        self.assertIsNotNone(emb._proc)  # first embed spawns
        self.assertEqual(len(vec), 4)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in vec)), 1.0, places=5)

    def test_fingerprint_and_dimension(self) -> None:
        emb = self._make()
        self.assertEqual(
            emb.fingerprint(), "apple_nlce:test-en:r3:pool=mean:norm=l2:v1"
        )
        self.assertEqual(emb.dimension(), 4)

    def test_embed_deterministic(self) -> None:
        emb = self._make()
        self.assertEqual(emb.embed("same text"), emb.embed("same text"))

    def test_error_reply_raises(self) -> None:
        emb = self._make()
        with unittest.mock.patch.dict(os.environ, {"FAKE_MODE": "error"}):
            with self.assertRaises(AppleEmbedderError):
                emb.embed("anything")

    def test_close_then_restart(self) -> None:
        emb = self._make()
        emb.embed("first")
        emb.close()
        self.assertFalse(emb._alive())
        # A later embed transparently restarts the sidecar.
        self.assertEqual(len(emb.embed("second")), 4)
        self.assertTrue(emb._alive())

    def test_respawn_on_crash(self) -> None:
        marker = os.path.join(self._dir, "crash-marker")
        env = {"FAKE_MODE": "crash", "FAKE_CRASH_MARKER": marker}
        with unittest.mock.patch.dict(os.environ, env):
            emb = self._make()
            vec = emb.embed("survives one crash")
        self.assertEqual(len(vec), 4)
        self.assertEqual(Path(marker).read_text(), "1")  # a crash did occur

    def test_missing_binary_raises(self) -> None:
        with self.assertRaises(AppleEmbedderError):
            AppleEmbedder(bin_path=os.path.join(self._dir, "does-not-exist"))

    def test_registry_lists_and_builds_apple(self) -> None:
        # apple is a non-hidden default embedder; TODO_APPLE_NLCE_BIN points the
        # backend at the fake sidecar so this runs off-macOS too.
        self.assertIn("apple", todo_embed.available_embedders())
        with unittest.mock.patch.dict(os.environ, {"TODO_APPLE_NLCE_BIN": self._bin}):
            emb = todo_embed.get_embedder("apple")
            self.addCleanup(emb.close)  # type: ignore[attr-defined]
            self.assertEqual(len(emb.embed("via registry")), 4)


if __name__ == "__main__":
    unittest.main()
