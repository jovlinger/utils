"""
Volumio REST API client. Stdlib-only (urllib, json) for easy porting to MicroPython.
Replace urllib with urequests or raw socket on device as needed.
"""

import json
import urllib.error
import urllib.request
from typing import Any


class VolumioAPI:
    """Minimal client for Volumio REST API (getState, volume, play/pause)."""

    def __init__(self, host: str = "volumio.local", port: int = 3000):
        self.host = host.rstrip("/")
        self.port = port
        self._base = f"http://{self.host}:{self.port}/api/v1"

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    def _get_command(self, cmd: str, **params: str) -> dict[str, Any]:
        q = "&".join(f"{k}={v}" for k, v in params.items())
        path = f"/commands/?cmd={cmd}" + (f"&{q}" if q else "")
        return self._get(path)

    def get_state(self) -> dict[str, Any]:
        """Return full player state (volume, status, track, etc.)."""
        return self._get("/getState")

    def set_volume(self, value: int | str) -> dict[str, Any]:
        """Set volume: 0–100, or 'plus', 'minus', 'mute', 'unmute'."""
        return self._get_command("volume", volume=str(value))

    def volume_up(self) -> dict[str, Any]:
        return self.set_volume("plus")

    def volume_down(self) -> dict[str, Any]:
        return self.set_volume("minus")

    def play(self) -> dict[str, Any]:
        return self._get_command("play")

    def pause(self) -> dict[str, Any]:
        return self._get_command("pause")

    def toggle(self) -> dict[str, Any]:
        return self._get_command("toggle")

    def stop(self) -> dict[str, Any]:
        return self._get_command("stop")

    def prev(self) -> dict[str, Any]:
        return self._get_command("prev")

    def next(self) -> dict[str, Any]:
        return self._get_command("next")
