#!/usr/bin/env node
'use strict';
/**
 * Runs inside Docker with the live gmk tree mounted at /mnt/gmk.
 * Enqueue files/_tags/genre/lounge via the in-repo resolver.
 * Pass band is 112 songs as of 2026-11-24, plus or minus 5.
 */

var fs = require('fs');
var path = require('path');
var m = require('/resolver/mpdignore.js');

var MNT = process.env.GMK_MNT || '/mnt/gmk';
var LOUNGE = 'files/_tags/genre/lounge';
var LOW = 112 - 5;
var HIGH = 112 + 5;
var AUDIO = {
  flac: 1, mp3: 1, m4a: 1, ogg: 1, opus: 1, wav: 1, aac: 1, aiff: 1, aif: 1
};

function fail(msg) {
  console.error('LOUNGE_FAIL ' + msg);
  process.exit(1);
}

if (!fs.existsSync('/.dockerenv') && !fs.existsSync('/run/.containerenv')) {
  fail('check ran outside Docker');
}

var genreDir = path.join(MNT, 'files/_tags/genre');
var loungeDir = path.join(MNT, LOUNGE);
if (!fs.existsSync(loungeDir) || !fs.existsSync(path.join(MNT, 'data'))) {
  fail('mount is not the live gmk tree');
}
var genres = fs.readdirSync(genreDir);
if (genres.length < 50) {
  fail('genre tree looks like a fixture (' + genres.length + ' genres)');
}

function walkCanonical(dir, out) {
  var names;
  try {
    names = fs.readdirSync(dir);
  } catch (e) {
    return;
  }
  for (var i = 0; i < names.length; i++) {
    var name = names[i];
    if (!name || name.charAt(0) === '.' || name === '_tags' || name === '_meta') {
      continue;
    }
    var abs = path.join(dir, name);
    var st;
    try {
      st = fs.lstatSync(abs);
    } catch (e2) {
      continue;
    }
    if (st.isSymbolicLink()) {
      try {
        st = fs.statSync(abs);
      } catch (e3) {
        continue;
      }
    }
    if (st.isDirectory()) {
      walkCanonical(abs, out);
    } else if (AUDIO[path.extname(name).slice(1).toLowerCase()]) {
      out.push(abs.slice(MNT.length + 1));
    }
  }
}

var index = [];
walkCanonical(path.join(MNT, 'files'), index);
if (index.length < 1000) {
  fail('canonical index is fixture-sized (' + index.length + ')');
}

var songs = m.enqueueSongs(LOUNGE, MNT, index);
var seenUri = {};
var seenReal = {};
var albums = {};
for (var i = 0; i < songs.length; i++) {
  var uri = songs[i];
  if (seenUri[uri]) {
    fail('duplicate uri ' + uri);
  }
  seenUri[uri] = true;
  if (uri.indexOf('/_tags/') >= 0) {
    fail('enqueued a tag path ' + uri);
  }
  var parts = uri.split('/');
  if (parts[0] !== 'files' || !parts[1]) {
    fail('unexpected uri ' + uri);
  }
  albums[parts[1]] = true;
  var real;
  try {
    real = fs.realpathSync(path.join(MNT, uri));
  } catch (e4) {
    fail('missing song ' + uri);
  }
  if (seenReal[real]) {
    fail('duplicate realpath ' + real);
  }
  seenReal[real] = true;
}

var albumCount = Object.keys(albums).length;
console.log('LOUNGE_SONGS=' + songs.length);
console.log('LOUNGE_ALBUMS=' + albumCount);
console.log('LOUNGE_INDEX=' + index.length);
if (albumCount < 2) {
  fail('resolved to one album');
}
if (songs.length < LOW || songs.length > HIGH) {
  fail('song count ' + songs.length + ' outside ' + LOW + '..' + HIGH);
}
console.log('LOUNGE_OK');
