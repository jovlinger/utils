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

module.exports = {
  readPatterns: readPatterns,
  fnmatch: fnmatch,
  nameMatches: nameMatches,
  patternsForDir: patternsForDir,
  collectAncestorPatterns: collectAncestorPatterns,
  seedExcludePatterns: seedExcludePatterns,
  rememberReal: rememberReal,
  isStructuralSkip: isStructuralSkip,
  resolveTagsLeafMusicPath: resolveTagsLeafMusicPath
};
