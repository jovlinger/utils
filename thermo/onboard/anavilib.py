"""
This is my own shim library for anavi's sensor code.

This is the main export of the onboard project, and the flask app.pyy
is just a stub api for it.

This library will require system libraries like i2c to be installed,
and hopefully described in onboard/README.md
"""

# where does this come from? presumably python-rpi.gpio. Also this is not I2C, but seems to work
# actually, looks like python3-smbus according to web pages
import smbus  

### <<< start theft from anavi-examples.git/sensors/HTU21D/python/htu21d.py

def unit_float(msb, lsb) -> float:
    return (msb * 256.0 + lsb) / 65536.0

class HTU21D(object):
    HTU21D_ADDR = 0x40
    CMD_READ_TEMP = 0xE3
    CMD_READ_HUM = 0xE5
    CMD_RESET = 0xFE

    instance = None

    @classmethod
    def singleton(cls) -> "HTU21D":
        if x := cls.instance:
            return x
        x = cls()
        cls.instance = x
        return x

    def __init__(self):
       # Rev 2 of Raspberry Pi and all newer use bus 1
       self.bus = smbus.SMBus(1)
       
    def reset(self):
        self.bus.write_byte(self.HTU21D_ADDR, self.CMD_RESET)
           
    def temperature(self):
        """We model temperature sensor as linear output from -46.85C to 128.87 in 65536 steps"""
        self.reset()
        msb, lsb, crc = self.bus.read_i2c_block_data(self.HTU21D_ADDR, self.CMD_READ_TEMP, 3)
        val = -46.85 + 175.72 * unit_float(msb, lsb)
        return {"centigrade": val}

    def humidity(self):
        """We model humidity sensor as having linear output from -6% to 119% in 65536 steps"""
        self.reset()
        msb, lsb, crc = self.bus.read_i2c_block_data(self.HTU21D_ADDR, self.CMD_READ_HUM, 3)
        val = -6 + 125 * unit_float(msb, lsb)
        return {"percent": val}

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
