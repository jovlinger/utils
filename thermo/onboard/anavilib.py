"""
This is my own shim library for anavi's sensor code.

This is the main export of the onboard project, and the flask app.pyy
is just a stub api for it.

This library will require system libraries like i2c to be installed,
and hopefully described in onboard/README.md
"""

import os
import subprocess
import sys
import tempfile

from common import is_test_env

LIRC_TX = "/dev/lirc0"


def send_daikin_state(state) -> bool:
    """Send Daikin IR state via ir-ctl. Return True if sent, False on error."""
    from heatpumpirctl import ARC452A9 as proto

    mode2 = proto.dumps(state)
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(mode2)
            path = f.name
        try:
            subprocess.run(["ir-ctl", "-d", LIRC_TX, "--send", path], check=True)
            return True
        finally:
            os.unlink(path)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as e:
        print("Daikin send error: %s" % e, file=sys.stderr)
        return False


def get_smbus():
    """Return SMBus(1) for I2C, or smbus_fake when ENV=TEST/DOCKERTEST."""
    if is_test_env():
        import smbus_fake

        return smbus_fake.SMBus(1)
    # where does this come from? presumably python-rpi.gpio. Also this is not I2C, but seems to work
    # actually, looks like python3-smbus according to web pages
    import smbus

    # Rev 2 of Raspberry Pi and all newer use bus 1
    return smbus.SMBus(1)


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
