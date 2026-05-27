"""
Main entry point.

Use as an import for testing. Must use the flask cmd line to start
"""

from collections import defaultdict, deque
from datetime import datetime
import json
import logging
import os
from typing import Any, Dict, FrozenSet, Optional, Tuple

from flask import Flask, request

from common import is_test_env
from common.constants import help_msg
from common.deployment_config import OnboardDeploymentConfig, config_from_environ
from common.heatpumpirctl import State
from common.logging_config import (
    configure_logging,
    format_kv,
    get_log_buffer_capacity,
    get_log_level,
    get_recent_log_messages,
    set_log_level,
)
from hardware.pizero2w.anavilib import HTU21D, send_daikin_state

configure_logging("onboard")
# Example: 2026-05-17T13:40:23.905Z INFO onboard app:136 request path='/environment'
logger = logging.getLogger(__name__)

app = Flask(__name__)


c = defaultdict(lambda: 0)

MANAGE_TOKEN_ENVVAR = "MANAGE_TOKEN"


def _onboard_deployment_config() -> OnboardDeploymentConfig:
    """Current onboard deployment config from environment variables."""
    return config_from_environ()


def _onboard_ui_zone_name() -> str:
    """Zone label for UI and ``GET /ui/context`` (defaults when unset)."""
    return _onboard_deployment_config().zone_name


def _manage_auth_ok() -> bool:
    """Allow management operations only with a matching token."""
    token = os.environ.get(MANAGE_TOKEN_ENVVAR, "")
    presented = request.headers.get("X-Manage-Token", "")
    return bool(token and presented and token == presented)


def _state_snapshot() -> Dict[str, Any]:
    """Return an internal state snapshot for forensics and testing."""
    deployment = _onboard_deployment_config()
    return {
        "time": datetime.now().isoformat(),
        "pid": os.getpid(),
        "log_level": get_log_level(),
        "log_path": os.environ.get("LOG_PATH"),
        "deployment": deployment.to_public_dict(),
        "fake_sensor": {
            "temperature_centigrade": _round1(_fake_temp),
            "humidity_percent": _round1(_fake_humid),
        },
        "daikin_queue_size": len(daikin_cmds),
        "daikin_queue_capacity": DAIKIN_CMDS_MAXLEN,
        "env": {
            "ENV": os.environ.get("ENV"),
            "PORT": os.environ.get("PORT"),
            "DMZ_URL": os.environ.get("DMZ_URL"),
        },
    }


def _active_log_path() -> Optional[str]:
    return os.environ.get("LOG_PATH") or os.environ.get("LOG_PATH_APP")


def _mount_info_for_path(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {"path": None, "available": False, "is_tmpfs": None}
    real_path = os.path.realpath(path)
    probe_path = real_path if os.path.exists(real_path) else os.path.dirname(real_path)
    best: Dict[str, Any] = {}
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as f:
            for raw in f:
                parts = raw.rstrip("\n").split(" ")
                if " - " not in raw or len(parts) < 10:
                    continue
                sep = parts.index("-")
                mount_point = parts[4].replace("\\040", " ")
                fs_type = parts[sep + 1]
                if probe_path == mount_point or probe_path.startswith(mount_point.rstrip("/") + "/"):
                    if len(mount_point) > len(best.get("mount_point", "")):
                        best = {
                            "mount_point": mount_point,
                            "fs_type": fs_type,
                        }
    except OSError:
        best = {}

    fs_type = best.get("fs_type")
    tmpfs_like_prefix = real_path.startswith(("/run/", "/tmp/", "/dev/shm/"))
    return {
        "path": path,
        "real_path": real_path,
        "available": True,
        "mount_point": best.get("mount_point"),
        "fs_type": fs_type,
        "is_tmpfs": bool(fs_type == "tmpfs" or (fs_type is None and tmpfs_like_prefix)),
    }


def _parse_exit_code(value: Any) -> int:
    code = int(value)
    if code < 1 or code > 255:
        raise ValueError("code must be in [1,255]")
    return code


def _management_action(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    action = str(payload.get("action", "")).strip().lower()
    if not action:
        return {"error": "missing action"}, 400

    if action == "inject_log":
        level_name = str(payload.get("level", "INFO")).upper().strip()
        message = str(payload.get("message", "injected-log"))
        level = getattr(logging, level_name, None)
        if not isinstance(level, int):
            return {"error": "invalid level"}, 400
        logger.log(level, "manage: injected log message=%r", message)
        return {
            "ok": True,
            "action": action,
            "level": level_name,
            "message": message,
        }, 200

    if action == "assert":
        msg = str(payload.get("message", "management assertion failure"))
        logger.info("management assert%s", format_kv(message=msg))
        raise AssertionError(msg)

    if action == "raise":
        msg = str(payload.get("message", "management runtime failure"))
        logger.info("management raise%s", format_kv(message=msg))
        raise RuntimeError(msg)

    if action == "fatal":
        code = _parse_exit_code(payload.get("code", 99))
        logger.info("management fatal exit%s", format_kv(code=code))
        os._exit(code)

    if action == "set_log_level":
        level_name = str(payload.get("level", "")).strip()
        updated = set_log_level(level_name)
        if not updated:
            return {"error": "invalid level"}, 400
        logger.info("management set log level%s", format_kv(log_level=updated))
        return {"ok": True, "action": action, "level": updated}, 200

    if action == "reset":
        global _fake_temp, _fake_humid, _last_daikin_ir_fingerprint, _last_applied_state
        global _last_command_created_dt
        _fake_temp = None
        _fake_humid = None
        _last_daikin_ir_fingerprint = None
        _last_applied_state = State()
        _last_command_created_dt = None
        daikin_cmds.clear()
        logger.info("management reset state")
        return {"ok": True, "action": action}, 200

    return {"error": "unknown action"}, 400


@app.route("/<path:path>")
def root(path):
    """This is just a test route to make sure the server is running."""
    global c
    logger.info("request%s", format_kv(path=path))
    c[path] += 1
    return f"<P>Hello my name is {path} / {c} </P>"


@app.route("/help")
@app.route("/about")
def help():
    return {"msg": help_msg}


# Test override: when set, /environment returns these instead of sensor
_fake_temp: Optional[float] = None
_fake_humid: Optional[float] = None


def _round1(x: Optional[float]) -> Optional[float]:
    return round(x, 1) if x is not None else None


def _last_command_with_created_dt() -> Optional[Dict[str, Any]]:
    """Return ``{...state fields..., "created_dt": ...}`` for the last accepted command.

    Returns ``None`` when no command has ever been applied (cold start). Twoway uses this
    to forward the most recent onboard-side command (and its origin timestamp) to DMZ;
    DMZ's strictly-newer gate then decides whether to replace its stored command.
    """
    if _last_command_created_dt is None:
        return None
    cmd = dict(_last_applied_state.to_json())
    cmd["created_dt"] = _last_command_created_dt
    return cmd


def _environment_dict() -> Dict[str, Any]:
    """Current environment payload + last-applied command (same shape as GET /environment).

    The ``command`` field carries the last command applied on this onboard (and its
    ``created_dt``) so twoway can propagate it to DMZ in a single POST. ``None`` until
    the first command is applied. (TODO: rename endpoint to ``/state`` -- the response
    is no longer just the environment readings.)
    """
    global _fake_temp, _fake_humid
    ts = datetime.now()
    cmd = _last_command_with_created_dt()
    if _fake_temp is not None and _fake_humid is not None:
        return {
            "temperature_centigrade": _round1(_fake_temp),
            "humidity_percent": _round1(_fake_humid),
            "time": ts.isoformat(),
            "command": cmd,
        }
    try:
        htu = HTU21D.singleton()
        temp = htu.temperature_centigrade()
        hum = htu.humidity_percent()
        return {
            "temperature_centigrade": _round1(temp),
            "humidity_percent": _round1(hum),
            "time": ts.isoformat(),
            "command": cmd,
        }
    except Exception as e:
        logger.info("environment%s", format_kv(error=str(e)))
        return {
            "temperature_centigrade": None,
            "humidity_percent": None,
            "time": ts.isoformat(),
            "command": cmd,
        }


@app.route("/environment", methods=["GET"])
def environment():
    """Return current temperature/humidity + last-applied command (TODO: rename to /state).

    See :func:`_environment_dict`.
    """
    return _environment_dict()


@app.route("/test/inject_readings", methods=["POST"])
def test_inject_readings():
    """Set fake sensor values for testing. Body: {temp_centigrade, humid_percent}."""
    global _fake_temp, _fake_humid
    if not is_test_env():
        return {"error": "only in test env"}, 403
    js = request.json or {}
    _fake_temp = js.get("temp_centigrade")
    _fake_humid = js.get("humid_percent")
    return {"temp_centigrade": _fake_temp, "humid_percent": _fake_humid}


@app.route("/test/reset", methods=["POST"])
def test_reset():
    """Clear in-memory command history and state for test isolation."""
    global _last_daikin_ir_fingerprint, _last_applied_state, _last_command_created_dt
    if not is_test_env():
        return {"error": "only in test env"}, 403
    daikin_cmds.clear()
    _last_daikin_ir_fingerprint = None
    _last_applied_state = State()
    _last_command_created_dt = None
    return {"ok": True}


DAIKIN_CMDS_MAXLEN = 100
daikin_cmds: deque[tuple[datetime, State, bool]] = deque(maxlen=DAIKIN_CMDS_MAXLEN)

# Keys understood by heatpumpirctl.State.from_json (canonical lowercase).
_STATE_FROM_JSON_KEYS: FrozenSet[str] = frozenset(
    {
        "power",
        "mode",
        "temp_c",
        "half_c",
        "fan",
        "swing",
        "powerful",
        "econo",
        "comfort",
        "timer_on_minutes",
        "timer_off_minutes",
        "timer_on_active",
        "timer_off_active",
    }
)


def _command_dict_for_state(cmd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the dict passed to State.from_json from a raw zone command.

    DMZ/twoway may carry noise (lolidk, created_dt, last_access_dt). CLI callers
    may use any casing (FAN=F1). Only keys in _STATE_FROM_JSON_KEYS are kept,
    renamed to lowercase.
    """
    out: Dict[str, Any] = {}
    for key, val in cmd.items():
        canon = str(key).lower()
        if canon in _STATE_FROM_JSON_KEYS:
            out[canon] = val
    return out


# Last IR payload successfully sent (JSON fingerprint); identical State skips send_daikin_state.
_last_daikin_ir_fingerprint: Optional[str] = None

# Last State applied on /daikin (UI or twoway); merge baseline for partial DMZ/twoway commands.
# Starts at a comfortable default (see heatpumpirctl.State: off, AUTO, 20°C).
_last_applied_state: State = State()

# created_dt of the last accepted command. Used to gate twoway-shaped writes:
# the from-twoway path applies a command only if its created_dt is *strictly newer*
# than this. UI-direct writes (POST /ui/command, plain POST /daikin) always apply
# and update this to ``now()`` if the incoming command does not carry one. None
# means "no command has ever been applied" -- the first write always wins.
_last_command_created_dt: Optional[str] = None


def _daikin_state_fingerprint(state: State) -> str:
    """Stable string for IR-relevant fields (no wall-clock in State)."""
    return json.dumps(state.to_json(), sort_keys=True)


@app.route("/daikin", methods=["GET"])
def get_daikin():
    """Return list of {time, command} for recent daikin commands sent (newest first).

    When the rolling queue is empty, returns one entry built from the current
    last-applied State (cold start: off, AUTO, 20°C) with ``time`` null.
    """
    if not daikin_cmds:
        return [{"time": None, "command": _last_applied_state.to_json()}]
    return [
        {"time": ts.isoformat(), "command": s.to_json()}
        for ts, s, _ in reversed(list(daikin_cmds))
    ]


@app.route("/logs", methods=["GET"])
def logs():
    """Return last N lines from LOG_PATH (rolling buffer). JSON {lines}, newest first."""
    path = os.environ.get("LOG_PATH")
    if not path or not os.path.isfile(path):
        return {"lines": [], "path": path}, 200
    try:
        with open(path) as f:
            lines = f.readlines()
        tail = [ln.rstrip("\n") for ln in lines[-200:]]
        return {"lines": list(reversed(tail))}
    except OSError:
        return {"lines": []}, 200


@app.route("/healthz", methods=["GET"])
def healthz():
    """Basic onboard app health plus recent in-memory log messages."""
    try:
        limit = int(request.args.get("n", "50"))
    except ValueError:
        limit = 50
    limit = max(0, min(limit, get_log_buffer_capacity()))
    log_path = _active_log_path()
    snapshot = _state_snapshot()
    return {
        "ok": True,
        "service": "onboard-app",
        "hardware_backend": "pizero2w",
        "time": snapshot["time"],
        "pid": snapshot["pid"],
        "log_level": snapshot["log_level"],
        "deployment": snapshot["deployment"],
        "queues": {
            "daikin_size": snapshot["daikin_queue_size"],
            "daikin_capacity": snapshot["daikin_queue_capacity"],
        },
        "log_storage": _mount_info_for_path(log_path),
        "log_buffer": {
            "capacity": get_log_buffer_capacity(),
            "returned": limit,
            "lines": get_recent_log_messages(limit),
        },
    }, 200


@app.route("/manage", methods=["GET"])
def manage_get():
    """Return internal state for diagnostics."""
    if not _manage_auth_ok():
        return {"error": "forbidden"}, 403
    return _state_snapshot(), 200


@app.route("/manage", methods=["POST"])
def manage_post():
    """Execute one management action for fault-injection or runtime tuning."""
    if not _manage_auth_ok():
        return {"error": "forbidden"}, 403
    js = request.json or {}
    if not isinstance(js, dict):
        return {"error": "json object required"}, 400
    return _management_action(js)


def _daikin_response_payload(ts_iso: str, state: State, **extra: Any) -> Dict[str, Any]:
    """JSON for successful /daikin responses (authoritative command + environment)."""
    pl: Dict[str, Any] = {
        "time": ts_iso,
        "command": state.to_json(),
        "environment": _environment_dict(),
    }
    pl.update(extra)
    return pl


def _latest_command_dict_for_ui() -> Dict[str, Any]:
    """Authoritative command JSON for the onboard zone (matches ``GET /daikin`` newest)."""
    global _last_applied_state
    if not daikin_cmds:
        return _last_applied_state.to_json()
    _ts, state, _succ = daikin_cmds[-1]
    return state.to_json()


def handle_set_daikin_body(js: Dict[str, Any]) -> Tuple[Any, int]:
    """Shared implementation for ``POST /daikin`` and ``POST /ui/command``.

    Twoway-shaped requests (``"sensors"`` key present in body) are gated on the
    command's ``created_dt``: the command is applied only when its ``created_dt`` is
    *strictly newer* than the most recently accepted one (``_last_command_created_dt``).
    Obsolete twoway commands log at DEBUG and return ``sent: False, reason: "obsolete"``.
    UI-direct requests (no ``"sensors"`` key) always apply and stamp ``created_dt`` with
    receiver wall-clock when the body did not provide one.
    """
    global _last_daikin_ir_fingerprint, _last_applied_state, _last_command_created_dt
    logger.debug("set_daikin%s", format_kv(js=js))
    cmd_obj = js.get("command") if isinstance(js, dict) else js
    if cmd_obj is None:
        logger.debug("no command in zone state; skipping /daikin")
        return {
            "sent": False,
            "reason": "no command",
            "environment": _environment_dict(),
        }, 200
    if not isinstance(cmd_obj, dict):
        logger.info("Invalid command: expected dict, got %s", type(cmd_obj).__name__)
        return {"error": "EmptyCmd"}, 400
    merged = _command_dict_for_state(cmd_obj)
    if not merged:
        logger.debug(
            "set_daikin no state fields in command%s",
            format_kv(keys=list(cmd_obj.keys())),
        )
        return {
            "sent": False,
            "reason": "no state fields in command",
            "environment": _environment_dict(),
        }, 200

    from_dmz_twoway = isinstance(js, dict) and "sensors" in js
    incoming_created_dt = (
        cmd_obj.get("created_dt") if isinstance(cmd_obj, dict) else None
    )

    if from_dmz_twoway:
        # Strictly-newer gate: skip stale round-trips of our own command (or older DMZ
        # commands that arrived after a fresher local change).  No created_dt at all on
        # an inbound twoway command is also stale: we cannot prove it is newer.
        if incoming_created_dt is None:
            logger.debug(
                "twoway command has no created_dt; treating as obsolete%s",
                format_kv(tracked=_last_command_created_dt),
            )
            return {
                "sent": False,
                "reason": "obsolete (missing created_dt)",
                "environment": _environment_dict(),
            }, 200
        if (
            _last_command_created_dt is not None
            and incoming_created_dt <= _last_command_created_dt
        ):
            logger.debug(
                "twoway command obsolete; ignored%s",
                format_kv(
                    incoming_created_dt=incoming_created_dt,
                    tracked_created_dt=_last_command_created_dt,
                ),
            )
            return {
                "sent": False,
                "reason": "obsolete",
                "environment": _environment_dict(),
            }, 200
        logger.info(
            "twoway command accepted%s",
            format_kv(
                incoming_created_dt=incoming_created_dt,
                previous_created_dt=_last_command_created_dt,
            ),
        )
    try:
        if from_dmz_twoway:
            base = _last_applied_state.to_json()
            merged_for_state = {**base, **merged}
            logger.debug(
                "set_daikin merge twoway command into last state%s",
                format_kv(merged_incoming=merged),
            )
            state = State.from_json(merged_for_state)
        else:
            logger.debug(
                "set_daikin state preconvert%s", format_kv(merged=merged)
            )
            state = State.from_json(merged)
        logger.debug("set_daikin state%s", format_kv(state=state))
    except (KeyError, ValueError, TypeError) as e:
        logger.info("Invalid command: %s", e)
        return {"error": "InvalidCmd", "detail": str(e)}, 400

    ts = datetime.now()
    ts_iso = ts.isoformat()
    # Stamp UI-direct commands with receiver wall-clock when missing; trust the inbound
    # value otherwise (twoway path got past the gate above so it has a real created_dt).
    new_created_dt = (
        incoming_created_dt
        if isinstance(incoming_created_dt, str) and incoming_created_dt
        else ts_iso
    )
    fp = _daikin_state_fingerprint(state)
    if _last_daikin_ir_fingerprint is not None and fp == _last_daikin_ir_fingerprint:
        logger.info("SET_DAIKIN unchanged (no IR): %s", state.summary())
        _last_applied_state = state
        _last_command_created_dt = new_created_dt
        return _daikin_response_payload(ts_iso, state, sent=False, unchanged=True), 200
    success = send_daikin_state(state)
    if success:
        _last_daikin_ir_fingerprint = fp
    _last_applied_state = state
    _last_command_created_dt = new_created_dt
    daikin_cmds.append((ts, state, success))
    logger.info("SET_DAIKIN: %s", state.summary())
    return _daikin_response_payload(ts_iso, state, sent=success), 200


@app.route("/ui/context", methods=["GET"])
def ui_context():
    """JSON for the shared thermo UI: one zone, local environment, latest command."""
    deployment = _onboard_deployment_config()
    zn = deployment.zone_name
    env = _environment_dict()
    env_row: Dict[str, Any] = {
        "zone": zn,
        "temperature_centigrade": env.get("temperature_centigrade"),
        "humidity_percent": env.get("humidity_percent"),
        "time": env.get("time"),
    }
    cmd = _latest_command_dict_for_ui()
    return {
        "zones": [zn],
        "environments": [env_row],
        "zone_states": {zn: {"command": cmd, "sensors": None}},
        "deployment": deployment.to_public_dict(),
    }


@app.route("/ui/command", methods=["POST"])
def ui_command():
    """Apply a Daikin command for this onboard zone (``zone`` in body is ignored)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {"error": "json object required"}, 400
    cmd = body.get("command")
    if not isinstance(cmd, dict):
        return {"error": "command object required"}, 400
    inner: Dict[str, Any] = {"command": cmd}
    payload, status = handle_set_daikin_body(inner)
    if status >= 400:
        return payload, status
    if not isinstance(payload, dict):
        return {"error": "unexpected response"}, 500
    zn = _onboard_ui_zone_name()
    out_payload: Dict[str, Any] = {
        "zone": zn,
        "command": payload.get("command"),
        "sensors": None,
        "time": payload.get("time"),
        "sent": payload.get("sent"),
        "environment": payload.get("environment"),
        "unchanged": payload.get("unchanged"),
        "reason": payload.get("reason"),
    }
    return out_payload, status


@app.route("/daikin", methods=["PUT", "POST"])
def set_daikin():
    """Accept a zone state or bare command dict, convert to State, send IR if changed.

    Twoway posts the raw DMZ zone state ({command, sensors}). Partial DMZ commands are
    merged onto the last applied onboard State so the UI is not overwritten by stale
    narrow keys (e.g. only fan). Direct UI posts typically send {command} without sensors
    and replace behavior as before. Command keys are normalized via _command_dict_for_state.

    Successful responses include ``command`` (authoritative State JSON) and
    ``environment`` (same as GET /environment) so twoway can push command back to DMZ.

    Repeated identical commands do not re-send IR. Returns {time, command, environment, sent}.
    """
    js = request.json or {}
    return handle_set_daikin_body(js)


def main() -> None:
    """Run the onboard Flask app for this hardware target."""
    deployment = _onboard_deployment_config()
    port = int(os.environ.get("PORT", 5000))
    logger.info(
        "starting%s",
        format_kv(
            host="0.0.0.0",
            port=port,
            zone=deployment.zone_name,
            hardware_profile=deployment.hardware_profile,
            send_behavior=deployment.send_behavior,
            report_behavior=deployment.report_behavior,
        ),
    )
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
