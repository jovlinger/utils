"""
Unit tests for configuration management.

These tests mock all file operations and test the core logic.
"""

import json
import pytest
from unittest.mock import Mock, patch, mock_open, MagicMock
from pathlib import Path

from merklefuse.config import load_config, save_config, validate_config, DEFAULT_CONFIG


class TestConfig:
    """Test cases for configuration management."""
    
    def test_load_default_config(self):
        """Test loading default configuration when no file exists."""
        with patch('merklefuse.config.get_config_path') as mock_get_path:
            mock_path = Mock()
            mock_path.exists.return_value = False
            mock_get_path.return_value = mock_path
            
            config = load_config()
            assert config == DEFAULT_CONFIG
    
    def test_load_config_from_file(self):
        """Test loading configuration from file."""
        test_config = {
            "debug": True,
            "log_level": "DEBUG",
            "data_directory": "/custom/data"
        }
        
        with patch('merklefuse.config.get_config_path') as mock_get_path, \
             patch('merklefuse.config._read_config_file') as mock_read:
            
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_get_path.return_value = mock_path
            mock_read.return_value = test_config
            
            config = load_config()
            expected = DEFAULT_CONFIG.copy()
            expected.update(test_config)
            assert config == expected
            mock_read.assert_called_once_with(mock_path)
    
    def test_load_config_file_not_found(self):
        """Test loading configuration when file doesn't exist."""
        with patch('merklefuse.config.get_config_path') as mock_get_path:
            mock_path = Mock()
            mock_path.exists.return_value = False
            mock_get_path.return_value = mock_path
            
            config = load_config()
            assert config == DEFAULT_CONFIG
    
    def test_load_config_json_error(self):
        """Test loading configuration with invalid JSON."""
        with patch('merklefuse.config.get_config_path') as mock_get_path, \
             patch('merklefuse.config._read_config_file', side_effect=json.JSONDecodeError("msg", "doc", 0)):
            
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_get_path.return_value = mock_path
            
            with pytest.raises(RuntimeError, match="Failed to load config"):
                load_config()
    
    def test_save_config(self):
        """Test saving configuration to file."""
        test_config = {
            "debug": True,
            "log_level": "DEBUG"
        }
        
        with patch('merklefuse.config.get_config_path') as mock_get_path, \
             patch('merklefuse.config._write_config_file') as mock_write, \
             patch('pathlib.Path.mkdir') as mock_mkdir:
            
            mock_path = Mock()
            mock_path.parent = Mock()
            mock_get_path.return_value = mock_path
            
            save_config(test_config, "/test/config.json")
            
            # Verify mkdir was called
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            
            # Verify write was called
            mock_write.assert_called_once_with(mock_path, test_config)
    
    def test_save_config_io_error(self):
        """Test saving configuration with IO error."""
        test_config = {"debug": True}
        
        with patch('merklefuse.config.get_config_path') as mock_get_path, \
             patch('merklefuse.config._write_config_file', side_effect=IOError("Permission denied")):
            
            mock_path = Mock()
            mock_path.parent = Mock()
            mock_get_path.return_value = mock_path
            
            with pytest.raises(RuntimeError, match="Failed to save config"):
                save_config(test_config)
    
    def test_validate_config_valid(self):
        """Test validation of valid configuration."""
        valid_config = DEFAULT_CONFIG.copy()
        # Should not raise any exception
        validate_config(valid_config)
    
    def test_validate_config_invalid_debug(self):
        """Test validation fails for invalid debug value."""
        invalid_config = DEFAULT_CONFIG.copy()
        invalid_config["debug"] = "not_a_boolean"
        
        with pytest.raises(ValueError, match="debug must be a boolean"):
            validate_config(invalid_config)
    
    def test_validate_config_invalid_log_level(self):
        """Test validation fails for invalid log level."""
        invalid_config = DEFAULT_CONFIG.copy()
        invalid_config["log_level"] = "INVALID"
        
        with pytest.raises(ValueError, match="log_level must be one of"):
            validate_config(invalid_config)
    
    def test_validate_config_invalid_max_file_size(self):
        """Test validation fails for invalid max file size."""
        invalid_config = DEFAULT_CONFIG.copy()
        invalid_config["max_file_size"] = -1
        
        with pytest.raises(ValueError, match="max_file_size must be a positive integer"):
            validate_config(invalid_config)
    
    def test_validate_config_invalid_prefix_length(self):
        """Test validation fails for invalid prefix length."""
        invalid_config = DEFAULT_CONFIG.copy()
        invalid_config["directory_organize_prefixlen"] = 0
        
        with pytest.raises(ValueError, match="directory_organize_prefixlen must be a positive integer"):
            validate_config(invalid_config)
