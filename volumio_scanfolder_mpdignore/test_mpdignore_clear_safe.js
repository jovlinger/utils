#!/usr/bin/env node
'use strict';
/**
 * Clearing files/.mpdignore must stay safe: album-local _tags cycles
 * terminate via realpath done-set even with no ignore patterns.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var walkMod = require('./scan_folder_walk');

var VISIT_BUDGET = 40;
var AUDIO = Buffer.from('fLaC-clear-safe');

function buildFixture(root, withIgnore) {
  var files = path.join(root, 'files');
  var album = path.join(files, 'AlbumA');
  fs.mkdirSync(album, { recursive: true });
  fs.writeFileSync(path.join(album, '01.flac'), AUDIO);
  if (withIgnore) {
    fs.writeFileSync(path.join(files, '.mpdignore'), '_tags\n_meta\n');
  }
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

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-clear-'));
  try {
    var album = buildFixture(tmp, false);
    var result = walkMod.walk(album, {
      honorMpdignore: true,
      maxVisits: VISIT_BUDGET
    });
    assert.strictEqual(
      result.hitBudget,
      false,
      'no .mpdignore: done-set must terminate; visits=' + result.visitedDirs.length
    );
    assert.ok(result.visitedDirs.length < VISIT_BUDGET);
    var rels = result.visitedFiles.map(function (p) {
      return path.relative(album, p).split(path.sep).join('/');
    });
    assert.ok(rels.indexOf('01.flac') >= 0, 'real flac kept: ' + JSON.stringify(rels));
    console.log('OK test_mpdignore_clear_safe');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
