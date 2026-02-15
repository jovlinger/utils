"""
Configuration management for Merkle FUSE filesystem.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any


DEFAULT_CONFIG = {
    "debug": False,
    "log_level": "INFO",
    "critical_debug_duration": 300,
    "data_directory": "./data",
    "root_file_prefix": "root_",
    "max_file_size": 1073741824,  # 1GB
    "enable_atime": False,
    "cache_size": 1000,  # TBD - post MVP
    "directory_organize_prefixlen": 2,
}


def get_config_path(config_path: str = None) -> Path:
    """Get the path to the configuration file."""
    if config_path:
        return Path(config_path)
    
    # Try system config first, then user config
    system_config = Path("/etc/merklefuse/config.json")
    user_config = Path.home() / ".config/merklefuse/config.json"
    
    if system_config.exists():
        return system_config
    elif user_config.exists():
        return user_config
    else:
        # Return user config path for creation
        return user_config


def _read_config_file(config_file: Path) -> Dict[str, Any]:
    """Read configuration from file. Separated for testing."""
    with open(config_file, 'r') as f:
        return json.load(f)


def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from file or return defaults."""
    config_file = get_config_path(config_path)
    
    if config_file.exists():
        try:
            user_config = _read_config_file(config_file)
            
            # Merge with defaults
            config = DEFAULT_CONFIG.copy()
            config.update(user_config)
            return config
            
        except (json.JSONDecodeError, IOError) as e:
            raise RuntimeError(f"Failed to load config from {config_file}: {e}")
    else:
        # Return defaults if no config file exists
        return DEFAULT_CONFIG.copy()


def _write_config_file(config_file: Path, config: Dict[str, Any]) -> None:
    """Write configuration to file. Separated for testing."""
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)


def save_config(config: Dict[str, Any], config_path: str = None) -> None:
    """Save configuration to file."""
    config_file = get_config_path(config_path)
    
    # Create directory if it doesn't exist
    config_file.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        _write_config_file(config_file, config)
    except IOError as e:
        raise RuntimeError(f"Failed to save config to {config_file}: {e}")


def validate_config(config: Dict[str, Any]) -> None:
    """Validate configuration values."""
    if not isinstance(config.get("debug"), bool):
        raise ValueError("debug must be a boolean")
    
    if config.get("log_level") not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        raise ValueError("log_level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    
    if not isinstance(config.get("critical_debug_duration"), int) or config["critical_debug_duration"] < 0:
        raise ValueError("critical_debug_duration must be a non-negative integer")
    
    if not isinstance(config.get("max_file_size"), int) or config["max_file_size"] <= 0:
        raise ValueError("max_file_size must be a positive integer")
    
    if not isinstance(config.get("directory_organize_prefixlen"), int) or config["directory_organize_prefixlen"] < 1:
        raise ValueError("directory_organize_prefixlen must be a positive integer")
