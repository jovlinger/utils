#!/usr/bin/env node
'use strict';
/**
 * explodeUri starts scanFolder at an album path, not files/.
 * Ancestor files/.mpdignore (_tags/_meta) must still apply when honor is on.
 * RED: honor off visits album-local _tags trap.
 * GREEN: honor on keeps only 01.flac.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var walkMod = require('./scan_folder_walk');

function buildAlbum(tmp) {
  var files = path.join(tmp, 'files');
  var album = path.join(files, 'AlbumA');
  var localTags = path.join(album, '_tags', 'album');
  fs.mkdirSync(localTags, { recursive: true });
  fs.writeFileSync(path.join(album, '01.flac'), 'flac');
  fs.writeFileSync(path.join(localTags, 'trap.flac'), 'bad');
  fs.writeFileSync(path.join(files, '.mpdignore'), '_tags\n_meta\n');
  return album;
}

function relFiles(album, result) {
  return result.visitedFiles.map(function (p) {
    return path.relative(album, p).split(path.sep).join('/');
  }).sort();
}

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-anc-'));
  try {
    var album = buildAlbum(tmp);

    var red = walkMod.walk(album, { honorMpdignore: false });
    var redRels = relFiles(album, red);
    assert.ok(
      redRels.indexOf('_tags/album/trap.flac') >= 0,
      'RED: honor off must visit trap under _tags: ' + JSON.stringify(redRels)
    );
    assert.ok(redRels.indexOf('01.flac') >= 0, 'RED: album flac still seen');
    assert.strictEqual(red.mpdignoreSkipped, 0);

    var green = walkMod.walk(album, { honorMpdignore: true });
    var greenRels = relFiles(album, green);
    assert.deepStrictEqual(
      greenRels,
      ['01.flac'],
      'GREEN: ancestor ignore must skip _tags; got ' + JSON.stringify(greenRels)
    );
    assert.ok(green.mpdignoreSkipped > 0, 'GREEN: expected skip of _tags');
    console.log('OK test_mpdignore_ancestor_seed red/green');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
