#!/usr/bin/env node
'use strict';
/**
 * Red/green for Volumio scanFolder .mpdignore honor.
 * Fixture: AlbumA + fat noise/ tree; files/.mpdignore lists noise.
 * RED (honor off): noise is visited.
 * GREEN (honor on): noise never visited; album flac still seen.
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

function fileRels(files, result) {
  return result.visitedFiles.map(function (p) {
    return relUnder(files, p);
  });
}

function dirRels(files, result) {
  return result.visitedDirs.map(function (p) {
    return relUnder(files, p);
  });
}

function noiseFileHits(rels) {
  return rels.filter(function (p) {
    return p.indexOf('noise') >= 0;
  });
}

function noiseDirHits(dirs) {
  return dirs.filter(function (p) {
    return p === 'noise' || p.indexOf('noise/') === 0;
  });
}

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-mpdignore-'));
  try {
    var files = buildFixture(tmp);

    var red = walkMod.walk(files, { honorMpdignore: false });
    var redFiles = fileRels(files, red);
    assert.ok(
      noiseFileHits(redFiles).length > 0,
      'RED: honor off must visit noise files: ' + JSON.stringify(redFiles)
    );
    assert.ok(
      redFiles.indexOf('AlbumA/01.flac') >= 0,
      'RED: album flac still seen'
    );
    assert.strictEqual(red.mpdignoreSkipped, 0, 'RED: no mpdignore skips');

    var green = walkMod.walk(files, { honorMpdignore: true });
    var greenFiles = fileRels(files, green);
    var greenDirs = dirRels(files, green);
    assert.strictEqual(
      noiseFileHits(greenFiles).length,
      0,
      'GREEN: noise files must not be visited: ' + JSON.stringify(greenFiles)
    );
    assert.strictEqual(
      noiseDirHits(greenDirs).length,
      0,
      'GREEN: noise dirs must not be visited: ' + JSON.stringify(greenDirs)
    );
    assert.ok(
      greenFiles.indexOf('AlbumA/01.flac') >= 0,
      'GREEN: album flac must remain: ' + JSON.stringify(greenFiles)
    );
    assert.ok(green.mpdignoreSkipped > 0, 'GREEN: expected mpdignore skip');
    console.log('OK test_mpdignore_exclude_tree red/green');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
