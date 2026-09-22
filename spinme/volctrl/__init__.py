"""Volumio proof-of-concept controller: discover, state, volume, play/pause."""

from .api import VolumioAPI
from .discover import discover, resolve_volumio_local

__all__ = ["VolumioAPI", "discover", "resolve_volumio_local"]
