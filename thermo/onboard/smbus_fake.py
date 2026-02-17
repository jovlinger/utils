"""
Duck-typed mocks for smbus.

use like so:


<brief tutorial in mocking. Do we want to switch to pytest instead of unittest?

Nah. we'll use the get-in-there-first low-level import
"""


class SMBus:
    def __init__(self, busno):
        pass

    def write_byte(self, addr, cmd):
        pass

    def read_i2c_block_data(self, addr, cmd, val) -> tuple[int, int, int]:
        return 123, 34, 56
