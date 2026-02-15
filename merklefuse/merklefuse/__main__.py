#!/usr/bin/env python3
"""
Entry point for running merklefuse as a module.

Usage: python -m merklefuse <mountpoint> [options]
"""

from .cli import main

if __name__ == "__main__":
    main()
