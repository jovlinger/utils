# Agent Notes -- binlinks

Command catalog and `make binlinks`: [`README.md`](README.md).

- Do not symlink `ingest.py` here; `ingest` must run the shell wrapper
  (`shadup/ingest.sh`) only (handles rw/ro remount).
- Do not symlink `dedup.py` here; `dedup` must run `dedup/dedup.sh` (venv +
  rw/ro remount).
