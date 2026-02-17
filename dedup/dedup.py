#!/usr/bin/env python3
"""
shasrv - Content-addressed file storage using SHA-256 deduplication.

This utility creates a deduplicated storage structure where:
1. Each file is stored under its SHA256 hash in <target>/data/<sha[:2]>/<sha>
2. Symlinks are created in <target>/files/<path> pointing to the actual file
3. Multiple files with the same content (same SHA256) share the same storage

Modes:
  (default)  Deduplicate files from sources into a target store
  --fix      Fix relative symlinks after files have been moved within files/
"""

import os
import hashlib
import shutil
from pathlib import Path
from typing import Set, Dict, Optional, List
import argparse
import sys
import re


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _calculate_sha256(file_path: Path, verbose: bool = False) -> str:
    """Calculate SHA256 hash of a file."""
    if verbose:
        print(f"sha256 summing {file_path}")

    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_directory(path: Path) -> None:
    """Ensure directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)


def _create_symlink(target_path: Path, link_path: Path) -> None:
    """Create a symlink, handling the case where the target is relative."""
    # Make the symlink target relative to the link's directory
    try:
        relative_target = os.path.relpath(target_path, link_path.parent)
        link_path.symlink_to(relative_target)
    except OSError as e:
        if e.errno == 17:  # File exists
            # Remove existing symlink and recreate
            link_path.unlink()
            relative_target = os.path.relpath(target_path, link_path.parent)
            link_path.symlink_to(relative_target)
        else:
            raise


def process_file(
    source_file: Path,
    source_root: Path,
    target_dir: Path,
    processed_hashes: Set[str],
    used_paths: Set[str],
    content_to_suffix: Dict[str, str],
    verbose: bool = False,
    dryrun: bool = False,
    remove_source: bool = False,
) -> str:
    """
    Process a single file: calculate hash, copy to data directory, create symlink.

    Args:
        source_file: Path to the source file
        source_root: Root of the source directory (for relative path calculation)
        target_dir: Target directory for deduplicated storage
        processed_hashes: Set of already processed hashes (for optimization)
        used_paths: Set of already used symlink paths
        content_to_suffix: Mapping from file hash to assigned suffix
        verbose: Whether to print progress information
        dryrun: Whether to skip actual file operations
        remove_source: Whether to remove source file after successful processing

    Returns:
        The SHA256 hash of the file
    """
    # Calculate SHA256 hash
    file_hash = _calculate_sha256(source_file, verbose)

    # Define paths
    data_dir = target_dir / "data"
    files_dir = target_dir / "files"
    hash_prefix = file_hash[:2]
    hash_dir = data_dir / hash_prefix
    hash_file = hash_dir / file_hash

    # Create directories (skip in dryrun)
    if not dryrun:
        _ensure_directory(hash_dir)

    # Copy file to data directory if not already there (skip in dryrun)
    if file_hash not in processed_hashes:
        if not dryrun:
            shutil.copy2(source_file, hash_file)
        processed_hashes.add(file_hash)

    # Create symlink in files directory preserving the complete relative path structure
    relative_path = source_file.relative_to(source_root)
    symlink_path = files_dir / relative_path

    # Handle path conflicts by adding numeric suffixes
    original_path = str(symlink_path)
    if original_path in used_paths:
        # Path already exists, need to add suffix
        if file_hash in content_to_suffix:
            # Content already stored, no-op - don't create another symlink
            if remove_source and not dryrun:
                source_file.unlink()
            return file_hash

        # Find next available suffix
        suffix_num = 1
        while f"{original_path}.{suffix_num}" in used_paths:
            suffix_num += 1

        symlink_path = Path(f"{original_path}.{suffix_num}")
        content_to_suffix[file_hash] = f".{suffix_num}"
    else:
        # First occurrence of this path - add to content mapping
        content_to_suffix[file_hash] = ""

    # Add path to used paths
    used_paths.add(str(symlink_path))

    # Create symlink (skip in dryrun)
    if not dryrun:
        _ensure_directory(symlink_path.parent)
        _create_symlink(hash_file, symlink_path)

        # Verify that the symlink points to a file with the expected SHA256 hash
        try:
            symlink_hash = _calculate_sha256(symlink_path, verbose)
            assert (
                symlink_hash == file_hash
            ), f"Hash mismatch: expected {file_hash}, got {symlink_hash} for {symlink_path}"
        except Exception as e:
            raise RuntimeError(f"Verification failed for {symlink_path}: {e}")

    # Remove source file after successful processing
    if remove_source and not dryrun:
        source_file.unlink()

    return file_hash


def _process_single_file(
    source_file: Path,
    source_root: Path,
    target_dir: Path,
    processed_hashes: Set[str],
    used_paths: Set[str],
    content_to_suffix: Dict[str, str],
    verbose: bool = False,
    dryrun: bool = False,
    remove_source: bool = False,
) -> bool:
    """
    Process a single file and return True if successful.
    """
    try:
        file_hash = process_file(
            source_file,
            source_root,
            target_dir,
            processed_hashes,
            used_paths,
            content_to_suffix,
            verbose,
            dryrun,
            remove_source,
        )
        if verbose:
            relative_path = source_file.relative_to(source_root)
            files_dir = target_dir / "files"
            symlink_path = files_dir / relative_path
            print(f"Processed: {source_file} -> {file_hash[:10]}... -> {symlink_path}")
        return True
    except Exception as e:
        print(f"Error processing {source_file}: {e}", file=sys.stderr)
        return False


def deduplicate_sources(
    sources: List[Path],
    target_dir: Path,
    verbose: bool = False,
    dryrun: bool = False,
    remove_source: bool = False,
) -> Dict[str, int]:
    """
    Deduplicate files from multiple source directories and/or files.

    Path preservation behavior:
    - If source is a file: preserves the filename only
    - If source is a directory: preserves the directory name and structure

    Args:
        sources: List of source directories and/or files to process
        target_dir: Target directory for deduplicated storage
        verbose: Whether to print progress information
        dryrun: Whether to skip actual file operations
        remove_source: Whether to remove source files after successful processing

    Returns:
        Dictionary with statistics
    """
    if not sources:
        raise ValueError("At least one source must be provided")

    if not dryrun:
        _ensure_directory(target_dir)

    processed_hashes: Set[str] = set()
    used_paths: Set[str] = set()
    content_to_suffix: Dict[str, str] = {}
    files_processed = 0

    for source in sources:
        if not source.exists():
            print(f"Warning: Source does not exist: {source}", file=sys.stderr)
            continue

        if source.is_file():
            if _process_single_file(
                source,
                source.parent,
                target_dir,
                processed_hashes,
                used_paths,
                content_to_suffix,
                verbose,
                dryrun,
                remove_source,
            ):
                files_processed += 1
        elif source.is_dir():
            source_parent = source.parent
            for root, dirs, files in os.walk(source):
                root_path = Path(root)
                for file_name in files:
                    source_file = root_path / file_name
                    if _process_single_file(
                        source_file,
                        source_parent,
                        target_dir,
                        processed_hashes,
                        used_paths,
                        content_to_suffix,
                        verbose,
                        dryrun,
                        remove_source,
                    ):
                        files_processed += 1
            # Clean up empty directories if removing sources
            if remove_source and not dryrun:
                for root, dirs, files in os.walk(source, topdown=False):
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass  # directory not empty or other error
        else:
            print(
                f"Warning: Source is neither file nor directory: {source}",
                file=sys.stderr,
            )
            continue

    unique_files = len(processed_hashes)
    duplicates_saved = files_processed - unique_files

    return {
        "files_processed": files_processed,
        "unique_files": unique_files,
        "duplicates_saved": duplicates_saved,
    }


def deduplicate_directory(
    source_dir: Path, target_dir: Path, verbose: bool = False, dryrun: bool = False
) -> Dict[str, int]:
    """Legacy wrapper for backward compatibility."""
    return deduplicate_sources([source_dir], target_dir, verbose, dryrun)


def fix_symlinks(
    target_dir: Path, verbose: bool = False, dryrun: bool = False
) -> Dict[str, int]:
    """
    Fix relative symlinks in files/ after they have been moved.

    Scans all symlinks under <target_dir>/files/. For each one, extracts the
    SHA-256 hash from the symlink target, verifies the data file exists, and
    recalculates the correct relative path from the symlink's current location.

    Args:
        target_dir: Root of the content-addressed store (contains data/ and files/)
        verbose: Whether to print progress information
        dryrun: Whether to skip actual symlink updates

    Returns:
        Dictionary with statistics: checked, fixed, skipped, broken
    """
    files_dir = target_dir / "files"
    data_dir = target_dir / "data"

    if not files_dir.exists():
        raise ValueError(f"No files/ directory in {target_dir}")
    if not data_dir.exists():
        raise ValueError(f"No data/ directory in {target_dir}")

    checked = 0
    fixed = 0
    skipped = 0
    broken = 0

    for path in sorted(files_dir.rglob("*")):
        if not path.is_symlink():
            continue
        checked += 1

        current_target = os.readlink(path)
        target_parts = Path(current_target).parts

        # Extract hash: last component should be a 64-char hex string
        hash_candidate = target_parts[-1]
        if not SHA256_RE.match(hash_candidate):
            if verbose:
                print(f"Skip (not a hash target): {path} -> {current_target}")
            skipped += 1
            continue

        sha_hash = hash_candidate
        hash_prefix = sha_hash[:2]

        # Verify the data file exists
        data_file = data_dir / hash_prefix / sha_hash
        if not data_file.exists():
            print(
                f"Warning: data file missing: {data_file} (from {path})",
                file=sys.stderr,
            )
            broken += 1
            continue

        # Calculate the correct relative path from symlink location to data file
        correct_relative = os.path.relpath(data_file, path.parent)

        if current_target == correct_relative:
            if verbose:
                print(f"OK: {path}")
            continue

        if verbose:
            print(f"Fix: {path}")
            print(f"  was: {current_target}")
            print(f"  now: {correct_relative}")

        if not dryrun:
            path.unlink()
            path.symlink_to(correct_relative)
        fixed += 1

    return {"checked": checked, "fixed": fixed, "skipped": skipped, "broken": broken}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="shasrv - Content-addressed file storage with SHA-256 deduplication"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print verbose output"
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Calculate without performing actual file operations",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Fix mode: repair relative symlinks in files/ after moving them",
    )
    parser.add_argument(
        "--remove-source",
        action="store_true",
        help="Remove source files after successful dedup (like old ingest.sh)",
    )
    parser.add_argument(
        "positional",
        nargs="*",
        type=Path,
        help="In default mode: <sources...> <target_dir>.  In --fix mode: <target_dir>",
    )

    args = parser.parse_args()

    if args.fix:
        # Fix mode: single positional argument = target_dir
        if len(args.positional) != 1:
            parser.error("--fix mode requires exactly one argument: <target_dir>")

        target_dir = args.positional[0]

        try:
            stats = fix_symlinks(target_dir, args.verbose, args.dryrun)
            prefix = "Dry run" if args.dryrun else "Fix"
            print(f"{prefix} complete!")
            print(f"Symlinks checked: {stats['checked']}")
            print(f"Symlinks fixed:   {stats['fixed']}")
            print(f"Symlinks skipped: {stats['skipped']}")
            print(f"Broken (missing): {stats['broken']}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Dedup mode: <sources...> <target_dir>
        if len(args.positional) < 2:
            parser.error(
                "Dedup mode requires at least two arguments: <source> [source...] <target_dir>"
            )

        sources = args.positional[:-1]
        target_dir = args.positional[-1]

        try:
            stats = deduplicate_sources(
                sources, target_dir, args.verbose, args.dryrun, args.remove_source
            )

            prefix = "Dry run" if args.dryrun else "Deduplication"
            print(f"{prefix} complete!")
            print(f"Files processed: {stats['files_processed']}")
            print(f"Unique files:    {stats['unique_files']}")
            print(f"Duplicates saved: {stats['duplicates_saved']}")
            if args.remove_source:
                print(f"Source files removed: {stats['files_processed']}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
