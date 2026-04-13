"""
Duck-typed mocks for smbus (``thermo/onboard/test/conftest.py`` injects this as
``sys.modules["smbus"]`` so HTU21D tests run without real I2C).
"""


class SMBus:
    def __init__(self, busno):
        pass

    def write_byte(self, addr, cmd):
        pass

    def read_i2c_block_data(self, addr, cmd, val) -> tuple[int, int, int]:
        return 123, 34, 56
