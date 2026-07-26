"""Parse and resolve onboardctl zonespec selectors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

KIND_ZONE = "zone"
KIND_HARDWARE = "hardware"
KIND_DIALECT = "dialect"
KIND_TYPE = "type"
VALID_KINDS = frozenset({KIND_ZONE, KIND_HARDWARE, KIND_DIALECT, KIND_TYPE})

_SPEC_RE = re.compile(r"^(?:(?P<kind>[a-zA-Z_]+):)?(?P<value>.+)$")


@dataclass(frozen=True)
class ZoneSpec:
    kind: str
    value: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


@dataclass(frozen=True)
class BoardTarget:
    """One resolved onboard board from zone.env / deployment config."""

    zone_name: str
    backend: str
    hardware_profile: str
    ir_protocol: str
    send_behavior: str
    base_url: str
    env_path: Path
    raw: Mapping[str, str]

    @property
    def hardware_tokens(self) -> Tuple[str, ...]:
        """Tokens used for fuzzy hardware: matching."""
        tokens = {self.backend.lower(), self.hardware_profile.lower()}
        # pico2w, pizero2w, esp32s3, pi_zero, etc.
        for part in re.split(r"[_\-/]+", self.backend.lower()):
            if part:
                tokens.add(part)
        for part in re.split(r"[_\-/]+", self.hardware_profile.lower()):
            if part:
                tokens.add(part)
        if "esp32" in self.backend.lower() or "esp32" in self.hardware_profile.lower():
            tokens.add("esp32")
        if "pizero" in self.backend.lower() or "pi_zero" in self.hardware_profile.lower():
            tokens.add("pizero")
            tokens.add("pi")
        return tuple(sorted(tokens))

    @property
    def dialect_tokens(self) -> Tuple[str, ...]:
        tokens = {self.ir_protocol.lower(), self.send_behavior.lower()}
        for part in re.split(r"[_\-/]+", self.ir_protocol.lower()):
            if part:
                tokens.add(part)
        # midea24_coolix -> midea, coolix
        if "midea" in self.ir_protocol.lower():
            tokens.add("midea")
        if "daikin" in self.ir_protocol.lower() or "daikin" in self.send_behavior.lower():
            tokens.add("daikin")
        if "haier" in self.ir_protocol.lower():
            tokens.add("haier")
        return tuple(sorted(tokens))

    @property
    def type_tokens(self) -> Tuple[str, ...]:
        tokens = set()
        sb = self.send_behavior.lower()
        if "ir" in sb or "heatpump" in sb or "daikin" in sb:
            tokens.update({"ac", "heatpump", "heat"})
        if "led" in sb:
            tokens.add("led")
        if not tokens:
            tokens.add("ac")
        return tuple(sorted(tokens))


def parse_zonespec(raw: str) -> ZoneSpec:
    text = raw.strip()
    if not text:
        raise ValueError("zonespec is empty")
    match = _SPEC_RE.match(text)
    if match is None:
        raise ValueError(f"invalid zonespec {raw!r}")
    kind = (match.group("kind") or KIND_ZONE).lower()
    value = match.group("value").strip()
    if kind not in VALID_KINDS:
        raise ValueError(
            f"unknown zonespec kind {kind!r}; want one of {sorted(VALID_KINDS)}"
        )
    if not value:
        raise ValueError(f"zonespec {raw!r} has empty value")
    return ZoneSpec(kind=kind, value=value)


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse KEY=VALUE lines; expand $THERMO_ROOT relative to onboard parent."""
    text = path.read_text(encoding="utf-8")
    onboard_root = path.resolve().parents[2]  # zones/<zone>/zone.env -> onboard
    thermo_root = onboard_root.parent
    values: Dict[str, str] = {
        "THERMO_ROOT": str(thermo_root),
        "ONBOARD_ROOT": str(onboard_root),
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        val = val.replace("$THERMO_ROOT", str(thermo_root))
        val = val.replace("$ONBOARD_ROOT", str(onboard_root))
        values[key] = val
    return values


def _base_url_from_env(env: Mapping[str, str]) -> str:
    if env.get("ONBOARD_URL"):
        return env["ONBOARD_URL"].rstrip("/")
    port = env.get("ONBOARD_HTTP_PORT") or env.get("PORT") or "5000"
    if env.get("ONBOARD_DEPLOY_HOST"):
        return f"http://{env['ONBOARD_DEPLOY_HOST']}:{port}"
    if env.get("ESP32S3_JAGUAR_DEVICE_ADDRESS"):
        return f"http://{env['ESP32S3_JAGUAR_DEVICE_ADDRESS']}:{port}"
    if env.get("PICO2W_HOST"):
        return f"http://{env['PICO2W_HOST']}:{port}"
    return f"http://127.0.0.1:{port}"


def load_targets_from_zones_dir(zones_dir: Path) -> List[BoardTarget]:
    targets: List[BoardTarget] = []
    if not zones_dir.is_dir():
        return targets
    for zone_dir in sorted(zones_dir.iterdir()):
        env_path = zone_dir / "zone.env"
        if not env_path.is_file():
            continue
        env = parse_env_file(env_path)
        zone_name = env.get("ZONE_NAME") or zone_dir.name
        targets.append(
            BoardTarget(
                zone_name=zone_name,
                backend=env.get("ONBOARD_DEPLOY_BACKEND", ""),
                hardware_profile=env.get("ONBOARD_HARDWARE_PROFILE", ""),
                ir_protocol=env.get("ONBOARD_IR_PROTOCOL", ""),
                send_behavior=env.get("ONBOARD_SEND_BEHAVIOR", ""),
                base_url=_base_url_from_env(env),
                env_path=env_path,
                raw=env,
            )
        )
    return targets


def _hardware_matches(needle: str, target: BoardTarget) -> bool:
    n = needle.lower()
    tokens = target.hardware_tokens
    if n in tokens:
        return True
    # Prefix / substring fuzzy: esp32 matches esp32s3 backend
    return any(t.startswith(n) or n.startswith(t) for t in tokens if len(n) >= 3)


def resolve_zonespec(
    spec: ZoneSpec,
    targets: Sequence[BoardTarget],
) -> List[BoardTarget]:
    value = spec.value.lower()
    if spec.kind == KIND_ZONE:
        return [t for t in targets if t.zone_name.lower() == value]
    if spec.kind == KIND_HARDWARE:
        return [t for t in targets if _hardware_matches(value, t)]
    if spec.kind == KIND_DIALECT:
        return [
            t
            for t in targets
            if value in t.dialect_tokens
            or any(value in tok for tok in t.dialect_tokens)
        ]
    if spec.kind == KIND_TYPE:
        return [t for t in targets if value in t.type_tokens]
    return []


def default_zones_dir(onboard_root: Optional[Path] = None) -> Path:
    if onboard_root is None:
        onboard_root = Path(__file__).resolve().parents[1]
    return onboard_root / "zones"
