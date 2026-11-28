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

module.exports = {
  readPatterns: readPatterns,
  fnmatch: fnmatch,
  nameMatches: nameMatches,
  patternsForDir: patternsForDir,
  collectAncestorPatterns: collectAncestorPatterns,
  seedExcludePatterns: seedExcludePatterns
};
