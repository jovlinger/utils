"""
Merkle FUSE filesystem implementation.

This module contains the main filesystem class that implements the FUSE interface
using a merkle tree for storage.
"""

import os
import errno
import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

from mfusepy import Operations


class FileHandle:
    """File handle for tracking open files."""
    
    def __init__(self, path: str, flags: int, mode: str):
        self.path = path          # Full path to file
        self.flags = flags        # Open flags (O_RDONLY, O_WRONLY, O_RDWR, etc.)
        self.mode = mode          # 'r', 'w', 'a', etc.
        self.position = 0         # Current read/write position
        self.file_hash = None     # SHA256 hash of the file content
        # self.parent_hash = None   # parent_directory_hash to allow consistent reads ? 
        self.is_directory = False # Whether this is a directory handle
        # self.temp_data = None     # For write operations: temporary data buffer


class MerkleFuseFS(Operations):
    """
    Merkle FUSE filesystem implementation.
    
    This filesystem stores all data in an immutable merkle tree structure,
    where each file is stored under its SHA256 hash and directories are
    represented as JSON objects containing file metadata.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the filesystem with configuration."""
        self.config = config
        self.data_dir = Path(config["data_directory"])
        self.root_prefix = config["root_file_prefix"]
        self.prefix_len = config["directory_organize_prefixlen"]
        
        # File handle management
        self.file_handles: Dict[int, FileHandle] = {}
        self.next_handle_id = 1
        
        # Ensure data directory exists
        if not self.data_dir.exists():
            raise RuntimeError(f"Data directory {self.data_dir} does not exist")
    
    def _get_file_handle(self, fh: int) -> FileHandle:
        """Get file handle by ID."""
        if fh not in self.file_handles:
            raise OSError(errno.EBADF, "Invalid file handle")
        return self.file_handles[fh]
    
    def _create_file_handle(self, path: str, flags: int) -> int:
        """Create a new file handle."""
        handle_id = self.next_handle_id
        self.next_handle_id += 1
        
        mode = "r" if flags & os.O_WRONLY == 0 else "w"
        handle = FileHandle(path, flags, mode)
        self.file_handles[handle_id] = handle
        
        return handle_id
    
    def _get_physical_path(self, file_hash: str) -> Path:
        """Get the physical path for a file hash."""
        prefix = file_hash[:self.prefix_len]
        return self.data_dir / prefix / file_hash
    
    def _read_file_by_hash(self, file_hash: str) -> bytes:
        """Read file content by hash."""
        physical_path = self._get_physical_path(file_hash)
        if not physical_path.exists():
            raise OSError(errno.ENOENT, "File not found")
        
        with open(physical_path, 'rb') as f:
            return f.read()
    
    def _write_file_by_hash(self, file_hash: str, data: bytes) -> None:
        """Write file content by hash."""
        physical_path = self._get_physical_path(file_hash)
        
        # Create directory if it doesn't exist
        physical_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(physical_path, 'wb') as f:
            f.write(data)
    
    def _get_root_hash(self) -> str:
        """Get the current root hash."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, "Root not initialized")
    
    def _set_root_hash(self, root_hash: str) -> None:
        """Set the current root hash."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, "Root not initialized")
    
    def _get_directory_entry(self, path: str) -> Dict[str, Any]:
        """Get directory entry for a path."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"Path not found: {path}")
    
    def _is_directory(self, path: str) -> bool:
        """Check if path is a directory."""
        # This is a skeleton implementation - always fail
        return False
    
    def _is_file(self, path: str) -> bool:
        """Check if path is a file."""
        # This is a skeleton implementation - always fail
        return False
    
    # Core FUSE operations (MVP)
    
    def getattr(self, path: str, fh: Optional[int] = None) -> Dict[str, Any]:
        """Get file/directory attributes."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"Path not found: {path}")
    
    def open(self, path: str, flags: int) -> int:
        """Open a file and return file handle."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        """Read data from file."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    def write(self, path: str, data: bytes, offset: int, fh: int) -> int:
        """Write data to file."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    def unlink(self, path: str) -> None:
        """Delete a file."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    # Secondary operations (implemented in terms of core)
    
    def readdir(self, path: str, fh: int) -> List[str]:
        """List directory contents."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"Directory not found: {path}")
    
    def mkdir(self, path: str, mode: int) -> None:
        """Create directory."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"Parent directory not found: {path}")
    
    def rmdir(self, path: str) -> None:
        """Remove directory."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"Directory not found: {path}")
    
    def rename(self, old: str, new: str) -> None:
        """Rename/move file or directory."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {old}")
    
    def truncate(self, path: str, length: int) -> None:
        """Truncate file to specified length."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    def chmod(self, path: str, mode: int) -> None:
        """Change file permissions."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    def chown(self, path: str, uid: int, gid: int) -> None:
        """Change file ownership."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
    
    def utimens(self, path: str, times: Optional[tuple] = None) -> None:
        """Update file timestamps."""
        # This is a skeleton implementation - always fail
        raise OSError(errno.ENOENT, f"File not found: {path}")
