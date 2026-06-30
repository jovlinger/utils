"""
Standard functions used everywhere.
"""

from __future__ import annotations

import os
from typing import Union

# Parsed HTTP JSON body from onboard helpers: object -> dict, else raw text.
jsonT = Union[dict, str]

# possibly the least informative name ever
ENVVAR = "ENV"


def is_test_env() -> bool:
    """Are we running in a test environment?"""
    return os.environ.get(ENVVAR) in ["TEST", "DOCKERTEST"]
