# Merkle FUSE

A FUSE filesystem backed by an n-ary merkle tree.

## Overview

This filesystem presents a normal r/w filesystem interface while storing all data in an immutable merkle tree structure. Every mutation results in new nodes, percolating to the root, providing a complete history of all changes.

## Features

- **Immutable Storage**: All files stored under SHA256 hash
- **Directory Structure**: Stored directly in the merkle tree as JSON
- **Content Addressable**: Files identified by content hash
- **Atomic Operations**: Each operation maintains tree consistency
- **FUSE Interface**: Standard Unix filesystem operations

## Installation

```bash
# Install dependencies
make install

# Or manually
pip install -r requirements.txt
```

## Usage

```bash
# Mount the filesystem
python -m merklefuse /mnt/merklefuse --foreground

# Or using the CLI directly
python merklefuse/cli.py /mnt/merklefuse --foreground
```

## Development

```bash
# Run tests
make test

# Run unit tests only
make test-unit

# Run integration tests only
make test-integration

# Format code
make format

# Run linting
make lint

# Clean up
make clean
```

## Project Structure

```
merklefuse/
├── merklefuse/           # Main package
│   ├── __init__.py
│   ├── cli.py           # Command-line interface
│   ├── config.py        # Configuration management
│   ├── filesystem.py    # FUSE filesystem implementation
│   └── __main__.py      # Module entry point
├── tests/               # Test suite
│   ├── unit/           # Unit tests (mocked)
│   └── integration/    # Integration tests (real filesystem)
├── requirements.txt     # Python dependencies
├── Makefile           # Build and test commands
└── README.md          # This file
```

## Configuration

The filesystem uses a JSON configuration file. Default locations:
- System: `/etc/merklefuse/config.json`
- User: `~/.config/merklefuse/config.json`

### Configuration Options

- `debug`: boolean (default: false) - Keep failed files in /tmp
- `log_level`: string (default: "INFO") - Logging level
- `critical_debug_duration`: integer (default: 300) - Debug duration after critical errors
- `data_directory`: string (default: "./data") - Hash storage location
- `root_file_prefix`: string (default: "root_") - Root file naming
- `max_file_size`: integer (default: 1GB) - File size limit
- `enable_atime`: boolean (default: false) - Access time tracking
- `cache_size`: integer (default: 1000) - Directory cache size (TBD)
- `directory_organize_prefixlen`: integer (default: 2) - Hash prefix length

## Status

This is a skeleton implementation that fails all tests. The core filesystem operations need to be implemented according to the design document.

## License

[License information to be added]
