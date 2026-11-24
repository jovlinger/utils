#!/usr/bin/env python3
"""Patch Volumio music_service/mpd/index.js so scanFolder honors .mpdignore."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


REQUIRE_LINE = "var mpdignoreUtil = require('./mpdignore.js');\n"

OLD_SIG = "ControllerMpd.prototype.scanFolder = function (uri) {"
HONOR_SIG = "ControllerMpd.prototype.scanFolder = function (uri, excludePatterns) {"
NEW_SIG = "ControllerMpd.prototype.scanFolder = function (uri, excludePatterns, doneReals) {"

OLD_LOOP = """\
    try {
      var files = libFsExtra.readdirSync(uri);
      for (var i in files) {
        uris = uris.concat(self.scanFolder(uri + '/' + files[i]));
      }
    } catch (e) {
      self.logger.error("Failed to stat '" + uri + "'");
    }
"""

HONOR_LOOP = """\
    try {
      excludePatterns = mpdignoreUtil.seedExcludePatterns(uri, excludePatterns);
      var files = libFsExtra.readdirSync(uri);
      var patterns = mpdignoreUtil.patternsForDir(uri, excludePatterns);
      for (var i = 0; i < files.length; i++) {
        var name = files[i];
        if (mpdignoreUtil.nameMatches(name, patterns)) {
          continue;
        }
        uris = uris.concat(self.scanFolder(uri + '/' + name, patterns));
      }
    } catch (e) {
      self.logger.error("Failed to stat '" + uri + "'");
    }
"""

NEW_LOOP = """\
    try {
      doneReals = doneReals || {};
      if (mpdignoreUtil.rememberReal(doneReals, uri)) {
        return uris;
      }
      excludePatterns = mpdignoreUtil.seedExcludePatterns(uri, excludePatterns);
      var files = libFsExtra.readdirSync(uri);
      var patterns = mpdignoreUtil.patternsForDir(uri, excludePatterns);
      for (var i = 0; i < files.length; i++) {
        var name = files[i];
        if (mpdignoreUtil.nameMatches(name, patterns)) {
          continue;
        }
        uris = uris.concat(self.scanFolder(uri + '/' + name, patterns, doneReals));
      }
    } catch (e) {
      self.logger.error("Failed to stat '" + uri + "'");
    }
"""

# Prior patch used a weaker seed (empty array only); upgrade in place.
OLD_SEEDED_LOOP = """\
    try {
      excludePatterns = excludePatterns || [];
      var files = libFsExtra.readdirSync(uri);
      var patterns = mpdignoreUtil.patternsForDir(uri, excludePatterns);
      for (var i = 0; i < files.length; i++) {
        var name = files[i];
        if (mpdignoreUtil.nameMatches(name, patterns)) {
          continue;
        }
        uris = uris.concat(self.scanFolder(uri + '/' + name, patterns));
      }
    } catch (e) {
      self.logger.error("Failed to stat '" + uri + "'");
    }
"""


def patch(text: str) -> str:
    if "rememberReal" in text and "doneReals" in text and "mpdignoreUtil" in text:
        return text  # already fully patched
    if "var fs = require('fs');" not in text:
        raise SystemExit("expected fs require in index.js")

    if "mpdignoreUtil" in text and HONOR_LOOP in text:
        text = text.replace(HONOR_SIG, NEW_SIG, 1)
        return text.replace(HONOR_LOOP, NEW_LOOP, 1)

    if "mpdignoreUtil" in text and OLD_SEEDED_LOOP in text:
        text = text.replace(HONOR_SIG, NEW_SIG, 1)
        text = text.replace(OLD_SIG, NEW_SIG, 1)
        return text.replace(OLD_SEEDED_LOOP, NEW_LOOP, 1)

    if OLD_SIG not in text:
        raise SystemExit("scanFolder signature not found")
    if OLD_LOOP not in text:
        raise SystemExit("scanFolder readdir loop not found (upstream changed?)")

    text = text.replace(
        "var fs = require('fs');\n",
        "var fs = require('fs');\n" + REQUIRE_LINE,
        1,
    )
    text = text.replace(OLD_SIG, NEW_SIG, 1)
    text = text.replace(OLD_LOOP, NEW_LOOP, 1)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("index_js", type=Path, help="path to mpd/index.js")
    ap.add_argument(
        "--in-place",
        action="store_true",
        help="rewrite index_js (writes .bak first)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write patched file here (default stdout with --in-place off)",
    )
    args = ap.parse_args()
    raw = args.index_js.read_text(encoding="utf-8")
    out = patch(raw)
    if args.in_place:
        bak = args.index_js.with_suffix(args.index_js.suffix + ".bak-mpdignore")
        if not bak.exists():
            shutil.copy2(args.index_js, bak)
        args.index_js.write_text(out, encoding="utf-8")
        print("patched", args.index_js, "backup", bak, file=sys.stderr)
    elif args.output:
        args.output.write_text(out, encoding="utf-8")
        print("wrote", args.output, file=sys.stderr)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
