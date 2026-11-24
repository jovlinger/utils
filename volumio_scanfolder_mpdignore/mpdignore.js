'use strict';
/**
 * MPD .mpdignore helpers for Volumio ControllerMpd.scanFolder.
 *
 * Semantics match MPD ExcludeList enough for Volumio FS walks:
 * - patterns are shell wildcards matched against basenames
 * - patterns from a directory's .mpdignore are inherited by children
 * - # comments and blank lines ignored
 */

var fs = require('fs');
var path = require('path');

/**
 * @param {string} absDir
 * @return {string[]}
 */
function readPatterns(absDir) {
  var ignorePath = path.join(absDir, '.mpdignore');
  var patterns = [];
  var raw;
  try {
    if (!fs.existsSync(ignorePath) || !fs.statSync(ignorePath).isFile()) {
      return patterns;
    }
    raw = fs.readFileSync(ignorePath, 'utf8');
  } catch (e) {
    return patterns;
  }
  var lines = raw.split(/\r?\n/);
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line || line.charAt(0) === '#') {
      continue;
    }
    patterns.push(line);
  }
  return patterns;
}

/**
 * Shell-wildcard match (fnmatch-ish) for a single basename.
 * Supports *, ?, and character classes like MPD/fnmatch.
 * @param {string} name
 * @param {string} pattern
 * @return {boolean}
 */
function fnmatch(name, pattern) {
  // Escape regex specials except our glob tokens, then translate.
  var reSrc = '';
  for (var i = 0; i < pattern.length; i++) {
    var c = pattern.charAt(i);
    if (c === '*') {
      reSrc += '.*';
    } else if (c === '?') {
      reSrc += '.';
    } else if (c === '[') {
      var j = i + 1;
      var buf = '[';
      if (j < pattern.length && pattern.charAt(j) === '!') {
        buf += '^';
        j++;
      }
      var closed = false;
      for (; j < pattern.length; j++) {
        var cj = pattern.charAt(j);
        if (cj === ']') {
          buf += ']';
          closed = true;
          break;
        }
        buf += cj;
      }
      if (!closed) {
        reSrc += '\\[';
        continue;
      }
      reSrc += buf;
      i = j;
    } else if ('\\.|^$()+{}'.indexOf(c) >= 0) {
      reSrc += '\\' + c;
    } else {
      reSrc += c;
    }
  }
  try {
    return new RegExp('^' + reSrc + '$').test(name);
  } catch (e) {
    return name === pattern;
  }
}

/**
 * @param {string} name basename
 * @param {string[]} patterns
 * @return {boolean}
 */
function nameMatches(name, patterns) {
  if (!patterns || !patterns.length) {
    return false;
  }
  for (var i = 0; i < patterns.length; i++) {
    if (fnmatch(name, patterns[i])) {
      return true;
    }
  }
  return false;
}

/**
 * Merge parent exclude list with local .mpdignore.
 * @param {string} absDir
 * @param {string[]} [parentPatterns]
 * @return {string[]}
 */
function patternsForDir(absDir, parentPatterns) {
  var parent = parentPatterns || [];
  return parent.concat(readPatterns(absDir));
}

/**
 * Collect .mpdignore patterns from ancestors of absPath (not absPath itself).
 *
 * Volumio explodeUri often starts scanFolder at an album directory under
 * /mnt/..., so files/.mpdignore would never be seen unless we walk upward.
 * Stop at /mnt (inclusive) or filesystem root.
 *
 * @param {string} absPath
 * @return {string[]}
 */
function collectAncestorPatterns(absPath) {
  var patterns = [];
  var cur = path.resolve(absPath);
  var parent = path.dirname(cur);
  var chain = [];
  while (parent && parent !== cur) {
    chain.push(parent);
    if (parent === '/mnt' || parent === '/') {
      break;
    }
    cur = parent;
    parent = path.dirname(cur);
  }
  chain.reverse();
  for (var i = 0; i < chain.length; i++) {
    patterns = patterns.concat(readPatterns(chain[i]));
  }
  return patterns;
}

/**
 * Seed exclude list for a scanFolder entry point.
 * If caller already passed patterns (recursive), keep them; otherwise load ancestors.
 * @param {string} absDir
 * @param {string[]} [excludePatterns]
 * @return {string[]}
 */
function seedExcludePatterns(absDir, excludePatterns) {
  if (excludePatterns && excludePatterns.length) {
    return excludePatterns;
  }
  return collectAncestorPatterns(absDir);
}

/**
 * Remember a directory realpath. Return true if it was already seen
 * (caller must not descend). Used so scanFolder can drop .mpdignore
 * without following album-local _tags cycles.
 * @param {Object<string, boolean>} doneReals
 * @param {string} absPath
 * @return {boolean} true if this real path is already in the set
 */
function rememberReal(doneReals, absPath) {
  var key;
  try {
    key = fs.realpathSync(absPath);
  } catch (e) {
    key = absPath;
  }
  if (doneReals[key]) {
    return true;
  }
  doneReals[key] = true;
  return false;
}

/**
 * Tag-mirror directory names. scanFolder must not descend into these even
 * when files/.mpdignore lists only _meta (MPD still indexes _tags via its
 * own updater). Cross-album _tags symlinks otherwise fan out across the
 * whole library; done-set alone only stops true cycles, not that BFS.
 * @param {string} name
 * @return {boolean}
 */
function isStructuralSkip(name) {
  return name === '_tags' || name === '_meta';
}

/**
 * Map a music-library-relative path under _tags to the real album path
 * MPD indexed (songs live only on the canonical album; tag leaves are
 * empty dont-walk stubs, often via ignored _meta/.../album).
 *
 * @param {string} musicRelPath e.g. NAS/gmk/files/_tags/genre/x/Album
 * @param {string} [mntRoot='/mnt']
 * @return {string|null} music-relative real album path, or null if none
 */
function resolveTagsLeafMusicPath(musicRelPath, mntRoot) {
  if (!musicRelPath || musicRelPath.indexOf('/_tags/') < 0) {
    return null;
  }
  var root = mntRoot || '/mnt';
  var abs = path.join(root, musicRelPath);
  var real;
  var rootReal;
  try {
    real = fs.realpathSync(abs);
    rootReal = fs.realpathSync(root);
  } catch (e) {
    return null;
  }
  if (real.indexOf('/_meta/') >= 0) {
    var albumLink = path.join(real, 'album');
    try {
      if (fs.existsSync(albumLink)) {
        real = fs.realpathSync(albumLink);
      }
    } catch (e2) {
      /* keep real as _meta dir */
    }
  }
  var prefix = rootReal.endsWith('/') ? rootReal : rootReal + '/';
  if (real.indexOf(prefix) !== 0) {
    return null;
  }
  var out = real.slice(prefix.length);
  if (!out || out === musicRelPath) {
    return null;
  }
  if (out.indexOf('/_tags/') >= 0 || out.indexOf('/_meta/') >= 0) {
    return null;
  }
  return out;
}

/**
 * File URIs stored under prefix (prefix itself or a child path).
 * @param {string[]} fileUris
 * @param {string} prefix
 * @return {string[]}
 */
function filesUnderPrefix(fileUris, prefix) {
  var out = [];
  if (!prefix) {
    return out;
  }
  for (var i = 0; i < fileUris.length; i++) {
    var fileUri = fileUris[i];
    if (fileUri === prefix || fileUri.indexOf(prefix + '/') === 0) {
      out.push(fileUri);
    }
  }
  return out;
}

/**
 * Music-relative real path, or null.
 * @param {string} abs
 * @param {string} mntRoot
 * @return {string|null}
 */
function musicRelFromReal(abs, mntRoot) {
  var rootReal;
  var real;
  try {
    rootReal = fs.realpathSync(mntRoot);
    real = fs.realpathSync(abs);
  } catch (e) {
    return null;
  }
  var prefix = rootReal.endsWith('/') ? rootReal : rootReal + '/';
  if (real.indexOf(prefix) !== 0) {
    return null;
  }
  return real.slice(prefix.length);
}

/**
 * Directory under files/ that owns the songs for a canonical path.
 * @param {string} musicRel
 * @return {string}
 */
function albumRootOf(musicRel) {
  var marker = '/files/';
  var at = musicRel.indexOf(marker);
  if (at < 0) {
    return musicRel;
  }
  var rest = musicRel.slice(at + marker.length);
  var album = rest.split('/')[0];
  if (!album || album === '_tags' || album === '_meta') {
    return musicRel;
  }
  return musicRel.slice(0, at + marker.length) + album;
}

/**
 * Where a tag path lands in the canonical tree, if the path itself is a link
 * (disc symlink, or _meta album symlink). Null when the path is still a
 * directory under _tags.
 * @param {string} abs
 * @param {string} mntRoot
 * @return {string|null}
 */
function canonicalDirForAbs(abs, mntRoot) {
  var rel = musicRelFromReal(abs, mntRoot);
  if (!rel) {
    return null;
  }
  if (rel.indexOf('/_tags/') < 0 && rel.indexOf('/_meta/') < 0) {
    return rel;
  }
  var metaAt = rel.indexOf('/_meta/');
  if (metaAt < 0) {
    return null;
  }
  var tail = rel.slice(metaAt + '/_meta/'.length);
  var parts = tail.split('/');
  var albumName = parts[0];
  if (!albumName) {
    return null;
  }
  var rootReal = fs.realpathSync(mntRoot);
  var albumLink = path.join(rootReal, rel.slice(0, metaAt), '_meta', albumName, 'album');
  var canon;
  try {
    canon = fs.realpathSync(albumLink);
  } catch (e) {
    return null;
  }
  var prefix = rootReal.endsWith('/') ? rootReal : rootReal + '/';
  if (canon.indexOf(prefix) !== 0) {
    return null;
  }
  var canonRel = canon.slice(prefix.length);
  var rest = parts.slice(1);
  if (rest[0] === 'album') {
    rest = rest.slice(1);
  }
  if (rest.length) {
    return canonRel + '/' + rest.join('/');
  }
  return canonRel;
}

/**
 * Album roots referenced by a _tags directory that is not itself a canonical link.
 * Disc children expand to the whole album. Nested tag dirs are walked the same way.
 * @param {string} musicRel
 * @param {string} mntRoot
 * @param {Object<string, boolean>} seen
 * @param {number} depth
 * @return {string[]}
 */
function albumRootsUnderTag(musicRel, mntRoot, seen, depth) {
  if (depth > 8) {
    return [];
  }
  var abs = path.join(mntRoot, musicRel);
  var names;
  try {
    if (!fs.statSync(abs).isDirectory()) {
      return [];
    }
    names = fs.readdirSync(abs);
  } catch (e) {
    return [];
  }
  var found = [];
  for (var i = 0; i < names.length; i++) {
    var name = names[i];
    if (!name || name.charAt(0) === '.' || name === '_tags' || name === '_meta') {
      continue;
    }
    var childRel = musicRel + '/' + name;
    var childAbs = path.join(mntRoot, childRel);
    var landed = canonicalDirForAbs(childAbs, mntRoot);
    if (landed) {
      var root = albumRootOf(landed);
      if (!seen[root]) {
        seen[root] = true;
        found.push(root);
      }
      continue;
    }
    var nested = albumRootsUnderTag(childRel, mntRoot, seen, depth + 1);
    for (var j = 0; j < nested.length; j++) {
      found.push(nested[j]);
    }
  }
  return found;
}

/**
 * Directories scanFolder should walk for a folder enqueue.
 * Canonical paths stay as given. A _tags path becomes the canonical album
 * directories (or one disc directory) and never the tag path itself.
 * @param {string} musicRel
 * @param {string} mntRoot
 * @return {string[]}
 */
function tagEnqueuePrefixes(musicRel, mntRoot) {
  var root = mntRoot || '/mnt';
  if (!musicRel || musicRel.indexOf('/_tags/') < 0) {
    return musicRel ? [musicRel] : [];
  }
  var landed = canonicalDirForAbs(path.join(root, musicRel), root);
  if (landed) {
    return [landed];
  }
  return albumRootsUnderTag(musicRel, root, {}, 0);
}

/**
 * Songs to enqueue for a music-library path.
 * Canonical directories use the indexed file prefix as-is.
 * A _tags path with no indexed files resolves to canonical album prefixes:
 * one album plus a disc suffix when the path names them, otherwise every
 * distinct album under that tag bucket.
 * @param {string} musicRel
 * @param {string} mntRoot
 * @param {string[]} fileUris indexed file URIs (canonical paths only)
 * @return {string[]}
 */
function enqueueSongs(musicRel, mntRoot, fileUris) {
  var direct = filesUnderPrefix(fileUris, musicRel);
  if (direct.length) {
    return direct;
  }
  if (!musicRel || musicRel.indexOf('/_tags/') < 0) {
    return [];
  }
  var prefixes = tagEnqueuePrefixes(musicRel, mntRoot);
  var seen = {};
  var out = [];
  for (var i = 0; i < prefixes.length; i++) {
    var songs = filesUnderPrefix(fileUris, prefixes[i]);
    for (var j = 0; j < songs.length; j++) {
      if (!seen[songs[j]]) {
        seen[songs[j]] = true;
        out.push(songs[j]);
      }
    }
  }
  return out;
}

module.exports = {
  readPatterns: readPatterns,
  fnmatch: fnmatch,
  nameMatches: nameMatches,
  patternsForDir: patternsForDir,
  collectAncestorPatterns: collectAncestorPatterns,
  seedExcludePatterns: seedExcludePatterns,
  rememberReal: rememberReal,
  isStructuralSkip: isStructuralSkip,
  resolveTagsLeafMusicPath: resolveTagsLeafMusicPath,
  filesUnderPrefix: filesUnderPrefix,
  tagEnqueuePrefixes: tagEnqueuePrefixes,
  enqueueSongs: enqueueSongs
};
