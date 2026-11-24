#!/usr/bin/env node
'use strict';
/**
 * Cross-album _tags fan-out: when files/.mpdignore lists only _meta, a naive
 * honor+.done-set walk from AlbumA still visits every album reachable through
 * _tags mirrors (SHD-scale combinatorial explode). Structural skip of _tags
 * must keep visits O(1 album).
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var walkMod = require('./scan_folder_walk');

var VISIT_BUDGET = 40;
var AUDIO = Buffer.from('fLaC-fanout');

function buildFixture(root) {
  var files = path.join(root, 'files');
  var albums = ['AlbumA', 'AlbumB', 'AlbumC'];
  albums.forEach(function (name) {
    var album = path.join(files, name);
    fs.mkdirSync(album, { recursive: true });
    fs.writeFileSync(path.join(album, '01.flac'), AUDIO);
    fs.mkdirSync(path.join(album, '_tags', 'album'), { recursive: true });
  });
  fs.mkdirSync(path.join(files, '_tags', 'album'), { recursive: true });
  // Global + album-local mirrors: A -> B -> C -> A
  fs.symlinkSync(
    path.join('..', '..', 'AlbumB'),
    path.join(files, '_tags', 'album', 'AlbumB')
  );
  fs.symlinkSync(
    path.join('..', '..', '..', '_tags', 'album', 'AlbumB'),
    path.join(files, 'AlbumA', '_tags', 'album', 'AlbumB')
  );
  fs.symlinkSync(
    path.join('..', '..', '..', 'AlbumC'),
    path.join(files, 'AlbumB', '_tags', 'album', 'AlbumC')
  );
  fs.symlinkSync(
    path.join('..', '..', '..', 'AlbumA'),
    path.join(files, 'AlbumC', '_tags', 'album', 'AlbumA')
  );
  fs.writeFileSync(path.join(files, '.mpdignore'), '_meta\n');
  return path.join(files, 'AlbumA');
}

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-fanout-'));
  try {
    var albumA = buildFixture(tmp);
    var red = walkMod.walk(albumA, {
      honorMpdignore: true,
      structuralSkip: false,
      maxVisits: VISIT_BUDGET
    });
    var redJoined = red.visitedDirs.join('\n');
    assert.ok(
      redJoined.indexOf('AlbumB') >= 0 && redJoined.indexOf('AlbumC') >= 0,
      'RED: without structural skip, _tags must fan out into AlbumB/C; dirs=' +
        redJoined
    );

    var green = walkMod.walk(albumA, {
      honorMpdignore: true,
      structuralSkip: true,
      maxVisits: VISIT_BUDGET
    });
    assert.strictEqual(
      green.hitBudget,
      false,
      'GREEN: structural skip must terminate; visits=' + green.visitedDirs.length
    );
    var joined = green.visitedDirs.join('\n');
    assert.ok(joined.indexOf('AlbumB') < 0, 'must not enter AlbumB via _tags');
    assert.ok(joined.indexOf('AlbumC') < 0, 'must not enter AlbumC via _tags');
    assert.ok(
      green.visitedFiles.some(function (p) {
        return path.basename(p) === '01.flac';
      }),
      'AlbumA audio kept'
    );
    console.log('OK test_mpdignore_cross_album_fanout red/green');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
