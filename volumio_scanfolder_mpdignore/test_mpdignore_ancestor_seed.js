#!/usr/bin/env node
'use strict';
/**
 * explodeUri starts scanFolder at an album path, not files/.
 * Ancestor .mpdignore (files/_tags) must still apply.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var walkMod = require('./scan_folder_walk');

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-anc-'));
  try {
    var files = path.join(tmp, 'files');
    var album = path.join(files, 'AlbumA');
    var localTags = path.join(album, '_tags', 'album');
    fs.mkdirSync(localTags, { recursive: true });
    fs.writeFileSync(path.join(album, '01.flac'), 'flac');
    fs.writeFileSync(path.join(localTags, 'trap.flac'), 'bad');
    fs.writeFileSync(path.join(files, '.mpdignore'), '_tags\n_meta\n');

    // Start at album (Volumio explodeUri style), not at files/
    var result = walkMod.walk(album, { honorMpdignore: true });
    var relFiles = result.visitedFiles.map(function (p) {
      return path.relative(album, p).split(path.sep).join('/');
    });
    assert.deepStrictEqual(relFiles, ['01.flac'], 'got ' + JSON.stringify(relFiles));
    assert.ok(result.mpdignoreSkipped > 0, 'expected skip of _tags');
    console.log('OK test_mpdignore_ancestor_seed');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
