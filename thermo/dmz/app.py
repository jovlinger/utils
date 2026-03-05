"""
This lives on the WWW.

Accept backend long-poll connections from trusted zone. (with trust token)

Accept request; redirect to google auth, if success push to backend long poll

Backend will return result in next query, with association ID.

Long-term, make the backend connection into a TCP based queue (connection is awkward bit)
"""

from collections import deque, defaultdict
from datetime import datetime
import os
from typing import Any, Callable, Deque, Dict, List, Union, Optional

from flask import Flask, g, redirect, request, session, url_for
from pydantic import BaseModel

JSON = Union[Dict, str, int]

# Access log: circular buffer of {method, path, status, ts}
ACCESS_LOG_MAXLEN = 500
_access_log: Deque[Dict[str, Any]] = deque(maxlen=ACCESS_LOG_MAXLEN)


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

    def model_post_init(self, __context) -> None:
        if not self.created_dt:
            self.created_dt = datetime.now().isoformat()


class IRCommand(BaseModel):
    lolidk: str = ""
    created_dt: str = ""
    last_access_dt: str = ""

    def model_post_init(self, __context) -> None:
        if not self.created_dt:
            self.created_dt = datetime.now().isoformat()

    def model_mark_accessed(self) -> None:
        self.last_access_dt = datetime.now().isoformat()


class ZoneState(BaseModel):
    command: Optional[IRCommand] = None
    sensors: Optional[Sensors] = None


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")

# OAuth enabled only when credentials are set
_oauth_enabled = bool(app.config["GOOGLE_CLIENT_ID"])
ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "jovlinger@gmail.com")

if _oauth_enabled:
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
        authorize_params={"hd": "gmail.com"},
    )


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
    return response


def _login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Require OAuth login for human-facing endpoints. No-op when OAuth disabled."""

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not _oauth_enabled:
            return f(*args, **kwargs)
        if not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    wrapped.__name__ = f.__name__
    return wrapped


def assertAuthAzZone(req: Any) -> None:
    """Zone auth placeholder. Machine auth (request signing) will replace this."""
    assert req


### BEGIN STATE (make this sqlite)
commands: Dict[str, List[IRCommand]] = defaultdict(list)
sensors: Dict[str, List[Sensors]] = defaultdict(list)
### END STATE


def _lastor(lst: List[Any], default: Optional[Any] = None) -> Any:
    if not lst:
        return default
    return lst[-1]


def _zone_response(zonename: str, update_access: bool) -> JSON:
    """Craft the json for one zone's response"""
    cmd = _lastor(commands[zonename])
    sns = _lastor(sensors[zonename])
    if cmd and update_access:
        cmd.model_mark_accessed()
    ret = ZoneState(command=cmd, sensors=sns).model_dump()
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


@app.route("/login")
def login() -> Any:
    """Redirect to Google OAuth. Restricted to gmail.com; only ALLOWED_EMAIL accepted."""
    if not _oauth_enabled:
        return {"error": "OAuth not configured"}, 400
    redirect_uri = url_for("authorize", _external=True)
    return oauth.google.authorize_redirect(redirect_uri, hd="gmail.com")


@app.route("/authorize")
def authorize() -> Any:
    """OAuth callback. Verify email is ALLOWED_EMAIL, then set session."""
    if not _oauth_enabled:
        return redirect(url_for("get_zones"))
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        return {"error": "OAuth failed"}, 400
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not email.endswith("@gmail.com"):
        return {"error": "Only gmail.com accounts allowed"}, 403
    if email != ALLOWED_EMAIL.lower():
        return {"error": f"Access restricted to {ALLOWED_EMAIL}"}, 403
    session["user"] = {"email": email}
    return redirect(url_for("get_zones"))


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


@app.route("/zone/<string:zonename>/sensors", methods=["POST"])
def update_sensors(zonename: str) -> Any:
    """
    Update a zone with UpdateZone. Read this zone's states.
    Register the zone if not already there.
    Machine auth (Ed25519 request signing) when ZONE_PUBLIC_KEY is set.
    """
    err = _verify_zone_request(zonename)
    if err:
        return err[1], err[0]
    assertAuthAzZone(request)
    sns = Sensors(**request.json)
    _append_and_trim(sensors[zonename], sns)
    return _zone_response(zonename, True)


@app.route("/zone/<string:zonename>/command", methods=["POST"])
@_login_required
def update_command(zonename: str) -> Any:
    """
    Update a zone with UpdateZone. Read this zone's states.
    Register the zone if not already there
    """
    assertAuthAzZone(request)
    js = request.json
    cmd = IRCommand(**js)
    _append_and_trim(commands[zonename], cmd)
    return _zone_response(zonename, True)


@app.route("/zones", methods=["GET"])
@_login_required
def get_zones() -> Any:
    """
    Stateless query.  Read ALL zone states, including pending commands.
    """
    assertAuthAzZone(request)
    res = {zonename: _zone_response(zonename, False) for zonename in sensors}
    return res


@app.route("/debug/logs", methods=["GET"])
@_login_required
def debug_logs() -> Any:
    """Return bounded in-memory access log. Auth required."""
    assertAuthAzZone(request)
    return {"logs": list(_access_log)}


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
    return '"ok"'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
