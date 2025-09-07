#!/usr/bin/env python3
"""
File deduplication utility for Merkle FUSE filesystem.

This utility takes a source directory and creates a deduplicated storage structure
in a target directory where:
1. Each file is stored under its SHA256 hash in <target>/data/<sha[:2]>/<sha>
2. Symlinks are created in <target>/files/<path> pointing to the actual file
3. Multiple files with the same content (same SHA256) share the same storage
"""

import os
import hashlib
import shutil
from pathlib import Path
from typing import Set, Dict, Optional, List
import argparse
import sys


def _calculate_sha256(file_path: Path, verbose: bool = False) -> str:
    """Calculate SHA256 hash of a file."""
    if verbose:
        print(f"sha256 summing {file_path}")
    
    with open(file_path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


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


def process_file(source_file: Path, source_root: Path, target_dir: Path, processed_hashes: Set[str], used_paths: Set[str], content_to_suffix: Dict[str, str], verbose: bool = False, dryrun: bool = False) -> str:
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
            assert symlink_hash == file_hash, f"Hash mismatch: expected {file_hash}, got {symlink_hash} for {symlink_path}"
        except Exception as e:
            raise RuntimeError(f"Verification failed for {symlink_path}: {e}")
    
    return file_hash


def _process_single_file(source_file: Path, source_root: Path, target_dir: Path, processed_hashes: Set[str], used_paths: Set[str], content_to_suffix: Dict[str, str], verbose: bool = False, dryrun: bool = False) -> bool:
    """
    Process a single file and return True if successful.
    
    Args:
        source_file: Path to the source file
        source_root: Root directory for relative path calculation
        target_dir: Target directory for deduplicated storage
        processed_hashes: Set of already processed hashes
        used_paths: Set of already used symlink paths
        content_to_suffix: Mapping from file hash to assigned suffix
        verbose: Whether to print progress information
        dryrun: Whether to skip actual file operations
    
    Returns:
        True if file was processed successfully, False otherwise
    """
    try:
        file_hash = process_file(source_file, source_root, target_dir, processed_hashes, used_paths, content_to_suffix, verbose, dryrun)
        if verbose:
            # Calculate the symlink path for display
            relative_path = source_file.relative_to(source_root)
            files_dir = target_dir / "files"
            symlink_path = files_dir / relative_path
            
            # Handle path conflicts for display (may be incorrect in dryrun mode)
            original_path = str(symlink_path)
            if original_path in used_paths:
                if file_hash in content_to_suffix:
                    # Content already stored, show original path
                    display_path = original_path
                else:
                    # Find next available suffix for display
                    suffix_num = 1
                    while f"{original_path}.{suffix_num}" in used_paths:
                        suffix_num += 1
                    display_path = f"{original_path}.{suffix_num}"
            else:
                display_path = original_path
            
            print(f"Processed: {source_file} -> {file_hash[:10]} -> {display_path}")
        return True
    except Exception as e:
        print(f"Error processing {source_file}: {e}", file=sys.stderr)
        return False


def deduplicate_sources(sources: List[Path], target_dir: Path, verbose: bool = False, dryrun: bool = False) -> Dict[str, int]:
    """
    Deduplicate files from multiple source directories and/or files.
    
    Path preservation behavior:
    - If source is a file: preserves the filename only (e.g., /src/a/b.txt → dst/files/b.txt)
    - If source is a directory: preserves the directory name and structure 
      (e.g., /src/a/b/ → dst/files/b/x, dst/files/b/y where b contains files x, y)
    
    Args:
        sources: List of source directories and/or files to process
        target_dir: Target directory for deduplicated storage
        verbose: Whether to print progress information
        dryrun: Whether to skip actual file operations (calculate paths and hashes only)
    
    Returns:
        Dictionary with statistics: {'files_processed': int, 'unique_files': int, 'duplicates_saved': int}
    """
    if not sources:
        raise ValueError("At least one source must be provided")
    
    # Ensure target directory exists (skip in dryrun)
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
            # Process single file - use parent directory as root so filename is preserved
            if _process_single_file(source, source.parent, target_dir, processed_hashes, used_paths, content_to_suffix, verbose, dryrun):
                files_processed += 1
        elif source.is_dir():
            # Process directory - use parent of source directory as root so directory name is preserved
            source_parent = source.parent
            for root, dirs, files in os.walk(source):
                root_path = Path(root)
                
                for file_name in files:
                    source_file = root_path / file_name
                    if _process_single_file(source_file, source_parent, target_dir, processed_hashes, used_paths, content_to_suffix, verbose, dryrun):
                        files_processed += 1
        else:
            print(f"Warning: Source is neither file nor directory: {source}", file=sys.stderr)
            continue
    
    unique_files = len(processed_hashes)
    duplicates_saved = files_processed - unique_files
    
    return {
        'files_processed': files_processed,
        'unique_files': unique_files,
        'duplicates_saved': duplicates_saved
    }


def deduplicate_directory(source_dir: Path, target_dir: Path, verbose: bool = False, dryrun: bool = False) -> Dict[str, int]:
    """
    Deduplicate all files in a source directory (legacy function for backward compatibility).
    
    Args:
        source_dir: Source directory to process
        target_dir: Target directory for deduplicated storage
        verbose: Whether to print progress information
        dryrun: Whether to skip actual file operations
    
    Returns:
        Dictionary with statistics: {'files_processed': int, 'unique_files': int, 'duplicates_saved': int}
    """
    return deduplicate_sources([source_dir], target_dir, verbose, dryrun)


def main():
    """Main entry point for the deduplication utility."""
    parser = argparse.ArgumentParser(
        description="Deduplicate files using SHA256 hashing and symlinks"
    )
    parser.add_argument(
        "sources",
        nargs="+",
        type=Path,
        help="Source directories and/or files to deduplicate (at least one required)"
    )
    parser.add_argument(
        "target_dir", 
        type=Path,
        help="Target directory for deduplicated storage"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print verbose output"
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Calculate paths and hashes without performing actual file operations"
    )
    
    args = parser.parse_args()
    
    # Validate that we have at least one source
    if len(args.sources) < 1:
        parser.error("At least one source must be provided")
    
    try:
        stats = deduplicate_sources(args.sources, args.target_dir, args.verbose, args.dryrun)
        
        if args.dryrun:
            print(f"Dry run complete!")
        else:
            print(f"Deduplication complete!")
        print(f"Files processed: {stats['files_processed']}")
        print(f"Unique files: {stats['unique_files']}")
        print(f"Duplicates saved: {stats['duplicates_saved']}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
