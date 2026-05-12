"""
This lives on the WWW.

Accept backend long-poll connections from trusted zone. (with trust token)

Accept request; redirect to google auth, if success push to backend long poll

Backend will return result in next query, with association ID.

Long-term, make the backend connection into a TCP based queue (connection is awkward bit)
"""

from collections import deque, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

from flask import Flask, g, redirect, request, session, url_for
from pydantic import BaseModel, validator

JSON = Union[Dict, str, int]

# Access log: circular buffer of {method, path, status, ts}
ACCESS_LOG_MAXLEN = 500
_access_log: Deque[Dict[str, Any]] = deque(maxlen=ACCESS_LOG_MAXLEN)

# In-memory only (no disk): recent zone POST outcomes for operator debugging (twoway ↔ DMZ).
_ZONE_ATTEMPT_MAXLEN = 200
_zone_attempts: Deque[Dict[str, Any]] = deque(maxlen=_ZONE_ATTEMPT_MAXLEN)
_START_MONO: float = time.time()
_START_UTC_ISO: str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        logger.debug(
            "zone command obsolete; ignored zone=%s source=%s incoming=%s stored=%s",
            zonename,
            source,
            incoming_dt,
            last_dt,
        )
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


def _log_full_zone_state(reason: str, zonename: Optional[str] = None) -> None:
    """Emit a single DEBUG line with the full ``{zone: {command, sensors}}`` snapshot.

    Called after every mutation of ``commands`` / ``sensors`` so the log shows the
    complete authoritative state at each transition. ``reason`` and ``zonename`` (if any)
    explain what just changed; the snapshot itself is the entire DMZ state, not just the
    mutated zone, since cross-zone visibility is the point.
    """
    try:
        snap = _full_zone_state_snapshot()
        logger.debug(
            "zone state changed reason=%s zone=%s state=%s",
            reason,
            zonename or "*",
            json.dumps(snap, default=str, sort_keys=True),
        )
    except Exception as e:
        logger.debug("zone state log failed reason=%s err=%s", reason, e)


# Logging: isodatetime, DEBUG, to stdout (Docker / process manager capture)
_log_handler = logging.StreamHandler(sys.stdout)
_log_handler.setLevel(logging.DEBUG)
_log_fmt = logging.Formatter(
    "%(asctime)s.%(msecs)03dZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
)
_log_fmt.converter = time.gmtime
_log_handler.setFormatter(_log_fmt)
logger = logging.getLogger("dmz")
logger.setLevel(logging.DEBUG)
logger.addHandler(_log_handler)
logger.propagate = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")

# OAuth enabled only when credentials are set
_oauth_enabled = bool(app.config["GOOGLE_CLIENT_ID"])


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
    pattern = (os.environ.get("ALLOWED_EMAIL_PATTERN") or "").strip()
    if pattern:
        try:
            return re.fullmatch(pattern, email, flags=re.IGNORECASE) is not None
        except re.error as exc:
            logger.error("ALLOWED_EMAIL_PATTERN is invalid: %s", exc)
            return False
    legacy = (os.environ.get("ALLOWED_EMAIL") or "").strip()
    if legacy:
        return email == legacy.lower()
    return email == "jovlinger@gmail.com"


if _oauth_enabled:
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
    raw_inline = os.environ.get("ZONE_PUBLIC_KEY")
    raw_path = os.environ.get("ZONE_PUBLIC_KEY_PATH")
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
    google_id = str(app.config.get("GOOGLE_CLIENT_ID") or "")
    google_last4 = google_id[-4:] if len(google_id) >= 4 else ("n/a" if not google_id else google_id)
    allow_pat = (os.environ.get("ALLOWED_EMAIL_PATTERN") or "").strip()
    allowlist_mode = "regex" if allow_pat else ("legacy_env" if (os.environ.get("ALLOWED_EMAIL") or "").strip() else "dev_default")
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
        "oauth_enabled": _oauth_enabled,
        "google_client_id_last4": google_last4,
        "allowlist_mode": allowlist_mode,
        "allowlist_pattern_sha256_last4": allow_pat_digest,
        "flask_secret_key_last4": secret_last4,
        "flask_secret_is_default_dev": default_dev,
        "env": os.environ.get("ENV"),
    }


def _log_auth_startup() -> None:
    d = _auth_config_detail()
    logger.info(
        "auth startup: zone_enforced=%s zone_src=%s zone_pub_sha256_last4=%s "
        "oauth=%s google_client_id_last4=%s allowlist_mode=%s allowlist_pat_sha256_last4=%s "
        "flask_secret_last4=%s default_dev_secret=%s env=%s port=%s",
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
        os.environ.get("PORT", "5000"),
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
        "uptime_seconds": round(time.time() - _START_MONO, 3),
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
        req_size = (
            request.content_length
            if request.content_length is not None
            else len(request.get_data())
        )
        resp_size = getattr(response, "content_length", None) or "-"
        logger.debug(
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
_ui_command_received_mono: Dict[str, float] = defaultdict(float)
_last_zone_command_reply_mono: Dict[str, float] = defaultdict(float)
_zone_command_clock_lock = threading.Lock()
### END STATE

# Overridable via env (e2e subprocess) or monkeypatch on this module (dmz unit tests).
LONG_POLL_TIMEOUT_SECS: float = float(os.environ.get("LONG_POLL_TIMEOUT_SECS", "10"))
LONG_POLL_SLEEP_SECS: float = float(os.environ.get("LONG_POLL_SLEEP_SECS", "1.0"))


def _lastor(lst: List[Any], default: Optional[Any] = None) -> Any:
    if not lst:
        return default
    return lst[-1]


def _mark_ui_command_received(zonename: str) -> float:
    now_mono = time.monotonic()
    with _zone_command_clock_lock:
        _ui_command_received_mono[zonename] = now_mono
    return now_mono


def _mark_zone_command_reply_sent(zonename: str) -> float:
    now_mono = time.monotonic()
    with _zone_command_clock_lock:
        _last_zone_command_reply_mono[zonename] = now_mono
    return now_mono


def _await_new_ui_command_or_timeout(zonename: str) -> None:
    """
    Long-poll gate for zone POSTs.

    Snapshot the zone's last reply-sent timestamp once at request start. Wait until UI has
    posted a newer command timestamp than that snapshot, or until timeout.

    Snapshot semantics intentionally allow overlapping POSTs from the same zone: each thread
    compares against its own start-time baseline so one thread updating "last sent" does not
    force siblings to keep waiting after a new UI command arrives.
    """
    started = time.monotonic()
    with _zone_command_clock_lock:
        sent_baseline = _last_zone_command_reply_mono[zonename]
    while True:
        with _zone_command_clock_lock:
            ui_last = _ui_command_received_mono[zonename]
        if ui_last > sent_baseline:
            return
        if (time.monotonic() - started) >= LONG_POLL_TIMEOUT_SECS:
            return
        time.sleep(LONG_POLL_SLEEP_SECS)


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


@app.route("/")
def root() -> Any:
    """Same-origin post-OAuth step: ``/authorize`` redirects here, then we send the browser onward."""
    origin = (os.environ.get("THERMO_UI_PUBLIC_ORIGIN") or "").strip().rstrip("/")
    if origin:
        return redirect(f"{origin}/")
    return redirect(url_for("ui_context"))


@app.route("/login")
def login() -> Any:
    """Redirect to Google OAuth. Restricted to gmail.com; allowlist via regex or legacy env."""
    if not _oauth_enabled:
        return {"error": "OAuth not configured"}, 400
    redirect_uri = url_for("authorize", _external=True)
    return oauth.google.authorize_redirect(redirect_uri, hd="gmail.com")


@app.route("/authorize")
def authorize() -> Any:
    """OAuth callback. Verify email against allowlist, then set session."""
    if not _oauth_enabled:
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
    return redirect("/")


@app.route("/logout")
def logout() -> Any:
    """Clear session."""
    session.pop("user", None)
    return redirect(url_for("login") if _oauth_enabled else url_for("get_zones"))


def _verify_zone_request(zonename: str) -> Optional[tuple[int, Any]]:
    """Verify Ed25519 machine auth. Returns (status_code, response) on failure, None on success."""
    pub_key = os.environ.get("ZONE_PUBLIC_KEY") or os.environ.get(
        "ZONE_PUBLIC_KEY_PATH"
    )
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
    pub_key = os.environ.get("ZONE_PUBLIC_KEY") or os.environ.get(
        "ZONE_PUBLIC_KEY_PATH"
    )
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

    Returns None when access is granted. When OAuth is enabled and no session
    exists, browser requests (Accept: text/html) receive a 302 to /login;
    programmatic clients (Accept: application/json) receive 401 JSON.
    /ui/diagnostics is intentionally left open for operator debugging.
    """
    if not _oauth_enabled:
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
    if os.environ.get("ENV") == "DOCKERTEST":
        return None
    pub_key = os.environ.get("ZONE_PUBLIC_KEY") or os.environ.get(
        "ZONE_PUBLIC_KEY_PATH"
    )
    machine_ok = False
    if pub_key:
        try:
            from zone_auth import HEADER_SIGNATURE
        except ImportError:
            HEADER_SIGNATURE = "X-Zone-Signature"
        if request.headers.get(HEADER_SIGNATURE):
            gerr = _verify_global_machine_request()
            if gerr:
                return gerr[1], gerr[0]
            machine_ok = True
    if machine_ok:
        return None
    if not pub_key:
        if not _oauth_enabled:
            return None
        if session.get("user"):
            return None
        return redirect(url_for("login"))
    if _oauth_enabled and session.get("user"):
        return None
    if _oauth_enabled:
        return redirect(url_for("login"))
    return {"error": "machine auth required"}, 401


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
    pub_key = os.environ.get("ZONE_PUBLIC_KEY") or os.environ.get(
        "ZONE_PUBLIC_KEY_PATH"
    )
    if pub_key:
        try:
            from zone_auth import HEADER_SIGNATURE
        except ImportError:
            HEADER_SIGNATURE = "X-Zone-Signature"
        if request.headers.get(HEADER_SIGNATURE):
            err = _verify_zone_request(zonename)
            if err:
                return err[1], err[0]
        elif _oauth_enabled and session.get("user"):
            pass
        elif _oauth_enabled:
            return redirect(url_for("login"))
        else:
            # thermo/test testdriver posts commands without signatures; twoway still signs sensors.
            if os.environ.get("ENV") != "DOCKERTEST":
                return {"error": "machine auth required"}, 401
    elif _oauth_enabled and not session.get("user"):
        return redirect(url_for("login"))
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
    Browser clients are redirected to /login; API clients receive 401 JSON.
    """
    denied = _authorize_ui()
    if denied is not None:
        return denied
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
    denied = _authorize_ui()
    if denied is not None:
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
    denied = _authorize_global_read()
    if denied is not None:
        return denied
    assertAuthAzZone(request)
    all_zones = sorted(set(commands.keys()) | set(sensors.keys()))
    res = {zonename: _zone_response(zonename, False) for zonename in all_zones}
    return res


@app.route("/debug/logs", methods=["GET"])
def debug_logs() -> Any:
    """Return bounded in-memory access log plus diagnostics (same data as ``/ui/diagnostics``)."""
    denied = _authorize_global_read()
    if denied is not None:
        return denied
    assertAuthAzZone(request)
    bundle = _diagnostics_payload()
    logs_list = list(bundle.pop("access_log"))
    return {"logs": logs_list, **bundle}


if os.environ.get("ENV") == "UI_INTEGRATION":

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
    _ui_command_received_mono.clear()
    _last_zone_command_reply_mono.clear()
    _zone_attempts.clear()
    _access_log.clear()
    _log_full_zone_state(reason="test_reset")
    return '"ok"'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
