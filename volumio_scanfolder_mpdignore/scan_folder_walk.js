'use strict';
/**
 * Directory walk used by unit tests and as the FS-recurse core of Volumio
 * scanFolder (iso / mpd lsinfo branches stay in index.js).
 *
 * When honorMpdignore is true, names matching inherited+.mpdignore patterns
 * are not entered and not listed in visitedPaths / visitedFiles.
 */

var fs = require('fs');
var path = require('path');
var mpdignore = require('./mpdignore');

/**
 * @typedef {object} WalkResult
 * @property {string[]} visitedDirs
 * @property {string[]} visitedFiles
 * @property {number} mpdignoreSkipped
 * @property {boolean} hitBudget
 */

/**
 * @param {string} rootAbs
 * @param {{honorMpdignore?: boolean, doneSet?: boolean, structuralSkip?: boolean, maxVisits?: number}} [opts]
 * @return {WalkResult}
 */
function walk(rootAbs, opts) {
  opts = opts || {};
  var honor = opts.honorMpdignore !== false;
  var useDoneSet = opts.doneSet !== false;
  var useStructural = opts.structuralSkip !== false;
  var maxVisits = opts.maxVisits || 0;
  var visitedDirs = [];
  var visitedFiles = [];
  var mpdignoreSkipped = 0;
  var hitBudget = false;
  var doneReals = {};

  function rec(absDir, exclude) {
    if (maxVisits && visitedDirs.length >= maxVisits) {
      hitBudget = true;
      return;
    }
    if (useDoneSet && mpdignore.rememberReal(doneReals, absDir)) {
      return;
    }
    visitedDirs.push(absDir);
    var seeded = honor ? mpdignore.seedExcludePatterns(absDir, exclude) : (exclude || []);
    var patterns = honor ? mpdignore.patternsForDir(absDir, seeded) : seeded;
    var names;
    try {
      names = fs.readdirSync(absDir);
    } catch (e) {
      return;
    }
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      if (useStructural && mpdignore.isStructuralSkip(name)) {
        mpdignoreSkipped += 1;
        continue;
      }
      if (honor && mpdignore.nameMatches(name, patterns)) {
        mpdignoreSkipped += 1;
        continue;
      }
      var child = path.join(absDir, name);
      var st;
      try {
        st = fs.statSync(child);
      } catch (e2) {
        continue;
      }
      if (st.isDirectory()) {
        rec(child, patterns);
      } else if (st.isFile()) {
        visitedFiles.push(child);
      }
    }
  }

  rec(rootAbs, []);
  return {
    visitedDirs: visitedDirs,
    visitedFiles: visitedFiles,
    mpdignoreSkipped: mpdignoreSkipped,
    hitBudget: hitBudget
  };
}

module.exports = { walk: walk };
