#!/usr/bin/env node
'use strict';
/**
 * Green/green: canonical album and disc prefixes enqueue indexed songs.
 * Red/green: _tags prefixes have no indexed file rows; enqueue resolves them.
 * Artist prefix is every album under that artist, not only 101.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var m = require('./mpdignore');

var FILES = 'NAS/gmk/files';
var ALBUM = FILES + '/Depeche Mode - 101';
var DISC_A = ALBUM + '/disc A';
var DISC_B = ALBUM + '/disc B';
var OTHER = FILES + '/Speak and Spell';
var TAG_ARTIST = FILES + '/_tags/artists/depechemode';
var TAG_ALBUM = TAG_ARTIST + '/Depeche Mode - 101';
var TAG_DISC_B = TAG_ALBUM + '/disc B';

function writeFlac(abs) {
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, Buffer.from('fLaC'));
}

function build(mnt) {
  var files = path.join(mnt, FILES);
  writeFlac(path.join(mnt, DISC_A, 'a1.flac'));
  writeFlac(path.join(mnt, DISC_B, 'b1.flac'));
  writeFlac(path.join(mnt, OTHER, '01.flac'));
  var meta101 = path.join(files, '_meta', 'Depeche Mode - 101');
  var metaSpeak = path.join(files, '_meta', 'Speak and Spell');
  fs.mkdirSync(meta101, { recursive: true });
  fs.mkdirSync(metaSpeak, { recursive: true });
  fs.symlinkSync(path.join('..', '..', 'Depeche Mode - 101'), path.join(meta101, 'album'));
  fs.symlinkSync(path.join('..', '..', 'Speak and Spell'), path.join(metaSpeak, 'album'));
  var tag101 = path.join(mnt, TAG_ALBUM);
  fs.mkdirSync(tag101, { recursive: true });
  fs.symlinkSync(
    path.join('..', '..', '..', '..', '_meta', 'Depeche Mode - 101', 'album', 'disc B'),
    path.join(tag101, 'disc B')
  );
  fs.symlinkSync(
    path.join('..', '..', '..', '_meta', 'Speak and Spell'),
    path.join(mnt, TAG_ARTIST, 'Speak and Spell')
  );
  fs.writeFileSync(path.join(files, '.mpdignore'), '_meta\n');
}

function sorted(list) {
  return list.slice().sort();
}

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'enq-prefix-'));
  var mnt = path.join(tmp, 'mnt');
  try {
    build(mnt);
    var index = [
      DISC_A + '/a1.flac',
      DISC_B + '/b1.flac',
      OTHER + '/01.flac'
    ];

    var albumSongs = sorted(m.enqueueSongs(ALBUM, mnt, index));
    var discASongs = sorted(m.enqueueSongs(DISC_A, mnt, index));
    var discBSongs = sorted(m.enqueueSongs(DISC_B, mnt, index));
    assert.deepStrictEqual(albumSongs, sorted([DISC_A + '/a1.flac', DISC_B + '/b1.flac']));
    assert.deepStrictEqual(discASongs, [DISC_A + '/a1.flac']);
    assert.ok(discASongs.length > 0);
    discASongs.forEach(function (song) {
      assert.ok(discBSongs.indexOf(song) < 0);
    });

    index.forEach(function (song) {
      assert.ok(song.indexOf('/_tags/') < 0, 'red index must not store tag file rows');
    });
    [TAG_DISC_B, TAG_ALBUM, TAG_ARTIST].forEach(function (prefix) {
      assert.deepStrictEqual(
        m.filesUnderPrefix(index, prefix),
        [],
        'red: no indexed files under ' + prefix
      );
    });

    assert.deepStrictEqual(sorted(m.enqueueSongs(TAG_DISC_B, mnt, index)), discBSongs);
    assert.deepStrictEqual(sorted(m.enqueueSongs(TAG_ALBUM, mnt, index)), albumSongs);
    var artistSongs = sorted(m.enqueueSongs(TAG_ARTIST, mnt, index));
    assert.deepStrictEqual(artistSongs, sorted(index));
    assert.ok(artistSongs.length > albumSongs.length, 'artist prefix is more than 101');

    assert.deepStrictEqual(m.enqueueSongs(TAG_ARTIST + '/missing', mnt, index), []);
    assert.deepStrictEqual(m.enqueueSongs(FILES + '/_tags/no-such', mnt, index), []);

    console.log('OK test_enqueue_prefixes');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
