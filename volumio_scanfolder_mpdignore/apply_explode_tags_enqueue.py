#!/usr/bin/env python3
"""Patch explodeUri so a _tags folder enqueues canonical album prefixes.

scanFolder keeps the path it was given. A tag album path has no MPD file
rows, and a tag tree that omits a disc would enqueue only the discs it
lists. tagEnqueuePrefixes rewrites the walk roots first.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


OLD_BRANCH = """\
  } else {
    var uriPath = '/mnt/' + self.sanitizeUri(uri);
    // self.commandRouter.logger.info('----------------------------'+uriPath);
    var uris = self.scanFolder(uriPath);
    var response = [];

    libQ.all(uris)
"""

NEW_BRANCH = """\
  } else {
    var uriPath = '/mnt/' + self.sanitizeUri(uri);
    // self.commandRouter.logger.info('----------------------------'+uriPath);
    var enqueueRoots = [uriPath];
    if (uriPath.indexOf('/_tags/') >= 0 &&
        typeof mpdignoreUtil !== 'undefined' && mpdignoreUtil.tagEnqueuePrefixes) {
      var musicRel = uriPath.replace(/^\\/mnt\\//, '');
      var resolved = mpdignoreUtil.tagEnqueuePrefixes(musicRel, '/mnt');
      enqueueRoots = [];
      for (var ri = 0; ri < resolved.length; ri++) {
        enqueueRoots.push('/mnt/' + resolved[ri]);
      }
    }
    var uris = [];
    for (var ei = 0; ei < enqueueRoots.length; ei++) {
      uris = uris.concat(self.scanFolder(enqueueRoots[ei]));
    }
    var response = [];

    libQ.all(uris)
"""


def patch(text: str) -> str:
    if "tagEnqueuePrefixes" in text:
        return text
    if OLD_BRANCH not in text:
        raise SystemExit("explodeUri folder branch not found (upstream changed?)")
    if "mpdignoreUtil" not in text:
        raise SystemExit("expected mpdignoreUtil require before explodeUri patch")
    return text.replace(OLD_BRANCH, NEW_BRANCH, 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("index_js", type=Path)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    raw = args.index_js.read_text(encoding="utf-8")
    out = patch(raw)
    if args.in_place:
        bak = args.index_js.with_suffix(args.index_js.suffix + ".bak-explode-tags")
        if not bak.exists():
            shutil.copy2(args.index_js, bak)
        args.index_js.write_text(out, encoding="utf-8")
        print("patched", args.index_js, "backup", bak, file=sys.stderr)
    elif args.output:
        args.output.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
