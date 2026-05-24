"""
This is my own shim library for anavi's sensor code.

This is the main export of the onboard project, and the flask app.pyy
is just a stub api for it.

This library will require system libraries like i2c to be installed,
and hopefully described in onboard/README.md
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from typing import Any

from common import is_test_env
from common.logging_config import format_kv

logger = logging.getLogger(__name__)

LIRC_TX = (os.environ.get("IR_DEVICE") or "/dev/lirc0").strip()
IR_KIND = "heatpump_ir"
IR_DIALECT = "Daikin/ARC452A9"
IR_DEVICE = "lirc:%s" % LIRC_TX


def _state_summary(state: Any) -> str:
    fn = getattr(state, "summary", None)
    if callable(fn):
        try:
            return str(fn())
        except Exception:
            pass
    return repr(state)


def _payload_sha256(mode2: str) -> str:
    return hashlib.sha256(mode2.encode("utf-8")).hexdigest()


def send_daikin_state(state: Any) -> bool:
    """Send Daikin IR state via ir-ctl. Return True if sent, False on error."""
    if is_test_env():
        logger.debug(
            "send_skipped%s",
            format_kv(
                kind=IR_KIND,
                dialect=IR_DIALECT,
                device=IR_DEVICE,
                reason="test_env",
                state_summary=_state_summary(state),
            ),
        )
        return True

    from common.heatpumpirctl import ARC452A9 as proto

    logger.debug(
        "encode_start%s",
        format_kv(
            kind=IR_KIND,
            dialect=IR_DIALECT,
            device=IR_DEVICE,
            state_summary=_state_summary(state),
        ),
    )
    try:
        mode2 = proto.dumps(state)
    except Exception as e:
        logger.error(
            "encode_failed%s",
            format_kv(
                kind=IR_KIND,
                dialect=IR_DIALECT,
                device=IR_DEVICE,
                error=str(e),
            ),
        )
        return False

    digest = _payload_sha256(mode2)
    first_line = mode2.split("\n", 1)[0] if mode2 else ""
    line_count = mode2.count("\n") + (1 if mode2 else 0)
    logger.debug(
        "encoded%s",
        format_kv(
            kind=IR_KIND,
            dialect=IR_DIALECT,
            device=IR_DEVICE,
            mode2_bytes=len(mode2.encode("utf-8")),
            mode2_lines=line_count,
            sha256=digest,
            first_line_preview=first_line[:160],
        ),
    )

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(mode2)
            path = f.name
        try:
            logger.info(
                "ir_send%s",
                format_kv(
                    kind=IR_KIND,
                    dialect=IR_DIALECT,
                    device=IR_DEVICE,
                    payload_sha256_prefix=digest[:16],
                ),
            )
            argv = ["ir-ctl", "-d", LIRC_TX, "--send", path]
            logger.debug(
                "ir_ctl_invoke%s",
                format_kv(kind=IR_KIND, dialect=IR_DIALECT, argv=argv),
            )
            subprocess.run(argv, check=True)
            logger.debug(
                "ir_ctl_sent_ok%s",
                format_kv(kind=IR_KIND, dialect=IR_DIALECT, device=IR_DEVICE),
            )
            return True
        finally:
            os.unlink(path)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as e:
        logger.error(
            "ir_ctl_failed%s",
            format_kv(
                kind=IR_KIND,
                dialect=IR_DIALECT,
                device=IR_DEVICE,
                payload_sha256_prefix=digest[:16],
                error=str(e),
            ),
        )
        return False


def get_smbus():
    """Return SMBus(1) for I2C, or smbus_fake when ENV=TEST/DOCKERTEST."""
    if is_test_env():
        from hardware.pizero2w import smbus_fake

        return smbus_fake.SMBus(1)
    # smbus2: pip package, works in container (host may use python3-smbus instead)
    import smbus2

    return smbus2.SMBus(1)


### <<< start theft from anavi-examples.git/sensors/HTU21D/python/htu21d.py


def unit_float(msb: int, lsb: int) -> float:
    """Convert MSB/LSB pair to unit [0,1) for HTU21D raw readings."""
    return (msb * 256.0 + lsb) / 65536.0


class HTU21D(object):
    HTU21D_ADDR = 0x40
    CMD_READ_TEMP = 0xE3
    CMD_READ_HUM = 0xE5
    CMD_RESET = 0xFE

    instance = None

    @classmethod
    def singleton(cls) -> "HTU21D":
        """Return singleton HTU21D instance."""
        if x := cls.instance:
            return x
        x = cls()
        cls.instance = x
        return x

    def __init__(self):
        """Initialize I2C bus for HTU21D at 0x40."""
        self.bus = get_smbus()

    def reset(self) -> None:
        """Send soft reset to sensor."""
        self.bus.write_byte(self.HTU21D_ADDR, self.CMD_RESET)

    def temperature(self):
        """We model temperature sensor as linear output from -46.85C to 128.87 in 65536 steps"""
        self.reset()
        msb, lsb, crc = self.bus.read_i2c_block_data(
            self.HTU21D_ADDR, self.CMD_READ_TEMP, 3
        )
        val = -46.85 + 175.72 * unit_float(msb, lsb)
        return {"centigrade": val}

    def temperature_centigrade(self) -> float:
        """Return temperature in °C. Intentionally brittle on unit change."""
        return self.temperature()["centigrade"]

    def humidity(self):
        """We model humidity sensor as having linear output from -6% to 119% in 65536 steps"""
        self.reset()
        msb, lsb, crc = self.bus.read_i2c_block_data(
            self.HTU21D_ADDR, self.CMD_READ_HUM, 3
        )
        val = -6 + 125 * unit_float(msb, lsb)
        return {"percent": val}

    def humidity_percent(self) -> float:
        """Return relative humidity in percent."""
        return self.humidity()["percent"]


### end theft from anavi-examples.git/sensors/HTU21D/python/htu21d.py >>>


class AnaviIRPhat:
    pass


"""
class I2C:
    def __init__(self): # or whatever that one is called.
        self.sensors = []
        self.sensors.append(HTU21D)


    def get_environment(self):
        return {"temp": 123}
"""
