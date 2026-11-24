#!/usr/bin/env python3
"""Patch-contract tests for apply_explode_tags_enqueue.py."""

from __future__ import annotations

import unittest

import apply_explode_tags_enqueue as patcher

STUB = """\
'use strict';
var mpdignoreUtil = require('./mpdignore.js');

ControllerMpd.prototype.explodeUri = function (uri) {
  } else {
    var uriPath = '/mnt/' + self.sanitizeUri(uri);
    // self.commandRouter.logger.info('----------------------------'+uriPath);
    var uris = self.scanFolder(uriPath);
    var response = [];

    libQ.all(uris)
  }
};
"""


class ApplyExplodeTagsEnqueueTest(unittest.TestCase):
    def test_patch_rewrites_tag_folder_roots(self) -> None:
        out = patcher.patch(STUB)
        self.assertIn("tagEnqueuePrefixes", out)
        self.assertIn("enqueueRoots", out)
        self.assertNotIn("var uris = self.scanFolder(uriPath);", out)

    def test_patch_is_idempotent(self) -> None:
        once = patcher.patch(STUB)
        twice = patcher.patch(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
