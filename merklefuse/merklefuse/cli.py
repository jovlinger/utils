#!/usr/bin/env python3
"""
Command-line interface for Merkle FUSE filesystem.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from mfusepy import FUSE

from .config import load_config
from .filesystem import MerkleFuseFS


def setup_logging(log_level: str = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Merkle FUSE - A FUSE filesystem backed by a merkle tree"
    )
    
    parser.add_argument(
        "mountpoint",
        help="Directory to mount the filesystem"
    )
    
    parser.add_argument(
        "--config",
        "-c",
        help="Path to configuration file",
        default=None
    )
    
    parser.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        help="Run in foreground (don't daemonize)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level"
    )
    
    return parser.parse_args()


def validate_mountpoint(mountpoint: str) -> None:
    """Validate that mountpoint exists and is a directory."""
    path = Path(mountpoint)
    
    if not path.exists():
        raise FileNotFoundError(f"Mountpoint {mountpoint} does not exist")
    
    if not path.is_dir():
        raise NotADirectoryError(f"Mountpoint {mountpoint} is not a directory")
    
    if not os.access(mountpoint, os.W_OK):
        raise PermissionError(f"No write access to mountpoint {mountpoint}")


def main() -> int:
    """Main entry point for the CLI application."""
    try:
        args = parse_args()
        
        # Set up logging
        log_level = "DEBUG" if args.debug else args.log_level
        setup_logging(log_level)
        logger = logging.getLogger(__name__)
        
        # Validate mountpoint
        validate_mountpoint(args.mountpoint)
        
        # Load configuration
        config = load_config(args.config)
        logger.info(f"Loaded configuration: {config}")
        
        # Create filesystem instance
        fs = MerkleFuseFS(config)
        logger.info("Created Merkle FUSE filesystem instance")
        
        # Mount the filesystem
        logger.info(f"Mounting filesystem at {args.mountpoint}")
        FUSE(fs, args.mountpoint, foreground=args.foreground)
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, unmounting...")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
