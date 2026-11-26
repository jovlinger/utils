#!/usr/bin/env python3
"""Patch ControllerMpd.lsInfo so empty _tags album leaves resolve to real albums.

dont-walk MPD keeps directory: stubs under _tags but indexes songs only on the
canonical album path. SHD tag leaves often symlink via ignored _meta/.../album,
so lsinfo of the leaf is empty and Volumio shows Nothing. After an empty parse,
re-issue lsinfo on resolveTagsLeafMusicPath(...).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


# Inserted immediately after the lsinfo parse loop finishes building `list`,
# before defer.resolve({navigation...}).
OLD_TAIL = """\
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

NEW_TAIL = """\
        } else {
          self.logger.error('Failed LSINFO: ' + err);
        }
      }
      var finishLsInfo = function (finalList) {
        defer.resolve({
          navigation: {
            prev: {
              uri: prev
            },
            lists: [{availableListViews: ['grid', 'list'], items: finalList}]
          }
        });
      };
      if (list.length === 0 && folderToList && folderToList.indexOf('/_tags/') >= 0 &&
          typeof mpdignoreUtil !== 'undefined' && mpdignoreUtil.resolveTagsLeafMusicPath) {
        var resolved = mpdignoreUtil.resolveTagsLeafMusicPath(folderToList);
        if (resolved && resolved !== folderToList) {
          var safeResolved = resolved.replace(/"/g, '\\\\"');
          self.clientMpd.sendCommand(cmd('lsinfo "' + safeResolved + '"', []), function (err2, msg2) {
            var list2 = [];
            if (msg2) {
              var lines2 = msg2.split('\\n');
              var s0r = sections[0] + '/';
              for (var j = 0; j < lines2.length; j++) {
                var line2 = lines2[j];
                if (line2.indexOf('file:') === 0) {
                  var path2 = line2.slice(6);
                  var name2 = path2.split('/').pop();
                  var artist2 = self.searchFor(lines2, j + 1, 'Artist:');
                  var album2 = self.searchFor(lines2, j + 1, 'Album:');
                  var title2 = self.searchFor(lines2, j + 1, 'Title:');
                  if (!title2) {
                    title2 = name2;
                  }
                  list2.push({
                    service: 'mpd',
                    type: 'song',
                    title: title2,
                    artist: artist2,
                    album: album2,
                    uri: s0r + path2,
                    albumart: self.getAlbumArt('', self.getParentFolder('/mnt/' + path2), 'music')
                  });
                } else if (line2.indexOf('directory:') === 0) {
                  var dpath = line2.slice(11);
                  var dname = dpath.split('/').pop();
                  if (dname && dname.charAt(0) !== '.' && dname !== '_tags' && dname !== '_meta') {
                    list2.push({
                      type: 'folder',
                      title: dname,
                      service: 'mpd',
                      albumart: self.getAlbumArt('', '/mnt/' + dpath, 'folder-o'),
                      uri: s0r + dpath
                    });
                  }
                }
              }
            } else if (err2) {
              self.logger.error('Failed LSINFO resolve: ' + err2);
            }
            finishLsInfo(list2.length ? list2 : list);
          });
          return;
        }
      }
      finishLsInfo(list);
    });
  }).fail(function (e) {
    self.logger.error('Could not execute lsinfo on URI: ' + uri + ' error: ' + e);
    defer.reject('');
  });
  return defer.promise;
};
"""


def patch(text: str) -> str:
    if "resolveTagsLeafMusicPath" in text and "finishLsInfo" in text:
        return text
    if OLD_TAIL not in text:
        raise SystemExit("lsInfo resolve tail not found (upstream changed?)")
    if "mpdignoreUtil" not in text:
        raise SystemExit("expected mpdignoreUtil require before lsInfo patch")
    return text.replace(OLD_TAIL, NEW_TAIL, 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("index_js", type=Path)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    raw = args.index_js.read_text(encoding="utf-8")
    out = patch(raw)
    if args.in_place:
        bak = args.index_js.with_suffix(args.index_js.suffix + ".bak-lsinfo-tags")
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
