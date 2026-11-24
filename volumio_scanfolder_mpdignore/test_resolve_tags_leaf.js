#!/usr/bin/env node
'use strict';
/**
 * SHD layout: _tags/genre/x/Album -> _meta/Album -> album -> real Album.
 * dont-walk leaves the tag path empty in MPD; resolve must find the real album.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var m = require('./mpdignore');

var AUDIO = Buffer.from('fLaC-resolve');

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-resolve-'));
  var mnt = path.join(tmp, 'mnt');
  var files = path.join(mnt, 'NAS', 'gmk', 'files');
  var album = path.join(files, 'Fila Brazillia - Luck Be a Weirdo Tonight');
  var meta = path.join(files, '_meta', 'Fila Brazillia - Luck Be a Weirdo Tonight');
  var leaf = path.join(
    files,
    '_tags',
    'genre',
    'ambientelectronic',
    'Fila Brazillia - Luck Be a Weirdo Tonight'
  );
  try {
    fs.mkdirSync(album, { recursive: true });
    fs.writeFileSync(path.join(album, '01.flac'), AUDIO);
    fs.mkdirSync(meta, { recursive: true });
    fs.symlinkSync(path.join('..', '..', path.basename(album)), path.join(meta, 'album'));
    fs.mkdirSync(path.dirname(leaf), { recursive: true });
    fs.symlinkSync(
      path.join('..', '..', '..', '_meta', path.basename(album)),
      leaf
    );
    fs.writeFileSync(path.join(files, '.mpdignore'), '_meta\n');

    var rel =
      'NAS/gmk/files/_tags/genre/ambientelectronic/Fila Brazillia - Luck Be a Weirdo Tonight';
    var got = m.resolveTagsLeafMusicPath(rel, mnt);
    assert.strictEqual(
      got,
      'NAS/gmk/files/Fila Brazillia - Luck Be a Weirdo Tonight',
      'got ' + got
    );
    assert.strictEqual(m.resolveTagsLeafMusicPath('NAS/gmk/files/AlbumA', mnt), null);
    assert.strictEqual(m.resolveTagsLeafMusicPath('', mnt), null);
    console.log('OK test_resolve_tags_leaf');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
