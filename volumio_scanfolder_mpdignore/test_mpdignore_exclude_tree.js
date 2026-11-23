#!/usr/bin/env node
'use strict';
/**
 * Red/green for Volumio scanFolder .mpdignore honor.
 * Fixture: AlbumA + fat noise/ tree; .mpdignore lists noise.
 * Success: noise never visited; album flac still seen.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var walkMod = require('./scan_folder_walk');

var AUDIO = Buffer.from('fLaC-keep');

function buildFixture(root) {
  var files = path.join(root, 'files');
  var album = path.join(files, 'AlbumA');
  fs.mkdirSync(album, { recursive: true });
  fs.writeFileSync(path.join(album, '01.flac'), AUDIO);

  var noise = path.join(files, 'noise', 'deep', 'wider');
  fs.mkdirSync(noise, { recursive: true });
  fs.writeFileSync(path.join(noise, 'dump.bin'), Buffer.alloc(64, 0x78));
  fs.writeFileSync(path.join(noise, 'trap.flac'), AUDIO);
  fs.writeFileSync(path.join(files, 'noise', 'readme.txt'), 'not music\n');

  fs.writeFileSync(path.join(files, '.mpdignore'), 'noise\n');
  return files;
}

function relUnder(root, abs) {
  return path.relative(root, abs).split(path.sep).join('/');
}

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-mpdignore-'));
  try {
    var files = buildFixture(tmp);
    var result = walkMod.walk(files, { honorMpdignore: true });
    var dirs = result.visitedDirs.map(function (p) {
      return relUnder(files, p);
    });
    var fileRels = result.visitedFiles.map(function (p) {
      return relUnder(files, p);
    });

    assert.strictEqual(
      fileRels.filter(function (p) {
        return p.indexOf('noise') >= 0;
      }).length,
      0,
      'noise files must not be visited: ' + JSON.stringify(fileRels)
    );
    assert.strictEqual(
      dirs.filter(function (p) {
        return p === 'noise' || p.indexOf('noise/') === 0;
      }).length,
      0,
      'noise dirs must not be visited: ' + JSON.stringify(dirs)
    );
    assert.ok(
      fileRels.indexOf('AlbumA/01.flac') >= 0,
      'album flac must remain: ' + JSON.stringify(fileRels)
    );
    assert.ok(
      result.mpdignoreSkipped > 0,
      'expected mpdignore skip count > 0'
    );
    console.log('OK test_mpdignore_exclude_tree');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
