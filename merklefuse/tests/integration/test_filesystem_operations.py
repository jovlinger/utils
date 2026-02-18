"""
Integration tests for filesystem operations.

These tests run sequences of operations and verify the state in the test area.
"""

import os
import tempfile
import pytest
from pathlib import Path

from merklefuse.filesystem import MerkleFuseFS
from merklefuse.config import DEFAULT_CONFIG


class TestFilesystemIntegration:
    """Integration tests for filesystem operations."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def fs(self, temp_dir):
        """Create a filesystem instance with test configuration."""
        config = DEFAULT_CONFIG.copy()
        config["data_directory"] = str(temp_dir / "data")
        return MerkleFuseFS(config)
    
    def test_create_and_read_file(self, fs, temp_dir):
        """Test creating a file and reading it back."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            fs.write("/testfile", b"hello world", 0, 1)
    
    def test_create_directory(self, fs, temp_dir):
        """Test creating a directory."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            fs.mkdir("/testdir", 0o755)
    
    def test_list_directory(self, fs, temp_dir):
        """Test listing directory contents."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            fs.readdir("/", None)
    
    def test_file_operations_sequence(self, fs, temp_dir):
        """Test a sequence of file operations."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            # Create file
            fs.write("/sequence_test", b"initial content", 0, 1)
            # Read file
            fs.read("/sequence_test", 1024, 0, 1)
            # Modify file
            fs.write("/sequence_test", b"modified content", 0, 1)
            # Delete file
            fs.unlink("/sequence_test")
    
    def test_directory_operations_sequence(self, fs, temp_dir):
        """Test a sequence of directory operations."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            # Create directory
            fs.mkdir("/testdir", 0o755)
            # Create file in directory
            fs.write("/testdir/file", b"content", 0, 1)
            # List directory
            fs.readdir("/testdir", None)
            # Remove file
            fs.unlink("/testdir/file")
            # Remove directory
            fs.rmdir("/testdir")
    
    def test_rename_operation(self, fs, temp_dir):
        """Test renaming files and directories."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            # Create file
            fs.write("/original", b"content", 0, 1)
            # Rename file
            fs.rename("/original", "/renamed")
            # Verify renamed file exists
            fs.read("/renamed", 1024, 0, 1)
    
    def test_permission_operations(self, fs, temp_dir):
        """Test permission and ownership operations."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            # Create file
            fs.write("/perm_test", b"content", 0, 1)
            # Change permissions
            fs.chmod("/perm_test", 0o600)
            # Change ownership
            fs.chown("/perm_test", 1000, 1000)
            # Update timestamps
            fs.utimens("/perm_test", None)
    
    def test_truncate_operation(self, fs, temp_dir):
        """Test file truncation."""
        # This should fail in skeleton implementation
        with pytest.raises(OSError):
            # Create file
            fs.write("/truncate_test", b"long content here", 0, 1)
            # Truncate file
            fs.truncate("/truncate_test", 5)
            # Read truncated content
            fs.read("/truncate_test", 1024, 0, 1)
