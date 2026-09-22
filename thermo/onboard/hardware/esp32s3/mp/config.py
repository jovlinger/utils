"""Office ESP32-S3 onboard constants (TSL / zone.env aligned).

Pure data -- importable on CPython host tests and MicroPython on-device.
"""

from __future__ import annotations

ZONE_NAME: str = "office"
BACKEND: str = "esp32s3"
HARDWARE_PROFILE: str = "esp32s3_aht20_ir"
IR_PROTOCOL: str = "midea24_coolix"
IR_TX_GPIO: int = 17
IR_RX_GPIO: int = 6
DEBUG_PULLUP_GPIO: int = 4
DEBUG_PULLDOWN_GPIO: int = 5
AHT20_SDA_GPIO: int = 8
AHT20_SCL_GPIO: int = 9
AHT20_ADDR: int = 0x38
HTTP_PORT: int = 5000
LOG_CAPACITY: int = 32
# Believable wall clock for Ed25519 zone timestamps (DMZ rejects skew).
MIN_CREDIBLE_EPOCH: int = 1_700_000_000
NTP_ATTEMPTS: int = 5

# Default office LAN identity (overridden at runtime when WiFi gives DHCP).
DEFAULT_LOCAL_IP: str = "192.168.88.73"

SEND_BEHAVIOR: str = "ir_heatpump"
REPORT_BEHAVIOR: str = "sensor_readings"
SENSOR_DRIVER: str = "aht20"
IR_TRANSPORT: str = "esp32s3_rmt"
STATUS_LED_DRIVER: str = "log_only"
