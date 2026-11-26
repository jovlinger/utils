#!/usr/bin/env python3
"""Contract: apply_lsinfo_tags_resolve patches empty _tags lsInfo tail."""
from __future__ import annotations

import unittest

import apply_lsinfo_tags_resolve as patcher


STUB = """\
var mpdignoreUtil = require('./mpdignore.js');
ControllerMpd.prototype.lsInfo = function (uri) {
  var self = this;
  var folderToList = 'x';
  var sections = ['music-library'];
  var prev = '';
  var list = [];
  var cmd = function () {};
        } else {
          self.logger.error('Failed LSINFO: ' + err);
        }
      }
      defer.resolve({
        navigation: {
          prev: {
            uri: prev
          },
          lists: [{availableListViews: ['grid', 'list'], items: list}]
        }
      });
    });
  }).fail(function (e) {
    self.logger.error('Could not execute lsinfo on URI: ' + uri + ' error: ' + e);
    defer.reject('');
  });
  return defer.promise;
};
"""


class ApplyLsinfoTagsResolveTest(unittest.TestCase):
    def test_patch_adds_resolve(self) -> None:
        out = patcher.patch(STUB)
        self.assertIn("resolveTagsLeafMusicPath", out)
        self.assertIn("finishLsInfo", out)
        self.assertNotIn(
            "defer.resolve({\n        navigation: {\n          prev: {\n            uri: prev\n          },\n          lists: [{availableListViews: ['grid', 'list'], items: list}]\n        }\n      });",
            out,
        )

    def test_idempotent(self) -> None:
        once = patcher.patch(STUB)
        twice = patcher.patch(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
