#!/usr/bin/env node
'use strict';
/**
 * Album-local _tags symlink cycle vs files/.mpdignore.
 * explodeUri-style walk starts at the album directory.
 * RED (honor off): visit budget is hit (cycle).
 * GREEN (honor on): walk terminates; only the real flac is listed.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var walkMod = require('./scan_folder_walk');

var VISIT_BUDGET = 40;
var AUDIO = Buffer.from('fLaC-album-local');

function buildFixture(root) {
  var files = path.join(root, 'files');
  var album = path.join(files, 'AlbumA');
  fs.mkdirSync(album, { recursive: true });
  fs.writeFileSync(path.join(album, '01.flac'), AUDIO);
  fs.writeFileSync(path.join(files, '.mpdignore'), '_tags\n_meta\n');

  var tagsAlbum = path.join(files, '_tags', 'album');
  fs.mkdirSync(tagsAlbum, { recursive: true });
  fs.symlinkSync(
    path.join('..', '..', 'AlbumA'),
    path.join(tagsAlbum, 'AlbumA')
  );

  var localTags = path.join(album, '_tags', 'album');
  fs.mkdirSync(localTags, { recursive: true });
  fs.symlinkSync(
    path.join('..', '..', '..', '_tags', 'album', 'AlbumA'),
    path.join(localTags, 'AlbumA')
  );
  return album;
}

function relFiles(album, result) {
  return result.visitedFiles.map(function (p) {
    return path.relative(album, p).split(path.sep).join('/');
  });
}

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-cycle-'));
  try {
    var album = buildFixture(tmp);

    var red = walkMod.walk(album, {
      honorMpdignore: false,
      doneSet: false,
      structuralSkip: false,
      maxVisits: VISIT_BUDGET
    });
    assert.strictEqual(
      red.hitBudget,
      true,
      'RED: honor/doneSet/structuralSkip off must hit visit budget; visits=' +
        red.visitedDirs.length
    );

    var green = walkMod.walk(album, {
      honorMpdignore: true,
      maxVisits: VISIT_BUDGET
    });
    assert.strictEqual(
      green.hitBudget,
      false,
      'GREEN: honor on must terminate; visits=' + green.visitedDirs.length
    );
    assert.ok(green.visitedDirs.length < VISIT_BUDGET);
    var gFiles = relFiles(album, green);
    assert.deepStrictEqual(
      gFiles,
      ['01.flac'],
      'GREEN: only real album flac; got ' + JSON.stringify(gFiles)
    );
    assert.ok(green.mpdignoreSkipped > 0, 'GREEN: skipped _tags');
    console.log('OK test_mpdignore_album_local_cycle red/green');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
