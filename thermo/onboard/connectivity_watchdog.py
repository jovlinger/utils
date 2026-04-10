"""
Periodic DMZ + onboard HTTP reachability checks. On sustained failure, append a
network snapshot to disk (durable across container restart; use a persistent
host path for CONNECTIVITY_DUMP_DIR if logs are tmpfs and you need data after
hard reboot).

Incident bundles include optional **hardware health**: Linux thermal zones,
load, memory; on Raspberry Pi, ``vcgencmd`` temp/throttle flags if the binary
is available (bind-mount ``/usr/bin/vcgencmd`` from the host in compose if
needed).
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import log  # noqa: E402


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def check_http_reachable(url: str, timeout: float) -> Tuple[bool, str]:
    """Return (ok, detail). Any completed HTTP response counts as reachable."""
    try:
        r = requests.get(url, timeout=timeout)
        return True, f"status={r.status_code}"
    except requests.RequestException as e:
        return False, str(e)


def run_cmd(
    args: List[str], timeout: float = 8.0
) -> str:
    """Run a command; return stdout+stderr for the snapshot bundle."""
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return (
            f"$ {' '.join(args)}\n"
            f"exit={p.returncode}\n"
            f"{out}\n"
        )
    except Exception as e:  # noqa: BLE001 — snapshot must not raise
        return f"$ {' '.join(args)}\nfailed: {e!s}\n"


def tail_file(path: str, max_lines: int = 60, max_bytes: int = 65536) -> str:
    """Best-effort last lines of a log file (shared volume)."""
    p = Path(path)
    if not p.is_file():
        return f"(file missing: {path})\n"
    try:
        with p.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            chunk = f.read().decode("utf-8", errors="replace")
        lines = chunk.splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail) + "\n"
    except OSError as e:
        return f"(read error {path}: {e})\n"


# Raspberry Pi ``vcgencmd get_throttled`` bitmask (see Raspberry Pi firmware docs).
_PI_THROTTLE_BITS: Dict[int, str] = {
    0: "under_voltage_now",
    1: "arm_freq_capped_now",
    2: "throttled_now",
    3: "soft_temp_limit_now",
    16: "under_voltage_occurred",
    17: "arm_freq_capped_occurred",
    18: "throttled_occurred",
    19: "soft_temp_limit_occurred",
}


def decode_pi_throttled(flags: int) -> str:
    """Human-readable list of set throttle / power flags, or ``none``."""
    names = [n for b, n in _PI_THROTTLE_BITS.items() if flags & (1 << b)]
    return ", ".join(names) if names else "none"


def parse_throttled_line(text: str) -> Optional[int]:
    """Parse ``throttled=0x....`` from vcgencmd stdout."""
    m = re.search(r"throttled\s*=\s*(0x[0-9a-fA-F]+)", text)
    if m:
        return int(m.group(1), 16)
    return None


def parse_measure_temp_line(text: str) -> Optional[float]:
    """Parse ``temp=42.3'C`` from vcgencmd stdout."""
    m = re.search(r"temp=([\d.]+)", text)
    if m:
        return float(m.group(1))
    return None


def _vcgencmd_paths() -> List[str]:
    extra = os.environ.get("VCGENCMD_PATH", "").strip()
    paths = [extra] if extra else []
    paths.extend(["/usr/bin/vcgencmd", "/opt/vc/bin/vcgencmd"])
    return paths


def _vcgencmd_run(args: List[str]) -> Optional[str]:
    for cand in _vcgencmd_paths():
        if not cand:
            continue
        p = Path(cand)
        if not p.is_file() or not os.access(p, os.X_OK):
            continue
        try:
            r = subprocess.run(
                [str(p)] + args,
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            out = (r.stdout or "") + (r.stderr or "")
            return out if out.strip() else None
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def collect_thermal_sysfs() -> str:
    """Read ``/sys/class/thermal/thermal_zone*`` (millidegree Celsius)."""
    lines: List[str] = []
    base = Path("/sys/class/thermal")
    if not base.is_dir():
        return "(no /sys/class/thermal)\n"
    for z in sorted(base.glob("thermal_zone*")):
        if not z.is_dir():
            continue
        try:
            t_raw = (z / "temp").read_text().strip()
            typ = (
                (z / "type").read_text().strip()
                if (z / "type").is_file()
                else "?"
            )
            mc = int(t_raw)
            lines.append(
                f"{z.name} type={typ} temp_millic={t_raw} ({mc / 1000.0:.3f} °C)\n"
            )
        except (OSError, ValueError) as e:
            lines.append(f"{z.name}: {e}\n")
    return "".join(lines) if lines else "(no thermal zones)\n"


def collect_hw_health_snapshot() -> str:
    """Thermal, load, memory, optional Pi vcgencmd (best-effort)."""
    blocks: List[str] = []
    blocks.append("--- thermal (sysfs) ---\n")
    blocks.append(collect_thermal_sysfs())
    blocks.append("--- load / mem ---\n")
    try:
        blocks.append(Path("/proc/loadavg").read_text())
    except OSError as e:
        blocks.append(f"(loadavg: {e})\n")
    try:
        with Path("/proc/meminfo").open() as f:
            blocks.append("".join(f.readlines()[:12]))
    except OSError as e:
        blocks.append(f"(meminfo: {e})\n")
    blocks.append("--- vcgencmd (Pi; optional) ---\n")
    mt = _vcgencmd_run(["measure_temp"])
    if mt:
        blocks.append(mt if mt.endswith("\n") else mt + "\n")
        parsed = parse_measure_temp_line(mt)
        if parsed is not None:
            blocks.append(f"(parsed temp_c={parsed})\n")
    else:
        blocks.append(
            "(vcgencmd not available — on Pi bind-mount host "
            "/usr/bin/vcgencmd and often /dev/vchiq)\n"
        )
    gt = _vcgencmd_run(["get_throttled"])
    if gt:
        blocks.append(gt if gt.endswith("\n") else gt + "\n")
        parsed = parse_throttled_line(gt)
        if parsed is not None:
            blocks.append(
                f"(parsed flags=0x{parsed:x} {decode_pi_throttled(parsed)})\n"
            )
    blocks.append("--- cpufreq (if present) ---\n")
    cpu0 = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    if cpu0.is_file():
        try:
            blocks.append(f"cpu0 scaling_cur_freq: {cpu0.read_text().strip()} kHz\n")
        except OSError as e:
            blocks.append(f"(cpufreq: {e})\n")
    else:
        blocks.append("(no cpufreq sysfs)\n")
    return "".join(blocks)


def hw_health_metrics_compact() -> Dict[str, object]:
    """Structured fields for periodic INFO logs (no secrets)."""
    out: Dict[str, object] = {}
    temps: List[float] = []
    base = Path("/sys/class/thermal")
    if base.is_dir():
        for z in base.glob("thermal_zone*"):
            if not z.is_dir() or not (z / "temp").is_file():
                continue
            try:
                mc = int((z / "temp").read_text().strip())
                typ = (
                    (z / "type").read_text().strip()
                    if (z / "type").is_file()
                    else z.name
                )
                c = mc / 1000.0
                temps.append(c)
                out[f"thermal_{typ}"] = round(c, 2)
            except (OSError, ValueError):
                continue
    if temps:
        out["thermal_max_c"] = round(max(temps), 2)
    try:
        la = Path("/proc/loadavg").read_text().strip().split()
        if la:
            out["load1"] = la[0]
    except OSError:
        pass
    mt = _vcgencmd_run(["measure_temp"])
    if mt:
        t = parse_measure_temp_line(mt)
        if t is not None:
            out["vcgencmd_temp_c"] = round(t, 2)
    gt = _vcgencmd_run(["get_throttled"])
    if gt:
        v = parse_throttled_line(gt)
        if v is not None:
            out["throttled_hex"] = f"0x{v:x}"
            out["throttled"] = decode_pi_throttled(v)
    return out


def _default_wlan_iface() -> Optional[str]:
    """Guess wlan interface from `ip -br link` (first wlan*)."""
    try:
        p = subprocess.run(
            ["ip", "-br", "link"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        for line in (p.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("wlan"):
                return parts[0].rstrip(":")
        return None
    except Exception:
        return None


def collect_network_snapshot(
    twoway_log_path: str,
    dmz_url: str,
    onboard_url: str,
) -> str:
    """Shell + file fragments for post-mortem (no secrets)."""
    blocks: List[str] = []
    blocks.append(f"timestamp_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    blocks.append(run_cmd(["uname", "-a"]))
    blocks.append(run_cmd(["cat", "/proc/uptime"]))
    blocks.append("--- hw health (thermal / load / Pi throttle) ---\n")
    blocks.append(collect_hw_health_snapshot())
    blocks.append("--- network ---\n")
    blocks.append(run_cmd(["ip", "-br", "link"]))
    blocks.append(run_cmd(["ip", "-br", "addr"]))
    blocks.append(run_cmd(["ip", "route", "show"]))
    blocks.append(run_cmd(["ip", "-6", "route", "show"]))
    blocks.append(run_cmd(["ip", "neigh", "show"]))
    parsed = urlparse(dmz_url)
    host = parsed.hostname
    if host:
        blocks.append(run_cmd(["getent", "ahosts", host]))
    wlan = os.environ.get("WATCHDOG_WLAN_IFACE") or _default_wlan_iface()
    if wlan:
        blocks.append(run_cmd(["iw", "dev", wlan, "link"]))
    blocks.append(run_cmd(["cat", "/proc/net/wireless"]))
    blocks.append(
        run_cmd(
            ["sh", "-c", "dmesg -T 2>&1 | tail -n 120"],
            timeout=4.0,
        )
    )
    blocks.append("--- tail twoway.log ---\n")
    blocks.append(tail_file(twoway_log_path))
    blocks.append("--- tail connectivity-watchdog.log ---\n")
    log_path = os.environ.get("CONNECTIVITY_LOG_PATH", "")
    if log_path:
        blocks.append(tail_file(log_path, max_lines=40))
    blocks.append(f"dmz_url={dmz_url!r} onboard_url={onboard_url!r}\n")
    out = "".join(blocks)
    max_chars = _env_int("CONNECTIVITY_SNAPSHOT_MAX_CHARS", 120000)
    if len(out) > max_chars:
        return out[:max_chars] + "\n... [snapshot truncated]\n"
    return out


def _incident_path(dump_dir: Path) -> Path:
    dump_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())
    return dump_dir / f"incident-{stamp}.txt"


def trim_old_incidents(dump_dir: Path, keep: int) -> None:
    """Keep only the newest `keep` incident-*.txt files."""
    pattern = str(dump_dir / "incident-*.txt")
    paths = sorted(glob.glob(pattern), reverse=True)
    for old in paths[keep:]:
        try:
            os.remove(old)
        except OSError:
            pass


def write_incident_bundle(text: str, dump_dir: Path, keep: int) -> Path:
    """Atomic-ish write + fsync for durability."""
    path = _incident_path(dump_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    trim_old_incidents(dump_dir, keep)
    return path


def detail_summary(ok: bool, detail: str) -> str:
    return f"ok={ok} {detail}"


def main() -> None:
    dmz_url = os.environ.get("DMZ_URL", "http://127.0.0.1:5000").rstrip("/") + "/"
    onboard_url = os.environ.get("ONBOARD_URL", "http://127.0.0.1:5000").rstrip("/") + "/"
    log_dir = os.environ.get("LOG_DIR", "/var/log/thermo-onboard")
    twoway_log = os.environ.get("TWOWAY_LOG_PATH", os.path.join(log_dir, "twoway.log"))
    dump_dir = Path(
        os.environ.get("CONNECTIVITY_DUMP_DIR", os.path.join(log_dir, "incidents"))
    )
    interval = _env_float("CONNECTIVITY_CHECK_INTERVAL_SECS", 30.0)
    threshold = _env_int("CONNECTIVITY_FAIL_THRESHOLD", 3)
    http_timeout = _env_float("CONNECTIVITY_HTTP_TIMEOUT_SECS", 5.0)
    keep_incidents = _env_int("CONNECTIVITY_INCIDENT_KEEP", 15)
    run_id = os.environ.get("CONNECTIVITY_RUN_ID", "watchdog-1")

    log("watchdog", "start", run_id=run_id, interval=interval, threshold=threshold)
    consecutive = 0
    in_episode = False
    episode_dumped = False
    hw_interval = _env_float("HW_HEALTH_LOG_INTERVAL_SECS", 0.0)
    last_hw_log = time.monotonic()

    while True:
        dmz_ok, dmz_detail = check_http_reachable(dmz_url, http_timeout)
        ob_ok, ob_detail = check_http_reachable(onboard_url, http_timeout)
        ok = dmz_ok and ob_ok

        if ok:
            if in_episode:
                log(
                    "watchdog",
                    "recovered",
                    run_id=run_id,
                    dmz=detail_summary(dmz_ok, dmz_detail),
                    onboard=detail_summary(ob_ok, ob_detail),
                )
            consecutive = 0
            in_episode = False
            episode_dumped = False
        else:
            consecutive += 1
            log(
                "watchdog",
                "check_fail",
                run_id=run_id,
                consecutive=consecutive,
                dmz=detail_summary(dmz_ok, dmz_detail),
                onboard=detail_summary(ob_ok, ob_detail),
            )
            in_episode = True
            if consecutive >= threshold and not episode_dumped:
                snap = collect_network_snapshot(twoway_log, dmz_url, onboard_url)
                meta = {
                    "run_id": run_id,
                    "consecutive_failures": consecutive,
                    "dmz_ok": dmz_ok,
                    "dmz_detail": dmz_detail,
                    "onboard_ok": ob_ok,
                    "onboard_detail": ob_detail,
                }
                header = json.dumps(meta, indent=2) + "\n\n--- snapshot ---\n"
                try:
                    path = write_incident_bundle(header + snap, dump_dir, keep_incidents)
                    log("watchdog", "incident_written", run_id=run_id, path=str(path))
                except OSError as e:
                    log("watchdog", "incident_write_failed", run_id=run_id, error=str(e))
                episode_dumped = True

        if hw_interval > 0:
            now_m = time.monotonic()
            if now_m - last_hw_log >= hw_interval:
                last_hw_log = now_m
                try:
                    m = hw_health_metrics_compact()
                    if m:
                        log("watchdog", "hw_health", run_id=run_id, **m)
                    else:
                        log("watchdog", "hw_health", run_id=run_id, note="empty")
                except Exception as e:  # noqa: BLE001 — never kill watchdog
                    log("watchdog", "hw_health_failed", run_id=run_id, error=str(e))

        time.sleep(interval)


if __name__ == "__main__":
    main()
