#!/usr/bin/env python3
"""The tag-prefix docker e2e stays off the fast suite."""

from __future__ import annotations

import os
import unittest


def _recipe(text: str, target: str) -> str:
    lines = text.splitlines()
    grab = False
    out: list[str] = []
    for line in lines:
        if grab:
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            out.append(line)
        elif line.startswith(target + ":"):
            grab = True
            out.append(line)
    return "\n".join(out)


class TestEnqueueDockerMakefile(unittest.TestCase):
    def test_docker_target_is_not_make_test(self) -> None:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "Makefile"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("test-enqueue-prefixes-docker:", text)
        self.assertIn("test-lounge-live-docker:", text)
        for target in ("test", "all-tests"):
            recipe = _recipe(text, target)
            self.assertNotIn("enqueue-prefixes", recipe)
            self.assertNotIn("lounge-live", recipe)
            self.assertNotIn("docker", recipe)


if __name__ == "__main__":
    unittest.main()
