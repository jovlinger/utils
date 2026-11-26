#!/usr/bin/env python3
"""Patch-contract tests for apply_to_index.py (scanFolder .mpdignore honor)."""
from __future__ import annotations

import unittest
from pathlib import Path

import apply_to_index as patcher

STUB = """\
'use strict';
var fs = require('fs');
var libFsExtra = require('fs-extra');

function ControllerMpd() {}

ControllerMpd.prototype.scanFolder = function (uri) {
  var self = this;
  var uris = [];
    try {
      var files = libFsExtra.readdirSync(uri);
      for (var i in files) {
        uris = uris.concat(self.scanFolder(uri + '/' + files[i]));
      }
    } catch (e) {
      self.logger.error("Failed to stat '" + uri + "'");
    }
  return uris;
};
"""


class ApplyToIndexTest(unittest.TestCase):
    def test_patch_seeds_and_matches(self) -> None:
        out = patcher.patch(STUB)
        self.assertIn("require('./mpdignore.js')", out)
        self.assertIn("function (uri, excludePatterns, doneReals)", out)
        self.assertIn("seedExcludePatterns", out)
        self.assertIn("rememberReal", out)
        self.assertIn("isStructuralSkip", out)
        self.assertIn("patternsForDir", out)
        self.assertIn("nameMatches", out)
        self.assertNotIn("for (var i in files)", out)

    def test_patch_is_idempotent(self) -> None:
        once = patcher.patch(STUB)
        twice = patcher.patch(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
