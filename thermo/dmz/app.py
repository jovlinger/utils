"""
This lives on the WWW.

Accept backend long-poll connections from trusted zone. (with trust token)

Accept request; redirect to google auth, if success push to backend long poll

Backend will return result in next query, with association ID.

Long-term, make the backend connection into a TCP based queue (connection is awkward bit)
"""

from collections import deque, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import re
import signal
import threading
import time
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple, TypedDict, Union
from urllib.parse import urlparse

from flask import Flask, g, redirect, request, session, url_for
from pydantic import BaseModel, validator

from logging_config import configure_logging, set_log_level

configure_logging("dmz")
# Example: 2026-05-17T13:40:23.905Z INFO dmz app:396 auth startup: zone_enforced=True zone_src=… oauth=…
logger = logging.getLogger(__name__)

JSON = Union[Dict, str, int]

# Access log: circular buffer of {method, path, status, ts}
ACCESS_LOG_MAXLEN = 500
_access_log: Deque[Dict[str, Any]] = deque(maxlen=ACCESS_LOG_MAXLEN)

# In-memory only (no disk): recent zone POST outcomes for operator debugging (twoway ↔ DMZ).
_ZONE_ATTEMPT_MAXLEN = 200
_zone_attempts: Deque[Dict[str, Any]] = deque(maxlen=_ZONE_ATTEMPT_MAXLEN)
_START_WALL: float = time.time()
_START_UTC_ISO: str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

# Repeat-log suppression (zone state dump + obsolete command DEBUG).
_last_zone_state_fingerprint: Optional[str] = None
_zone_state_log_suppressed_count: int = 0
_last_obsolete_log_fingerprint: Optional[str] = None
_obsolete_log_suppressed_count: int = 0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    norm = raw.strip().lower()
    if norm in ("1", "true", "yes", "on"):
        return True
    if norm in ("0", "false", "no", "off"):
        return False
    return default


def _zone_state_log_suppress_repeat() -> int:
    """Log again after this many consecutive suppressed identical fingerprints."""
    raw = os.environ.get("ZONE_STATE_LOG_SUPPRESS_REPEAT", "10").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 10
    return max(1, n)


class ZoneRequest(BaseModel):
    security_token: str
    zone_name: str
    threading_id: str
    payload: JSON


class ZoneReply(BaseModel):
    threading_id: str
    method: str  # enum Timeout | ReadEnv | SendTemp


class Sensors(BaseModel):
    temp_centigrade: Optional[float] = None
    humid_percent: Optional[float] = None
    created_dt: str = ""

    @validator("created_dt", pre=True, always=True)
    def _set_created_dt(cls, v: Any) -> str:
        # Pydantic v2 used `model_post_init`; in v1 we validate after construction.
        if not v:
            return datetime.now().isoformat()
        return v


class ZoneState(BaseModel):
    command: Optional[Any] = None
    sensors: Optional[Sensors] = None


def _json_strings_only_ascii(value: Any) -> Optional[str]:
    """
    Return an error detail string if any JSON string value or object key
    contains a non-ASCII character (code point > 127).
    """
    if isinstance(value, str):
        for ch in value:
            if ord(ch) > 127:
                return "string contains non-ASCII character"
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            err = _json_strings_only_ascii(k)
            if err:
                return err
            err = _json_strings_only_ascii(v)
            if err:
                return err
        return None
    if isinstance(value, list):
        for item in value:
            err = _json_strings_only_ascii(item)
            if err:
                return err
        return None
    return None


def _parse_validated_command_json(
    raw: bytes,
) -> Tuple[Optional[Any], Optional[Tuple[Dict[str, Any], int]]]:
    """
    Parse POST body as JSON and ensure all strings are 7-bit ASCII.
    Returns (value, None) on success, or (None, (error_body, status_code)) on failure.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, ({"error": "body must be valid UTF-8"}, 400)
    if not text.strip():
        return None, ({"error": "empty body"}, 400)
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError as e:
        return None, ({"error": "invalid JSON", "detail": str(e)}, 400)
    err = _json_strings_only_ascii(parsed)
    if err:
        return None, (
            {"error": "JSON strings must be 7-bit ASCII", "detail": err},
            400,
        )
    return parsed, None


def _mark_command_accessed(cmd: Any) -> None:
    if isinstance(cmd, dict):
        cmd["last_access_dt"] = datetime.now().isoformat()


def _stamp_command_if_missing(cmd: Dict[str, Any]) -> str:
    """Ensure ``cmd["created_dt"]`` is a string; receiver-stamp with now() when missing.

    Returns the (now-guaranteed) ``created_dt`` string. Origin clocks are trusted when
    present, but should be human-precision close to ours; receiver-stamping covers
    callers that simply do not bother (UI form posts, ad-hoc curl).
    """
    existing = cmd.get("created_dt")
    if isinstance(existing, str) and existing:
        return existing
    stamped = datetime.now().isoformat()
    cmd["created_dt"] = stamped
    return stamped


def _replace_command_if_newer(zonename: str, cmd: Dict[str, Any], source: str) -> str:
    """Append ``cmd`` to ``commands[zonename]`` iff its created_dt is strictly newer
    than the stored last command's. Returns one of ``"accepted"`` or ``"obsolete"``.

    The stored history (capped at MAXLEN) is append-only on accept; obsolete commands
    are dropped entirely so ``_lastor`` always returns the freshest seen command.
    """
    incoming_dt = _stamp_command_if_missing(cmd)
    last = _lastor(commands[zonename])
    last_dt = last.get("created_dt") if isinstance(last, dict) else None
    if isinstance(last_dt, str) and last_dt and incoming_dt <= last_dt:
        _log_zone_command_obsolete(zonename, source, incoming_dt, last_dt, cmd)
        return "obsolete"
    _append_and_trim(commands[zonename], cmd)
    logger.info(
        "zone command accepted zone=%s source=%s created_dt=%s previous=%s",
        zonename,
        source,
        incoming_dt,
        last_dt,
    )
    _log_full_zone_state(reason=f"command:{source}", zonename=zonename)
    return "accepted"


def _full_zone_state_snapshot() -> Dict[str, Dict[str, Any]]:
    """Latest ``{command, sensors}`` for every known zone, JSON-friendly.

    Walks the union of ``commands`` and ``sensors`` keys so a zone with sensors but no
    command (or vice versa) still appears. Used by :func:`_log_full_zone_state` to dump
    the entire DMZ state on every mutation; cheap (one-deep dict + Pydantic .dict()).
    """
    snap: Dict[str, Dict[str, Any]] = {}
    for z in sorted(set(commands.keys()) | set(sensors.keys())):
        cmd = _lastor(commands[z])
        sns = _lastor(sensors[z])
        sns_d = sns.dict() if hasattr(sns, "dict") else sns
        snap[z] = {"command": cmd, "sensors": sns_d}
    return snap


def _prune_snap_for_fingerprint(obj: Any) -> Any:
    """Copy *obj* without volatile fields (``sensors``, keys ending in ``_dt``) Recursively."""
    if isinstance(obj, dict):
        pruned: Dict[str, Any] = {}
        for key, value in obj.items():
            if key == "sensors" or key.endswith("_dt"):
                continue
            pruned[key] = _prune_snap_for_fingerprint(value)
        return pruned
    if isinstance(obj, list):
        return [_prune_snap_for_fingerprint(item) for item in obj]
    return obj


def _zone_state_fingerprint(snap: Dict[str, Dict[str, Any]]) -> str:
    """SHA-256 of JSON for *snap* with volatile keys removed."""
    pruned = _prune_snap_for_fingerprint(snap)
    payload = json.dumps(pruned, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _obsolete_log_fingerprint(
    zonename: str,
    source: str,
    incoming_dt: str,
    stored_dt: str,
    cmd: Dict[str, Any],
) -> str:
    payload = {
        "zone": zonename,
        "source": source,
        "incoming_dt": incoming_dt,
        "stored_dt": stored_dt,
        "command": _prune_snap_for_fingerprint(cmd),
    }
    blob = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _obsolete_repeat_suppression_active() -> bool:
    """True when identical obsolete DEBUG lines may be collapsed."""
    return CONFIG["obsolete_log_suppress_repeat"] > 1


def _should_emit_repeat_log(
    fp: str,
    last_fp: Optional[str],
    suppressed_count: int,
    repeat_max: int,
) -> Tuple[bool, int]:
    """Return (emit_now, new_suppressed_count)."""
    if last_fp == fp:
        suppressed_count += 1
        if suppressed_count < repeat_max:
            return False, suppressed_count
        return True, 0
    return True, 0


def _log_zone_command_obsolete(
    zonename: str,
    source: str,
    incoming_dt: str,
    stored_dt: str,
    cmd: Dict[str, Any],
) -> None:
    global _last_obsolete_log_fingerprint, _obsolete_log_suppressed_count
    if not _obsolete_repeat_suppression_active():
        logger.debug(
            "zone command obsolete; ignored zone=%s source=%s incoming=%s stored=%s",
            zonename,
            source,
            incoming_dt,
            stored_dt,
        )
        return
    fp = _obsolete_log_fingerprint(zonename, source, incoming_dt, stored_dt, cmd)
    repeat_max = CONFIG["obsolete_log_suppress_repeat"]
    emit, _obsolete_log_suppressed_count = _should_emit_repeat_log(
        fp,
        _last_obsolete_log_fingerprint,
        _obsolete_log_suppressed_count,
        repeat_max,
    )
    _last_obsolete_log_fingerprint = fp
    if not emit:
        return
    logger.debug(
        "zone command obsolete; ignored zone=%s source=%s incoming=%s stored=%s fingerprint=%s",
        zonename,
        source,
        incoming_dt,
        stored_dt,
        fp[:16],
    )


def _reset_repeat_log_suppression() -> None:
    global _last_zone_state_fingerprint, _zone_state_log_suppressed_count
    global _last_obsolete_log_fingerprint, _obsolete_log_suppressed_count
    _last_zone_state_fingerprint = None
    _zone_state_log_suppressed_count = 0
    _last_obsolete_log_fingerprint = None
    _obsolete_log_suppressed_count = 0


def _log_full_zone_state(reason: str, zonename: Optional[str] = None) -> None:
    """Emit a single DEBUG line with the full ``{zone: {command, sensors}}`` snapshot.

    Called after every mutation of ``commands`` / ``sensors`` so the log shows the
    complete authoritative state at each transition. ``reason`` and ``zonename`` (if any)
    explain what just changed; the snapshot itself is the entire DMZ state, not just the
    mutated zone, since cross-zone visibility is the point.

    Identical pruned state (no ``sensors`` / ``*_dt``) is logged once, then suppressed until
    the fingerprint changes or ``ZONE_STATE_LOG_SUPPRESS_REPEAT`` identical updates
    have been skipped (then one repeat log and the counter resets).
    """
    global _last_zone_state_fingerprint, _zone_state_log_suppressed_count
    try:
        snap = _full_zone_state_snapshot()
        fp = _zone_state_fingerprint(snap)
        repeat_max = _zone_state_log_suppress_repeat()
        emit, _zone_state_log_suppressed_count = _should_emit_repeat_log(
            fp,
            _last_zone_state_fingerprint,
            _zone_state_log_suppressed_count,
            repeat_max,
        )
        _last_zone_state_fingerprint = fp
        if not emit:
            return
        logger.debug(
            "zone state changed reason=%s zone=%s fingerprint=%s state=%s",
            reason,
            zonename or "*",
            fp[:16],
            json.dumps(snap, default=str, sort_keys=True),
        )
    except Exception as e:
        logger.debug("zone state log failed reason=%s err=%s", reason, e)


class DmzConfig(TypedDict):
    """Snapshot of DMZ runtime settings (from the environment at load / reload time).

    ``env`` is the raw ``ENV`` value; ``is_*_env`` booleans are derived equality checks
    against known mode names (``DOCKERTEST``, ``UI_INTEGRATION``).
    """

    secret_key: str
    google_client_id: Optional[str]
    google_client_secret: Optional[str]
    oauth_enabled: bool
    allowed_email_pattern: str
    allowed_email: str
    zone_public_key: Optional[str]
    zone_public_key_path: Optional[str]
    env: Optional[str]
    is_dockertest_env: bool
    is_ui_integration_env: bool
    port: int
    long_poll_timeout_secs: float
    long_poll_sleep_secs: float
    log_level: str
    obsolete_log_suppress_repeat: int
    oauth_session_lifetime_secs: int
    thermo_ui_public_origin: str
    dmz_public_base_url: Optional[str]


def build_dmz_config_from_environ() -> DmzConfig:
    """Read all DMZ-relevant environment variables into one mapping."""
    google_client_id: Optional[str] = os.environ.get("GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = os.environ.get("GOOGLE_CLIENT_SECRET")
    env_raw: Optional[str] = os.environ.get("ENV")
    thermo_ui = (os.environ.get("THERMO_UI_PUBLIC_ORIGIN") or "").strip().rstrip("/")
    base_raw = (
        os.environ.get("DMZ_PUBLIC_BASE_URL")
        or os.environ.get("DMZ_PUBLIC_URL")
        or ""
    ).strip().rstrip("/")
    dmz_public_base_url: Optional[str] = base_raw or None
    port_s = os.environ.get("PORT", "5000")
    try:
        port: int = int(port_s)
    except ValueError:
        port = 5000
    oauth_life_s = os.environ.get("OAUTH_SESSION_LIFETIME_SECS", "2592000").strip()
    try:
        oauth_session_lifetime_secs: int = max(0, int(oauth_life_s))
    except ValueError:
        oauth_session_lifetime_secs = 0
    cfg: DmzConfig = {
        "secret_key": os.environ.get("SECRET_KEY", "dev-secret-change-in-production"),
        "google_client_id": google_client_id,
        "google_client_secret": google_client_secret,
        "oauth_enabled": bool(google_client_id),
        "allowed_email_pattern": (os.environ.get("ALLOWED_EMAIL_PATTERN") or "").strip(),
        "allowed_email": (os.environ.get("ALLOWED_EMAIL") or "").strip(),
        "zone_public_key": os.environ.get("ZONE_PUBLIC_KEY"),
        "zone_public_key_path": os.environ.get("ZONE_PUBLIC_KEY_PATH"),
        "env": env_raw,
        "is_dockertest_env": env_raw == "DOCKERTEST",
        "is_ui_integration_env": env_raw == "UI_INTEGRATION",
        "port": port,
        "long_poll_timeout_secs": float(os.environ.get("LONG_POLL_TIMEOUT_SECS", "60")),
        "long_poll_sleep_secs": float(os.environ.get("LONG_POLL_SLEEP_SECS", "1.0")),
        "log_level": (os.environ.get("LOG_LEVEL") or "DEBUG").strip().upper(),
        "obsolete_log_suppress_repeat": _env_int("OBSOLETE_LOG_SUPPRESS_REPEAT", 10),
        "oauth_session_lifetime_secs": oauth_session_lifetime_secs,
        "thermo_ui_public_origin": thermo_ui,
        "dmz_public_base_url": dmz_public_base_url,
    }
    return cfg


CONFIG: DmzConfig = build_dmz_config_from_environ()

app = Flask(__name__)
app.secret_key = CONFIG["secret_key"]
app.config["GOOGLE_CLIENT_ID"] = CONFIG["google_client_id"]
app.config["GOOGLE_CLIENT_SECRET"] = CONFIG["google_client_secret"]


def _apply_flask_session_lifetime() -> None:
    """Set Flask ``PERMANENT_SESSION_LIFETIME`` from ``OAUTH_SESSION_LIFETIME_SECS``."""
    secs = CONFIG["oauth_session_lifetime_secs"]
    if secs > 0:
        app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=secs)
    else:
        app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=31)


_apply_flask_session_lifetime()

# Runtime tuning file (generated from thermo/dmz/dmz.conf at image build).
# Pi: copied to chroot /etc/dmz/dmz-app.env by install/dmz-boot.start (from SD install/dmz-app.env).
DEFAULT_DMZ_APP_ENV_PATH = "/etc/dmz/dmz-app.env"
_config_reload_signal_installed = False


def dmz_app_env_path() -> Path:
    """Path to the KEY=value env file re-read on config reload."""
    return Path(os.environ.get("DMZ_APP_ENV_PATH", DEFAULT_DMZ_APP_ENV_PATH))


def load_dmz_app_env_file(path: Optional[Path] = None) -> bool:
    """Load KEY=value lines from *path* into ``os.environ``. Returns True if file existed."""
    env_path = path if path is not None else dmz_app_env_path()
    if not env_path.is_file():
        return False
    with env_path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, val = line.partition("=")
            if not sep:
                continue
            key = key.strip()
            if key:
                os.environ[key] = val
    return True


def reload_dmz_config_from_disk() -> bool:
    """Re-read dmz-app.env from disk, then rebuild :data:`CONFIG`. Returns True if file found."""
    path = dmz_app_env_path()
    found = load_dmz_app_env_file(path)
    reload_dmz_config_from_environ()
    _wake_long_poll_waiters_for_config_reload()
    logger.info(
        "config reloaded from disk path=%s found=%s log_level=%s "
        "obsolete_log_suppress_repeat=%s long_poll_timeout_secs=%s port=%s",
        path,
        found,
        CONFIG["log_level"],
        CONFIG["obsolete_log_suppress_repeat"],
        CONFIG["long_poll_timeout_secs"],
        CONFIG["port"],
    )
    return found


def _on_sigusr1_reload_config(signum: int, frame: Any) -> None:
    del signum, frame
    reload_dmz_config_from_disk()


def install_config_reload_signal() -> None:
    """Register SIGUSR1 → reload dmz-app.env + CONFIG (Unix only)."""
    global _config_reload_signal_installed
    if _config_reload_signal_installed:
        return
    if not hasattr(signal, "SIGUSR1"):
        return
    signal.signal(signal.SIGUSR1, _on_sigusr1_reload_config)
    _config_reload_signal_installed = True


def reload_dmz_config_from_environ() -> None:
    """
    Rebuild :data:`CONFIG` from ``os.environ`` and sync Flask settings.

    Used by tests that set ``ZONE_PUBLIC_KEY`` (or other vars) after import.
    """
    global CONFIG
    CONFIG = build_dmz_config_from_environ()
    app.secret_key = CONFIG["secret_key"]
    app.config["GOOGLE_CLIENT_ID"] = CONFIG["google_client_id"]
    app.config["GOOGLE_CLIENT_SECRET"] = CONFIG["google_client_secret"]
    set_log_level(CONFIG["log_level"])
    _apply_flask_session_lifetime()


def email_matches_allowlist(raw_email: str) -> bool:
    """
    Return True if the Gmail OAuth email is permitted.

    Resolution order (first that applies):
    - ``ALLOWED_EMAIL_PATTERN``: Python ``re.fullmatch`` against the whole address
      (case-insensitive). SD images bake this from ``install/allowed-email`` via
      ``start.sh``.
    - ``ALLOWED_EMAIL``: legacy exact single-address match (e.g. Docker ``-e``).
    - Default dev address ``jovlinger@gmail.com`` when neither env var is set.
    """
    email = (raw_email or "").strip().lower()
    if not email:
        return False
    pattern = CONFIG["allowed_email_pattern"]
    if pattern:
        try:
            return re.fullmatch(pattern, email, flags=re.IGNORECASE) is not None
        except re.error as exc:
            logger.error("ALLOWED_EMAIL_PATTERN is invalid: %s", exc)
            return False
    legacy = CONFIG["allowed_email"]
    if legacy:
        return email == legacy.lower()
    return email == "jovlinger@gmail.com"


if CONFIG["oauth_enabled"]:
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
        authorize_params={"hd": "gmail.com"},
    )


def _auth_config_detail() -> Dict[str, Any]:
    """Operator-safe auth summary (no full secrets): booleans, sources, SHA256/ID suffixes."""
    raw_inline = CONFIG["zone_public_key"]
    raw_path = CONFIG["zone_public_key_path"]
    zone_enforced = bool(raw_inline or raw_path)
    zone_source = "none"
    pem_bytes: Optional[bytes] = None
    if raw_inline:
        zone_source = "ZONE_PUBLIC_KEY(inline)"
        pem_bytes = raw_inline.strip().encode("utf-8")
    elif raw_path:
        zone_source = f"ZONE_PUBLIC_KEY_PATH={raw_path}"
        try:
            pem_bytes = Path(raw_path).read_bytes()
        except OSError as exc:
            zone_source = f"{zone_source} (unreadable: {exc})"
    zone_key_last4 = "n/a"
    if pem_bytes:
        zone_key_last4 = hashlib.sha256(pem_bytes).hexdigest()[-4:]
    google_id = str(CONFIG["google_client_id"] or "")
    google_last4 = google_id[-4:] if len(google_id) >= 4 else ("n/a" if not google_id else google_id)
    allow_pat = CONFIG["allowed_email_pattern"]
    allowlist_mode = (
        "regex"
        if allow_pat
        else ("legacy_env" if CONFIG["allowed_email"] else "dev_default")
    )
    allow_pat_digest = "n/a"
    if allow_pat:
        allow_pat_digest = hashlib.sha256(allow_pat.encode("utf-8")).hexdigest()[-4:]
    sk = str(app.secret_key or "")
    secret_last4 = sk[-4:] if len(sk) >= 4 else ("n/a" if not sk else sk)
    default_dev = sk == "dev-secret-change-in-production"
    return {
        "zone_auth_enforced": zone_enforced,
        "zone_pubkey_source": zone_source,
        "zone_pubkey_sha256_last4": zone_key_last4,
        "oauth_enabled": CONFIG["oauth_enabled"],
        "google_client_id_last4": google_last4,
        "allowlist_mode": allowlist_mode,
        "allowlist_pattern_sha256_last4": allow_pat_digest,
        "flask_secret_key_last4": secret_last4,
        "flask_secret_is_default_dev": default_dev,
        "env": CONFIG["env"],
        "dmz_public_base_url": CONFIG["dmz_public_base_url"],
        "oauth_session_lifetime_secs": CONFIG["oauth_session_lifetime_secs"],
    }


DEFAULT_BUILDINFO_PATHS: Tuple[Path, ...] = (
    Path("/etc/dmz/buildinfo.txt"),
    Path("/app/buildinfo.txt"),
    Path("/BUILD.txt"),
)


def _candidate_buildinfo_paths() -> List[Path]:
    """Return buildinfo probe paths, with ``DMZ_BUILDINFO_PATH`` taking precedence."""
    override = (os.environ.get("DMZ_BUILDINFO_PATH") or "").strip()
    paths: List[Path] = []
    if override:
        paths.append(Path(override))
    paths.extend(DEFAULT_BUILDINFO_PATHS)
    return paths


def _parse_buildinfo(text: str, source: str) -> Dict[str, Any]:
    """Parse build-and-write.sh buildinfo.txt into an operator-safe JSON object."""
    out: Dict[str, Any] = {
        "available": True,
        "source": source,
    }
    first_data_line = True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if first_data_line and "=" not in line:
            parts = line.split(None, 1)
            out["build_id"] = parts[0]
            if len(parts) > 1:
                out["build_date_utc"] = parts[1]
            first_data_line = False
            continue
        first_data_line = False
        key, sep, value = line.partition("=")
        if not sep:
            continue
        clean_key = key.strip()
        if clean_key:
            out[clean_key] = value.strip()
    return out


def _build_version_payload() -> Dict[str, Any]:
    """Return image provenance visible to operators and deployment checks."""
    tried: List[str] = []
    for path in _candidate_buildinfo_paths():
        path_s = str(path)
        if path_s in tried:
            continue
        tried.append(path_s)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        return _parse_buildinfo(text, path_s)
    return {
        "available": False,
        "source": "none",
        "paths_tried": tried,
    }


@app.route("/version", methods=["GET"])
def version() -> Any:
    """Open build provenance endpoint for checking which image is live."""
    return _build_version_payload()


def _log_auth_startup() -> None:
    d = _auth_config_detail()
    logger.info(
        "auth startup: zone_enforced=%s zone_src=%s zone_pub_sha256_last4=%s "
        "oauth=%s google_client_id_last4=%s allowlist_mode=%s allowlist_pat_sha256_last4=%s "
        "flask_secret_last4=%s default_dev_secret=%s env=%s port=%s "
        "oauth_session_lifetime_secs=%s",
        d["zone_auth_enforced"],
        d["zone_pubkey_source"],
        d["zone_pubkey_sha256_last4"],
        d["oauth_enabled"],
        d["google_client_id_last4"],
        d["allowlist_mode"],
        d["allowlist_pattern_sha256_last4"],
        d["flask_secret_key_last4"],
        d["flask_secret_is_default_dev"],
        d.get("env"),
        CONFIG["port"],
        d["oauth_session_lifetime_secs"],
    )


_log_auth_startup()


def _client_ip(req: Any) -> str:
    """Best-effort client address (honors ``X-Forwarded-For`` when present)."""
    xff = (req.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        return xff.split(",", 1)[0].strip()
    return str(req.remote_addr or "")


def _record_zone_sensor_attempt(
    zonename: str,
    path: str,
    outcome: str,
    detail: str,
    http_status: Optional[int],
) -> None:
    """Append one POST /zone/<z>/sensors outcome (ring buffer, no persistent state)."""
    _zone_attempts.append(
        {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "zone": zonename,
            "path": path,
            "outcome": outcome,
            "detail": (detail[:500] if detail else ""),
            "client_ip": _client_ip(request),
            "status_code": http_status,
        }
    )


def _diagnostics_payload() -> Dict[str, Any]:
    """Shared JSON for ``/ui/diagnostics`` and augmented ``GET /debug/logs``."""
    cfg = _auth_config_detail()
    return {
        "server_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "process_start_utc": _START_UTC_ISO,
        "uptime_seconds": round(time.time() - _START_WALL, 3),
        "version": _build_version_payload(),
        "config": cfg,
        "access_log": list(_access_log),
        "zone_attempts": list(_zone_attempts),
    }


def _log_access(method: str, path: str, status: int) -> None:
    """Append to circular access log."""
    _access_log.append(
        {
            "method": method,
            "path": path,
            "status": status,
            "ts": datetime.now().isoformat(),
        }
    )


@app.after_request
def _after_request(response: Any) -> Any:
    """Log every endpoint access with result HTTP status."""
    if request.endpoint and request.endpoint != "static":
        _log_access(request.method, request.path, response.status_code)
        logger.info(
            "request %s %s -> %s",
            request.method,
            request.path,
            response.status_code,
        )
        req_size = (
            request.content_length
            if request.content_length is not None
            else len(request.get_data())
        )
        resp_size = getattr(response, "content_length", None) or "-"
        logger.trace(
            "request %s %s body=%s -> %d response_len=%s",
            request.method,
            request.path,
            req_size,
            response.status_code,
            resp_size,
        )
    return response


def assertAuthAzZone(req: Any) -> None:
    """Zone auth placeholder. Machine auth (request signing) will replace this."""
    assert req


### BEGIN STATE (make this sqlite)
commands: Dict[str, List[Any]] = defaultdict(list)
sensors: Dict[str, List[Sensors]] = defaultdict(list)
# Wall-clock floats (``time.time()``), comparable across NTP adjustments.
_ui_command_received_at: Dict[str, float] = defaultdict(float)
_last_zone_command_reply_at: Dict[str, float] = defaultdict(float)
_zone_command_clock_lock = threading.Lock()
### END STATE


def _lastor(lst: List[Any], default: Optional[Any] = None) -> Any:
    if not lst:
        return default
    return lst[-1]


def _mark_ui_command_received(zonename: str) -> float:
    now = time.time()
    with _zone_command_clock_lock:
        _ui_command_received_at[zonename] = now
    return now


def _mark_zone_command_reply_sent(zonename: str) -> float:
    now = time.time()
    with _zone_command_clock_lock:
        _last_zone_command_reply_at[zonename] = now
    return now


def _wake_long_poll_waiters_for_config_reload() -> None:
    """Bump UI-command wall time so in-flight zone long-polls return promptly."""
    now = time.time()
    with _zone_command_clock_lock:
        for zonename in set(commands.keys()) | set(sensors.keys()):
            _ui_command_received_at[zonename] = now


def _await_new_ui_command_or_timeout(zonename: str) -> None:
    """
    Long-poll gate for zone POSTs.

    Snapshot the zone's last reply-sent wall time once at request start. Wait until UI has
    posted a newer command time than that snapshot, or until timeout.

    Uses ``time.time()`` (not monotonic) so timestamps stay aligned with log lines and
    ``created_dt`` after NTP sets the system clock during boot.

    Snapshot semantics intentionally allow overlapping POSTs from the same zone: each thread
    compares against its own start-time baseline so one thread updating "last sent" does not
    force siblings to keep waiting after a new UI command arrives.
    """
    started = time.time()
    with _zone_command_clock_lock:
        sent_baseline = _last_zone_command_reply_at[zonename]
    while True:
        with _zone_command_clock_lock:
            ui_last = _ui_command_received_at[zonename]
        if ui_last > sent_baseline:
            return
        if (time.time() - started) >= CONFIG["long_poll_timeout_secs"]:
            return
        time.sleep(CONFIG["long_poll_sleep_secs"])


def _zone_response(zonename: str, update_access: bool) -> JSON:
    """Craft the json for one zone's response"""
    cmd = _lastor(commands[zonename])
    sns = _lastor(sensors[zonename])
    if cmd is not None and update_access:
        _mark_command_accessed(cmd)
    ret = ZoneState(command=cmd, sensors=sns).dict()
    print(f"_zone_response({zonename}, {update_access}) -> {ret}")
    return ret


MAXLEN = 10000


def _append_and_trim(lst: List[Any], item: Any) -> None:
    """Append an item to the lst, and trim it to max length."""
    lst.append(item)
    while len(lst) > MAXLEN:
        del lst[0]


# FIXME: soonish, make separate endpoints for external client vs internal zones/
# require different auth for each
# and restrict who can update what.


# Session: HTML UI base (scheme + host, no path) captured on GET /login — survives Google round-trip.
_SESSION_OAUTH_PUBLIC_UI_HOME = "_thermo_oauth_public_ui_home"


def _public_ui_root_url() -> Optional[str]:
    """
    Default browser UI: same scheme + hostname as the current request, **no port or path**
    (implicit port 80 / HTTPS default). Uses ``request.url`` / ``request.scheme`` — never ``/ui/context``.
    """
    try:
        u = urlparse(request.url)
    except Exception:
        return None
    host = u.hostname
    if not host:
        return None
    scheme = (request.scheme or u.scheme or "http").lower()
    if scheme not in ("http", "https"):
        scheme = "http"
    return f"{scheme}://{host}"


def _redirect_public_ui_home_or_503() -> Any:
    """302 to the public HTML UI root; never ``/ui/context`` in ``Location``."""
    origin = CONFIG["thermo_ui_public_origin"]
    if origin:
        return redirect(f"{origin}/")
    login_origin = (session.get(_SESSION_OAUTH_PUBLIC_UI_HOME) or "").strip().rstrip("/")
    if login_origin:
        return redirect(f"{login_origin}/")
    fallback = _public_ui_root_url()
    if fallback:
        return redirect(f"{fallback}/")
    return (
        {"error": "cannot derive public UI URL (set THERMO_UI_PUBLIC_ORIGIN or open /login on this host)"},
        503,
    )


@app.route("/login")
def login() -> Any:
    """Redirect to Google OAuth. Restricted to gmail.com; allowlist via regex or legacy env."""
    if not CONFIG["oauth_enabled"]:
        return {"error": "OAuth not configured"}, 400
    home = _public_ui_root_url()
    if home:
        session[_SESSION_OAUTH_PUBLIC_UI_HOME] = home
    redirect_uri = url_for("authorize", _external=True)
    return oauth.google.authorize_redirect(redirect_uri, hd="gmail.com")


@app.route("/authorize")
def authorize() -> Any:
    """OAuth callback. Verify email against allowlist, then redirect browser to HTML UI."""
    if not CONFIG["oauth_enabled"]:
        return redirect(url_for("get_zones"))
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        return {"error": "OAuth failed"}, 400
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not (email.endswith("@gmail.com") or email.endswith("@googlemail.com")):
        return {"error": "Only Gmail addresses allowed"}, 403
    if not email_matches_allowlist(email):
        return {"error": "Access denied (email not on allowlist)"}, 403
    session["user"] = {"email": email}
    if CONFIG["oauth_session_lifetime_secs"] > 0:
        session.permanent = True
    return _redirect_public_ui_home_or_503()


@app.route("/logout")
def logout() -> Any:
    """Clear session."""
    session.pop("user", None)
    session.pop(_SESSION_OAUTH_PUBLIC_UI_HOME, None)
    return redirect(url_for("login") if CONFIG["oauth_enabled"] else url_for("get_zones"))


def _zone_public_key_configured() -> Optional[str]:
    return CONFIG["zone_public_key"] or CONFIG["zone_public_key_path"]


def _zone_auth_signature_header_present() -> bool:
    """
    True when the request includes a non-empty zone-auth signature header
    (header name from ``zone_auth`` when importable, else ``X-Zone-Signature``).
    """
    try:
        from zone_auth import HEADER_SIGNATURE
    except ImportError:
        HEADER_SIGNATURE = "X-Zone-Signature"
    return bool(request.headers.get(HEADER_SIGNATURE))


def _verify_zone_request(zonename: str) -> Optional[tuple[int, Any]]:
    """Verify Ed25519 machine auth. Returns (status_code, response) on failure, None on success."""
    pub_key = _zone_public_key_configured()
    if not pub_key:
        return None  # auth disabled
    try:
        from zone_auth import (
            verify_request,
            HEADER_SIGNATURE,
            HEADER_TIMESTAMP,
            HEADER_ZONE,
        )
    except ImportError:
        return None
    sig = request.headers.get(HEADER_SIGNATURE)
    ts = request.headers.get(HEADER_TIMESTAMP)
    zone_hdr = request.headers.get(HEADER_ZONE)
    if not sig or not ts or zone_hdr != zonename:
        return (401, {"error": "missing or invalid zone auth headers"})
    body = request.get_data()
    if verify_request(
        request.method,
        request.path,
        body,
        zonename,
        sig,
        ts,
        pub_key,
    ):
        return None
    return (401, {"error": "invalid zone signature"})


def _verify_global_machine_request() -> Optional[tuple[int, Any]]:
    """
    Verify Ed25519 machine auth for routes without a zone in the URL (e.g. GET /zones).
    Returns (status_code, response) on failure, None on success.
    """
    pub_key = _zone_public_key_configured()
    if not pub_key:
        return (401, {"error": "machine auth misconfigured"})
    try:
        from zone_auth import (
            verify_request,
            HEADER_SIGNATURE,
            HEADER_TIMESTAMP,
            HEADER_ZONE,
        )
    except ImportError:
        return None
    sig = request.headers.get(HEADER_SIGNATURE)
    ts = request.headers.get(HEADER_TIMESTAMP)
    zone_hdr = request.headers.get(HEADER_ZONE)
    if not sig or not ts or not zone_hdr:
        return (401, {"error": "missing zone auth headers"})
    body = request.get_data()
    if verify_request(
        request.method,
        request.path,
        body,
        zone_hdr,
        sig,
        ts,
        pub_key,
    ):
        return None
    return (401, {"error": "invalid zone signature"})


def _authorize_ui() -> Optional[Any]:
    """
    Gate /ui/context and /ui/command on OAuth session when OAuth is configured.


    RETURNS NONE WHEN ACCESS IS GRANTED.
    When OAuth is enabled and no session exists, browser requests 
    (``Accept: text/html``) receive a **302** to ``/login``; programmatic clients receive **401** JSON.
    ``/ui/diagnostics`` is intentionally left open for operator debugging.
    """
    if not CONFIG["oauth_enabled"]:
        return None
    if session.get("user"):
        return None
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        return redirect(url_for("login"))
    return {"error": "authentication required"}, 401


def _authorize_global_read() -> Optional[Any]:
    """
    Authorize GET /zones and GET /debug/logs: machine signature, OAuth session, or open
    when neither ZONE_PUBLIC_KEY nor OAuth is enforcing access.
    """
    # Black-box docker-compose testdriver polls GET /zones without Ed25519 headers.
    # Zone POSTs from twoway remain signature-verified via _verify_zone_request.
    if CONFIG["is_dockertest_env"]:
        return None
    pub_key = _zone_public_key_configured()
    machine_ok = False
    if pub_key and _zone_auth_signature_header_present():
        gerr = _verify_global_machine_request()
        if gerr:
            return gerr[1], gerr[0]
        machine_ok = True
    if machine_ok:
        return None
    if not pub_key:
        if not CONFIG["oauth_enabled"]:
            return None
        if session.get("user"):
            return None
        return redirect(url_for("login"))
    if CONFIG["oauth_enabled"] and session.get("user"):
        return None
    if CONFIG["oauth_enabled"]:
        return redirect(url_for("login"))
    return {"error": "machine auth required"}, 401


def _authorize_zone_command_post(zonename: str) -> Optional[Any]:
    """
    Gate ``POST /zone/<zonename>/command``: Ed25519 when ``ZONE_PUBLIC_KEY`` is set,
    else OAuth session when enabled, else machine auth or ``DOCKERTEST`` allowance.

    Returns ``None`` when the request may proceed; otherwise a Flask response.
    """
    pub_key = _zone_public_key_configured()
    if pub_key:
        if _zone_auth_signature_header_present():
            err = _verify_zone_request(zonename)
            if err:
                return err[1], err[0]
        elif CONFIG["oauth_enabled"] and session.get("user"):
            pass
        elif CONFIG["oauth_enabled"]:
            return redirect(url_for("login"))
        else:
            # thermo/test testdriver posts commands without signatures; twoway still signs sensors.
            if not CONFIG["is_dockertest_env"]:
                return {"error": "machine auth required"}, 401
    elif CONFIG["oauth_enabled"] and not session.get("user"):
        return redirect(url_for("login"))
    return None


@app.route("/ui/diagnostics", methods=["GET"])
def ui_diagnostics() -> Any:
    """
    Bounded in-memory bundle: access tail, zone POST outcomes, uptime, flags.
    Not gated — same openness as ``GET /ui/context``. No durable state on DMZ.

    Operators can paste this JSON for support / export copies from the bundled UI textarea.
    """
    return _diagnostics_payload()


@app.route("/zone/<string:zonename>/sensors", methods=["POST"])
def update_sensors(zonename: str) -> Any:
    """
    Update a zone with sensors and (optionally) a piggybacked command.

    Body shape (preferred): ``{"sensors": {...}, "command": {...}}``.

    Legacy / backward-compat: a flat sensors dict (``{"temp_centigrade": ..., ...}``) is
    accepted and treated as the ``sensors`` payload with no piggybacked command. Both
    callers (twoway and the smoke test driver) sign the raw bytes, so no auth concerns.

    The optional ``command`` carries the latest onboard-side command and its
    ``created_dt``; DMZ's strictly-newer gate (see :func:`_replace_command_if_newer`)
    decides whether to replace the stored command. Receiver-stamps when missing.

    Machine auth (Ed25519 request signing) when ZONE_PUBLIC_KEY is set.
    """
    err = _verify_zone_request(zonename)
    if err:
        code_e, payload_e = err[0], err[1]
        det_e = ""
        if isinstance(payload_e, dict):
            det_e = str(payload_e.get("error", "") or "")
        _record_zone_sensor_attempt(
            zonename,
            request.path,
            "rejected",
            det_e,
            code_e,
        )
        return err[1], err[0]
    _record_zone_sensor_attempt(zonename, request.path, "accepted", "", 200)
    assertAuthAzZone(request)
    body = request.json or {}
    if isinstance(body, dict) and ("sensors" in body or "command" in body):
        sensors_body = body.get("sensors") or {}
        cmd_body = body.get("command")
    else:
        sensors_body = body
        cmd_body = None
    sns = Sensors(**sensors_body)
    _append_and_trim(sensors[zonename], sns)
    _log_full_zone_state(reason="sensors", zonename=zonename)
    if isinstance(cmd_body, dict) and cmd_body:
        _replace_command_if_newer(zonename, cmd_body, source="zone-sensors")
    _await_new_ui_command_or_timeout(zonename)
    _mark_zone_command_reply_sent(zonename)
    return _zone_response(zonename, True)


@app.route("/zone/<string:zonename>/command", methods=["POST"])
def update_command(zonename: str) -> Any:
    """
    Store the JSON body as the zone’s latest command and return the zone snapshot.
    Body checks: valid UTF-8, parse as JSON, all JSON strings 7-bit ASCII only.
    """
    if (denied := _authorize_zone_command_post(zonename)):
        return denied
    assertAuthAzZone(request)
    raw = request.get_data(cache=True)
    parsed, parse_err = _parse_validated_command_json(raw)
    if parse_err:
        return parse_err[0], parse_err[1]
    if isinstance(parsed, dict):
        decision = _replace_command_if_newer(zonename, parsed, source="zone-command")
        if decision == "accepted":
            _mark_ui_command_received(zonename)
    else:
        # Non-dict commands (legacy / test) cannot carry created_dt; keep prior behavior
        # of unconditional append so existing callers do not regress.
        _append_and_trim(commands[zonename], parsed)
        _log_full_zone_state(reason="command:legacy-nondict", zonename=zonename)
    return _zone_response(zonename, True)


def _environment_row_for_zone(zonename: str) -> Dict[str, Any]:
    """One table row: latest sensor snapshot for ``zonename`` (DMZ UI / ``GET /ui/context``)."""
    sns: Optional[Sensors] = _lastor(sensors[zonename])
    if sns is None:
        return {
            "zone": zonename,
            "temperature_centigrade": None,
            "humidity_percent": None,
            "time": None,
        }
    d = sns.dict()
    return {
        "zone": zonename,
        "temperature_centigrade": d.get("temp_centigrade"),
        "humidity_percent": d.get("humid_percent"),
        "time": d.get("created_dt") or None,
    }


@app.route("/ui/context", methods=["GET"])
def ui_context() -> Any:
    """
    JSON for the shared thermo UI: all zones with state, environment table per zone.

    Gated on OAuth session when GOOGLE_CLIENT_ID is configured; open otherwise.
    Unauthenticated browser requests (``Accept`` contains ``text/html``) receive **302** to ``/login``.
    Authenticated browser requests are **302**'d to the public HTML UI root (same rules as after **`GET /authorize`**), not JSON.
    API clients (no ``text/html`` in ``Accept``) receive JSON or **401** JSON when unauthenticated.
    """
    if (denied := _authorize_ui()):
        return denied
    if (
        CONFIG["oauth_enabled"]
        and session.get("user")
        and "text/html" in (request.headers.get("Accept") or "")
    ):
        return _redirect_public_ui_home_or_503()
    all_zones = sorted(set(commands.keys()) | set(sensors.keys()))
    env_rows = [_environment_row_for_zone(z) for z in all_zones]
    zone_states = {z: _zone_response(z, False) for z in all_zones}
    return {
        "zones": all_zones,
        "environments": env_rows,
        "zone_states": zone_states,
    }


@app.route("/ui/command", methods=["POST"])
def ui_command() -> Any:
    """
    Store command JSON for ``zone`` (same storage as ``POST /zone/<z>/command``).

    Gated on OAuth session when GOOGLE_CLIENT_ID is configured; open otherwise.
    """
    if (denied := _authorize_ui()):
        return denied
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {"error": "json object required"}, 400
    zonename_raw = body.get("zone")
    if not isinstance(zonename_raw, str) or not zonename_raw.strip():
        return {"error": "zone string required"}, 400
    zonename = zonename_raw.strip()
    cmd = body.get("command")
    if not isinstance(cmd, dict):
        return {"error": "command object required"}, 400
    raw = json.dumps(cmd, separators=(",", ":")).encode("utf-8")
    parsed, parse_err = _parse_validated_command_json(raw)
    if parse_err:
        return parse_err[0], parse_err[1]
    if isinstance(parsed, dict):
        decision = _replace_command_if_newer(zonename, parsed, source="ui-command")
        if decision == "accepted":
            _mark_ui_command_received(zonename)
    else:
        _append_and_trim(commands[zonename], parsed)
        _log_full_zone_state(reason="ui-command:legacy-nondict", zonename=zonename)
    snap = _zone_response(zonename, True)
    return {
        "zone": zonename,
        "command": snap.get("command"),
        "sensors": snap.get("sensors"),
        "time": datetime.now().isoformat(),
        "sent": None,
        "environment": None,
        "unchanged": None,
        "reason": None,
    }


@app.route("/zones", methods=["GET"])
def get_zones() -> Any:
    """
    Stateless query.  Read ALL zone states, including pending commands.
    """
    if (denied := _authorize_global_read()):
        return denied
    assertAuthAzZone(request)
    all_zones = sorted(set(commands.keys()) | set(sensors.keys()))
    res = {zonename: _zone_response(zonename, False) for zonename in all_zones}
    return res


@app.route("/debug/logs", methods=["GET"])
def debug_logs() -> Any:
    """Return bounded in-memory access log plus diagnostics (same data as ``/ui/diagnostics``)."""
    if (denied := _authorize_global_read()):
        return denied
    assertAuthAzZone(request)
    bundle = _diagnostics_payload()
    logs_list = list(bundle.pop("access_log"))
    return {"logs": logs_list, **bundle}


if CONFIG["is_ui_integration_env"]:

    @app.route("/test/ui_session", methods=["GET"])
    def test_ui_session() -> Any:
        """Integration tests only (``ENV=UI_INTEGRATION``): set a logged-in session."""
        session["user"] = {"email": "integration-test@gmail.com"}
        return {"ok": True, "email": "integration-test@gmail.com"}


@app.route("/test_reset", methods=["POST"])
def test_reset() -> Any:
    """
    Update the zone state for testing.
    """
    assertAuthAzZone(request)
    updates = request.json or {}
    if "commands" in updates:
        commands.clear()
        commands.update(updates.get("commands", {}))
    if "sensors" in updates:
        sensors.clear()
        sensors.update(updates.get("sensors", {}))
    _ui_command_received_at.clear()
    _last_zone_command_reply_at.clear()
    _zone_attempts.clear()
    _access_log.clear()
    _reset_repeat_log_suppression()
    _log_full_zone_state(reason="test_reset")
    return '"ok"'


if __name__ == "__main__":
    install_config_reload_signal()
    logger.info(
        "SIGUSR1 reloads runtime config from %s (source: thermo/dmz/dmz.conf at image build)",
        dmz_app_env_path(),
    )
    app.run(host="0.0.0.0", port=CONFIG["port"])
