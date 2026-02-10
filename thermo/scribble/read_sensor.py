#!/usr/bin/env python3
"""Read temperature and humidity from HTU21D (GY-21) sensor on I2C bus 1, addr 0x40."""

import smbus

ADDR      = 0x40
READ_TEMP = 0xE3
READ_HUM  = 0xE5
RESET     = 0xFE

bus = smbus.SMBus(1)

def read_temp():
    bus.write_byte(ADDR, RESET)
    msb, lsb, crc = bus.read_i2c_block_data(ADDR, READ_TEMP, 3)
    return -46.85 + 175.72 * (msb * 256 + lsb) / 65536.0

def read_humidity():
    bus.write_byte(ADDR, RESET)
    msb, lsb, crc = bus.read_i2c_block_data(ADDR, READ_HUM, 3)
    return -6.0 + 125.0 * (msb * 256 + lsb) / 65536.0

temp_c = read_temp()
temp_f = temp_c * 9.0 / 5.0 + 32.0
hum    = read_humidity()

print(f'Temperature: {temp_c:.1f} C  ({temp_f:.1f} F)')
print(f'Humidity:    {hum:.1f} %')
