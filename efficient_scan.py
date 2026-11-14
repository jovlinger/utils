#!/usr/bin/env python3
"""Instrumented efficient library walk (todo:d6d78baa).

Policy (normative):
  - DFS
  - In each directory: real entries before symlinks
  - Sort within class: digit, letter, other (by name)
  - done-set of real abspaths; add on directory entry
  - Follow a symlink only if real target abspath not already in done-set
  - Follow cross-device symlink targets when not done

Observability (tunable via env):
  EFF_SCAN_ROOT   music root (default /mnt/NAS/gmk)
  EFF_SCAN_LOG    jsonl metrics path (default /tmp/efficient_scan.jsonl)
  EFF_SCAN_LEVEL  0=quiet summary, 1=milestones, 2=per-dir, 3=per-skip
  EFF_SCAN_EVERY  emit progress every N entries (default 500)
  EFF_SCAN_ALIAS_SKIP  0 (default). 1 is a NON-NORMATIVE CIFS experiment only;
                       it must still record _tags/_meta as directory entries.
                       Ticket AC forbids name-based wipe of those trees.

Library-health signals (no playback required):
  - unique audio files discovered
  - SoT-style _tags bucket children reached vs skipped
  - symlink skips due to done-set (circularity / alias avoidance)
  - peak RSS, elapsed, max stack depth, max files in one dir
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

AUDIO_EXT = (".flac", ".mp3", ".m4a", ".aac", ".wav", ".aiff", ".dsf", ".dff", ".ogg", ".wma")


def rss_kb() -> int:
    # Linux: ru_maxrss is KB on Linux
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def name_class(name: str) -> int:
    if not name:
        return 2
    ch = name[0]
    if ch.isdigit():
        return 0
    if ch.isalpha():
        return 1
    return 2


def sort_key(name: str) -> Tuple[int, str]:
    return (name_class(name), name.lower())


@dataclass
class Metrics:
    root: str
    t0: float = field(default_factory=time.time)
    dirs_entered_real: int = 0
    dirs_entered_via_symlink: int = 0
    symlinks_seen: int = 0
    symlinks_followed: int = 0
    symlinks_skipped_done: int = 0
    symlinks_skipped_broken: int = 0
    audio_files: int = 0
    audio_unique_realpaths: int = 0
    other_files: int = 0
    max_depth: int = 0
    max_dir_entries: int = 0
    done_set_size: int = 0
    peak_rss_kb: int = 0
    errors: int = 0
    # _tags taxonomy health
    tags_bucket_children: Dict[str, int] = field(default_factory=dict)
    tags_bucket_skipped_all: Dict[str, int] = field(default_factory=dict)
    tags_bucket_followed: Dict[str, int] = field(default_factory=dict)
    path_under_tags_audio: int = 0
    alias_roots_skipped: int = 0
    alias_roots_listed: int = 0
    last_path: str = ""

    def touch_rss(self) -> None:
        self.peak_rss_kb = max(self.peak_rss_kb, rss_kb())

    def elapsed(self) -> float:
        return round(time.time() - self.t0, 3)


ALIAS_DIR_NAMES = frozenset({"_tags", "_meta"})


class EfficientScan:
    def __init__(
        self,
        root: str,
        log_path: str,
        level: int,
        every: int,
        alias_skip: bool = False,
    ) -> None:
        self.root = os.path.abspath(root)
        self.log_path = log_path
        self.level = level
        self.every = max(1, every)
        self.alias_skip = alias_skip
        self.done: Set[str] = set()
        self.audio_real: Set[str] = set()
        # Logical paths for contract tests (lsinfo stand-in / visit trace).
        self.directory_entries: Set[str] = set()
        self.song_logical_paths: List[str] = []
        self.visit_order: List[str] = []
        self.m = Metrics(root=self.root)
        self._n_events = 0
        self._log_fp = open(self.log_path, "w", encoding="utf-8")

    def close(self) -> None:
        self._emit("final", {"metrics": asdict(self.m), "done_set_size": len(self.done)})
        self._log_fp.close()

    def _emit(self, kind: str, payload: Dict[str, object]) -> None:
        self.m.touch_rss()
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": kind,
            "elapsed_s": self.m.elapsed(),
            "rss_kb": rss_kb(),
            "peak_rss_kb": self.m.peak_rss_kb,
            "done_set": len(self.done),
            "audio_files": self.m.audio_files,
            "audio_unique": len(self.audio_real),
            "sym_skip_done": self.m.symlinks_skipped_done,
            "sym_followed": self.m.symlinks_followed,
            **payload,
        }
        self._log_fp.write(json.dumps(row, ensure_ascii=True) + "\n")
        self._log_fp.flush()
        if self.level >= 1 and kind in ("milestone", "final", "start", "health"):
            print(json.dumps(row, ensure_ascii=True), flush=True)
        elif self.level >= 2 and kind == "dir":
            print(json.dumps(row, ensure_ascii=True), flush=True)
        elif self.level >= 3 and kind.startswith("skip"):
            print(json.dumps(row, ensure_ascii=True), flush=True)

    def _progress(self) -> None:
        self._n_events += 1
        if self._n_events % self.every == 0:
            self._emit(
                "milestone",
                {
                    "event_n": self._n_events,
                    "last_path": self.m.last_path,
                    "max_depth": self.m.max_depth,
                    "max_dir_entries": self.m.max_dir_entries,
                },
            )

    def _classify_dirents(self, abs_dir: str) -> Tuple[List[str], List[str]]:
        """Return (real_names, symlink_names) sorted by policy."""
        try:
            names = os.listdir(abs_dir)
        except OSError as e:
            self.m.errors += 1
            self._emit("error", {"path": abs_dir, "err": str(e)})
            return [], []
        self.m.max_dir_entries = max(self.m.max_dir_entries, len(names))
        real_n: List[str] = []
        sym_n: List[str] = []
        for name in names:
            if name in (".", ".."):
                continue
            p = os.path.join(abs_dir, name)
            try:
                if os.path.islink(p):
                    sym_n.append(name)
                else:
                    real_n.append(name)
            except OSError:
                self.m.errors += 1
                continue
        real_n.sort(key=sort_key)
        sym_n.sort(key=sort_key)
        return real_n, sym_n

    def _maybe_alias_list_only(self, abs_dir: str, logical: str, depth: int) -> bool:
        """List _tags buckets for health, but do not descend (CIFS reified aliases)."""
        base = os.path.basename(abs_dir.rstrip("/"))
        rel = os.path.relpath(abs_dir, self.root).replace("\\", "/")
        if not self.alias_skip or base not in ALIAS_DIR_NAMES:
            return False
        # Only treat root-level and per-album alias dirs as skip bodies.
        self.m.alias_roots_skipped += 1
        self.m.last_path = logical
        if rel == "_tags" or base == "_tags":
            try:
                names = sorted(os.listdir(abs_dir), key=sort_key)
            except OSError as e:
                self.m.errors += 1
                self._emit("error", {"path": abs_dir, "err": str(e)})
                return True
            self.m.alias_roots_listed += 1
            if rel == "_tags":
                for name in names:
                    self.m.tags_bucket_children[name] = (
                        self.m.tags_bucket_children.get(name, 0) + 1
                    )
            self._emit(
                "alias_skip",
                {
                    "logical": logical,
                    "rel": rel,
                    "listed": len(names),
                    "buckets": sorted(self.m.tags_bucket_children.keys()),
                    "depth": depth,
                },
            )
        else:
            self._emit("alias_skip", {"logical": logical, "rel": rel, "depth": depth})
        self._progress()
        return True

    def _record_dir_entry(self, logical: str) -> None:
        key = logical if logical.startswith("/") else ("/" + logical if logical else "")
        if key == "":
            key = "/"
        self.directory_entries.add(key)
        self.visit_order.append(key)

    def _enter_dir(self, abs_dir: str, via_symlink: bool, depth: int, logical: str) -> None:
        # Always record the directory entry (lsinfo line), including alias_skip.
        self._record_dir_entry(logical)
        if self._maybe_alias_list_only(abs_dir, logical, depth):
            # Still mark realpath done so later symlink follows skip.
            try:
                self.done.add(os.path.realpath(abs_dir))
            except OSError:
                pass
            self.m.done_set_size = len(self.done)
            return
        real = os.path.realpath(abs_dir)
        if real in self.done:
            # Directory entry already recorded; do not descend or re-index songs.
            self._emit("skip_dir_done", {"path": abs_dir, "real": real, "logical": logical})
            return
        self.done.add(real)
        self.m.done_set_size = len(self.done)
        if via_symlink:
            self.m.dirs_entered_via_symlink += 1
        else:
            self.m.dirs_entered_real += 1
        self.m.max_depth = max(self.m.max_depth, depth)
        self.m.last_path = logical
        if self.level >= 2:
            self._emit(
                "dir",
                {
                    "logical": logical,
                    "real": real,
                    "via_symlink": via_symlink,
                    "depth": depth,
                },
            )
        self._walk_dir(abs_dir, depth, logical)

    def _handle_audio(self, abs_path: str, logical: str) -> None:
        self.m.audio_files += 1
        log = logical if logical.startswith("/") else ("/" + logical)
        self.song_logical_paths.append(log)
        try:
            real = os.path.realpath(abs_path)
        except OSError:
            real = abs_path
        if real not in self.audio_real:
            self.audio_real.add(real)
            self.m.audio_unique_realpaths = len(self.audio_real)
        if "/_tags/" in logical.replace("\\", "/"):
            self.m.path_under_tags_audio += 1
        self.m.last_path = logical
        self._progress()

    def _walk_dir(self, abs_dir: str, depth: int, logical: str) -> None:
        real_n, sym_n = self._classify_dirents(abs_dir)
        # Track top-level _tags bucket children only (not per-album _tags)
        rel = os.path.relpath(abs_dir, self.root).replace("\\", "/")
        if rel == "_tags":
            for name in real_n + sym_n:
                self.m.tags_bucket_children[name] = self.m.tags_bucket_children.get(name, 0) + 1

        # 1) real entries first
        for name in real_n:
            p = os.path.join(abs_dir, name)
            log = logical.rstrip("/") + "/" + name
            try:
                if os.path.isdir(p):
                    self._enter_dir(p, via_symlink=False, depth=depth + 1, logical=log)
                elif os.path.isfile(p):
                    if name.lower().endswith(AUDIO_EXT):
                        self._handle_audio(p, log)
                    else:
                        self.m.other_files += 1
            except OSError as e:
                self.m.errors += 1
                self._emit("error", {"path": p, "err": str(e)})

        # 2) symlinks after
        for name in sym_n:
            p = os.path.join(abs_dir, name)
            log = logical.rstrip("/") + "/" + name
            self.m.symlinks_seen += 1
            try:
                target = os.path.realpath(p)
            except OSError as e:
                self.m.symlinks_skipped_broken += 1
                self.m.errors += 1
                self._emit("skip_broken", {"path": p, "err": str(e)})
                continue
            if not os.path.exists(p):
                self.m.symlinks_skipped_broken += 1
                self._emit("skip_broken", {"path": p, "target": target})
                continue
            # bucket accounting under _tags/<bucket>
            parts = log.replace("\\", "/").split("/")
            if len(parts) >= 3 and parts[0] == "" and "_tags" in parts:
                pass
            if "/_tags/" in ("/" + log.replace("\\", "/")):
                segs = [s for s in log.replace("\\", "/").split("/") if s]
                if len(segs) >= 2 and segs[0] == "_tags" or (len(segs) >= 3 and "_tags" in segs):
                    try:
                        ti = segs.index("_tags")
                        if ti + 1 < len(segs):
                            bucket = segs[ti + 1]
                            if target in self.done:
                                self.m.tags_bucket_skipped_all[bucket] = (
                                    self.m.tags_bucket_skipped_all.get(bucket, 0) + 1
                                )
                            else:
                                self.m.tags_bucket_followed[bucket] = (
                                    self.m.tags_bucket_followed.get(bucket, 0) + 1
                                )
                    except ValueError:
                        pass

            if target in self.done:
                self.m.symlinks_skipped_done += 1
                # Contract: still record directory entry; do not descend/songs.
                if os.path.isdir(p):
                    self._record_dir_entry(log)
                if self.level >= 3:
                    self._emit(
                        "skip_done",
                        {"path": p, "target": target, "logical": log},
                    )
                self._progress()
                continue

            self.m.symlinks_followed += 1
            if os.path.isdir(p):
                # Enter via symlink: done-set gains realpath on entry
                self._enter_dir(p, via_symlink=True, depth=depth + 1, logical=log)
            elif os.path.isfile(p) and name.lower().endswith(AUDIO_EXT):
                # rare: symlink to file
                self._handle_audio(p, log)
            self._progress()

    def run(self) -> Metrics:
        self._emit("start", {"root": self.root, "level": self.level, "every": self.every})
        if not os.path.isdir(self.root):
            self.m.errors += 1
            self._emit("error", {"err": "root_missing", "root": self.root})
            return self.m
        # Root itself is a real directory entry
        self._enter_dir(self.root, via_symlink=False, depth=0, logical="")
        health = self.health()
        self._emit("health", health)
        return self.m

    def health(self) -> Dict[str, object]:
        """Library health without playback."""
        expected_buckets = ["album", "artist", "genre", "year", "various", "NOTAGS"]
        children = sorted(self.m.tags_bucket_children.keys())
        return {
            "ok_unique_audio_gt_1000": len(self.audio_real) > 1000,
            "unique_audio": len(self.audio_real),
            "audio_seen_total": self.m.audio_files,
            "duplicate_path_visits": self.m.audio_files - len(self.audio_real),
            "tags_buckets_seen": children,
            "tags_buckets_expected": expected_buckets,
            "tags_buckets_missing": [b for b in expected_buckets if b not in self.m.tags_bucket_children],
            "tags_bucket_child_count": len(children),
            "tags_richness_ok": len(children) >= 4,  # album/artist/genre/year at minimum
            "symlinks_skipped_done": self.m.symlinks_skipped_done,
            "symlinks_followed": self.m.symlinks_followed,
            "path_under_tags_audio": self.m.path_under_tags_audio,
            "alias_roots_skipped": self.m.alias_roots_skipped,
            "alias_skip_enabled": self.alias_skip,
            "peak_rss_kb": self.m.peak_rss_kb,
            "elapsed_s": self.m.elapsed(),
            "errors": self.m.errors,
            "verdict": (
                "HEALTHY"
                if len(self.audio_real) > 1000
                and (len(children) >= 4 or not self.alias_skip)
                else "UNHEALTHY"
            ),
        }


def sot_snapshot(sot_root: str) -> Dict[str, object]:
    tags = os.path.join(sot_root, "_tags")
    buckets: Dict[str, int] = {}
    if os.path.isdir(tags):
        for name in sorted(os.listdir(tags)):
            p = os.path.join(tags, name)
            if os.path.isdir(p):
                try:
                    buckets[name] = len(os.listdir(p))
                except OSError:
                    buckets[name] = -1
    albums = 0
    audio = 0
    if os.path.isdir(sot_root):
        for name in os.listdir(sot_root):
            if name.startswith("_"):
                continue
            p = os.path.join(sot_root, name)
            if not os.path.isdir(p) or os.path.islink(p):
                continue
            albums += 1
            for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
                dirnames[:] = [d for d in dirnames if d not in ("_tags", "_meta")]
                audio += sum(1 for f in filenames if f.lower().endswith(AUDIO_EXT))
    return {
        "sot_root": sot_root,
        "sot_tag_buckets": buckets,
        "sot_tag_bucket_count": len(buckets),
        "sot_album_dirs": albums,
        "sot_audio_nofollow": audio,
        "sot_tags_richness_ok": len(buckets) >= 4,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Instrumented efficient library scan")
    ap.add_argument(
        "--root",
        default=os.environ.get("EFF_SCAN_ROOT", "/mnt/NAS/gmk"),
        help="music root to walk",
    )
    ap.add_argument(
        "--sot",
        default=os.environ.get("EFF_SCAN_SOT", ""),
        help="optional Source-of-Truth root for health compare",
    )
    ap.add_argument(
        "--log",
        default=os.environ.get("EFF_SCAN_LOG", "/tmp/efficient_scan.jsonl"),
    )
    ap.add_argument(
        "--level",
        type=int,
        default=int(os.environ.get("EFF_SCAN_LEVEL", "1")),
    )
    ap.add_argument(
        "--every",
        type=int,
        default=int(os.environ.get("EFF_SCAN_EVERY", "500")),
    )
    ap.add_argument(
        "--alias-skip",
        dest="alias_skip",
        action="store_true",
        default=os.environ.get("EFF_SCAN_ALIAS_SKIP", "0") not in ("0", "false", "no"),
        help="NON-NORMATIVE: list-only descend into _tags/_meta (CIFS experiment)",
    )
    ap.add_argument(
        "--no-alias-skip",
        dest="alias_skip",
        action="store_false",
        help="descend into _tags/_meta (local symlink FS / stress test)",
    )
    args = ap.parse_args(argv)

    sot: Dict[str, object] = {}
    if args.sot:
        sot = sot_snapshot(args.sot)
        print(json.dumps({"kind": "sot", **sot}, ensure_ascii=True), flush=True)

    scan = EfficientScan(
        args.root, args.log, args.level, args.every, alias_skip=args.alias_skip
    )
    try:
        scan.run()
    finally:
        health = scan.health()
        if sot:
            health["sot"] = sot
            health["compare_unique_vs_sot"] = {
                "scan_unique": health.get("unique_audio"),
                "sot_audio_nofollow": sot.get("sot_audio_nofollow"),
                "delta": int(health.get("unique_audio") or 0)
                - int(sot.get("sot_audio_nofollow") or 0),
            }
            health["compare_tags_buckets"] = {
                "scan_buckets": health.get("tags_buckets_seen"),
                "sot_buckets": list((sot.get("sot_tag_buckets") or {}).keys()),
            }
        print(json.dumps({"kind": "summary", "health": health, "log": args.log}, ensure_ascii=True), flush=True)
        scan.close()
    return 0 if health.get("verdict") == "HEALTHY" else 2


if __name__ == "__main__":
    sys.exit(main())
