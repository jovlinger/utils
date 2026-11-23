#!/usr/bin/env node
'use strict';
/**
 * Feature tests for mpdignore.js: fnmatch, nameMatches, inherited
 * patternsForDir, seedExcludePatterns vs already-seeded lists.
 */

var assert = require('assert');
var fs = require('fs');
var os = require('os');
var path = require('path');
var m = require('./mpdignore');

function main() {
  var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vol-feat-'));
  try {
    var files = path.join(tmp, 'files');
    var album = path.join(files, 'AlbumA');
    fs.mkdirSync(album, { recursive: true });
    fs.writeFileSync(
      path.join(files, '.mpdignore'),
      '# comment\n\n_tags\n_meta\n*.tmp\n'
    );
    fs.writeFileSync(path.join(album, '.mpdignore'), 'scratch\n');

    var local = m.readPatterns(files);
    assert.deepStrictEqual(local, ['_tags', '_meta', '*.tmp']);
    assert.strictEqual(m.readPatterns(path.join(tmp, 'missing')).length, 0);

    assert.strictEqual(m.fnmatch('_tags', '_tags'), true);
    assert.strictEqual(m.fnmatch('foo.tmp', '*.tmp'), true);
    assert.strictEqual(m.fnmatch('foo.flac', '*.tmp'), false);
    assert.strictEqual(m.fnmatch('a', '?'), true);
    assert.strictEqual(m.fnmatch('ab', '?'), false);
    assert.strictEqual(m.fnmatch('noise', '[n]oise'), true);
    assert.strictEqual(m.fnmatch('poise', '[n]oise'), false);
    assert.strictEqual(m.fnmatch('noise', '[!n]oise'), false);
    assert.strictEqual(m.fnmatch('poise', '[!n]oise'), true);

    assert.strictEqual(m.nameMatches('_tags', local), true);
    assert.strictEqual(m.nameMatches('AlbumA', local), false);
    assert.strictEqual(m.nameMatches('x.tmp', local), true);
    assert.strictEqual(m.nameMatches('x', []), false);
    assert.strictEqual(m.nameMatches('x', null), false);

    var inherited = m.patternsForDir(album, local);
    assert.ok(inherited.indexOf('_tags') >= 0);
    assert.ok(inherited.indexOf('scratch') >= 0);
    assert.ok(inherited.indexOf('*.tmp') >= 0);

    var seededEmpty = m.seedExcludePatterns(album, []);
    assert.ok(
      seededEmpty.indexOf('_tags') >= 0,
      'empty seed must load ancestor files/.mpdignore: ' + JSON.stringify(seededEmpty)
    );
    var seededNull = m.seedExcludePatterns(album);
    assert.ok(seededNull.indexOf('_tags') >= 0);

    var already = ['_keep'];
    var kept = m.seedExcludePatterns(album, already);
    assert.deepStrictEqual(
      kept,
      already,
      'non-empty excludePatterns must be kept as-is'
    );

    var anc = m.collectAncestorPatterns(album);
    assert.ok(anc.indexOf('_tags') >= 0);
    assert.ok(anc.indexOf('_meta') >= 0);
    assert.ok(
      anc.indexOf('scratch') < 0,
      'ancestor collect must not include absPath itself'
    );

    console.log('OK test_mpdignore_features');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

main();
