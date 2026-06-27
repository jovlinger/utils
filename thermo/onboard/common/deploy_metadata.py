"""Deploy metadata piggybacked on onboard POST bodies (e.g. DMZ ``/zone/.../sensors``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Tuple

from common.deployment_config import DEFAULT_HARDWARE_PROFILE, DEFAULT_ZONE_NAME

# Public JSON keys -> environment variables written by deploy scripts.
DEPLOYMENT_METADATA_ENV_KEYS: Tuple[Tuple[str, str], ...] = (
    ("git_sha", "THERMO_DEPLOY_GIT_SHA"),
    ("git_sha_short", "THERMO_DEPLOY_GIT_SHA_SHORT"),
    ("git_branch", "THERMO_DEPLOY_GIT_BRANCH"),
    ("git_dirty", "THERMO_DEPLOY_GIT_DIRTY"),
    ("env_file", "THERMO_DEPLOY_ENV_FILE"),
    ("backend", "THERMO_DEPLOY_BACKEND"),
    ("hardware_profile", "THERMO_DEPLOY_HARDWARE_PROFILE"),
    ("zone_name", "THERMO_DEPLOY_ZONE_NAME"),
)

_HARDWARE_PROFILE_ENV = "ONBOARD_HARDWARE_PROFILE"
_ZONE_NAME_ENV = "ZONE_NAME"


def _utils_repo_root(environ: Mapping[str, str]) -> Optional[Path]:
    """Best-effort path to the utils git repo root (parent of ``thermo/``)."""
    override = environ.get("THERMO_DEPLOY_ROOT", "").strip()
    if override:
        return Path(override)
    for candidate in Path(__file__).resolve().parents:
        if _git_inside_work_tree(candidate):
            return candidate
    return None


def _git_inside_work_tree(repo: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _git_output(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _resolve_git_sha(environ: Mapping[str, str]) -> Tuple[str, str]:
    full = environ.get("THERMO_DEPLOY_GIT_SHA", "").strip()
    short = environ.get("THERMO_DEPLOY_GIT_SHA_SHORT", "").strip()
    if full:
        return full, short
    repo = _utils_repo_root(environ)
    if repo is None:
        return "", short
    full = _git_output(repo, "rev-parse", "HEAD")
    if not short and full:
        short = _git_output(repo, "rev-parse", "--short", "HEAD")
    return full, short


def _resolve_hardware_profile(environ: Mapping[str, str]) -> str:
    for env_key in ("THERMO_DEPLOY_HARDWARE_PROFILE", _HARDWARE_PROFILE_ENV):
        value = environ.get(env_key, "").strip()
        if value:
            return value
    return DEFAULT_HARDWARE_PROFILE


def _resolve_zone_name(environ: Mapping[str, str]) -> str:
    for env_key in ("THERMO_DEPLOY_ZONE_NAME", _ZONE_NAME_ENV):
        value = environ.get(env_key, "").strip()
        if value:
            return value
    return DEFAULT_ZONE_NAME


def deployment_post_metadata(
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Metadata for POST bodies: hardware profile and repo git SHA when known."""
    if environ is None:
        environ = os.environ

    metadata: dict[str, str] = {}
    for public_key, env_key in DEPLOYMENT_METADATA_ENV_KEYS:
        value = environ.get(env_key, "").strip()
        if value:
            metadata[public_key] = value

    hardware_profile = _resolve_hardware_profile(environ)
    metadata["hardware_profile"] = hardware_profile

    git_sha, git_sha_short = _resolve_git_sha(environ)
    if git_sha and "git_sha" not in metadata:
        metadata["git_sha"] = git_sha
    if git_sha_short and "git_sha_short" not in metadata:
        metadata["git_sha_short"] = git_sha_short

    zone_name = _resolve_zone_name(environ)
    if zone_name and "zone_name" not in metadata:
        metadata["zone_name"] = zone_name

    return metadata
