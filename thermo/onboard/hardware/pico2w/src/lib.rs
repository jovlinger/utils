#![cfg_attr(not(feature = "std"), no_std)]

pub mod aht20;
pub mod auth;
pub mod config;
pub mod debug;
pub mod health;
pub mod ir;
pub mod led;
pub mod protocol;
pub mod sensors;

#[cfg(feature = "firmware")]
pub use aht20::{Aht20, SoftI2c};

pub use auth::{SignedHeaders, ZoneAuth, ZoneAuthError};
pub use config::{
    wifi_password, wifi_ssid, zone_private_key_b64, DeviceConfig, PICO2W_AHT20_SCL_GPIO,
    PICO2W_AHT20_SDA_GPIO, PICO2W_IR_RX_GPIO, PICO2W_IR_TX_GPIO,
};
pub use debug::{
    hat_named_pins, parse_debug_line, write_err, write_gpio_read, write_gpio_set, write_help,
    write_ir_edge, write_ok, write_pins, DebugCommand, NamedPin,
};
pub use health::{PicoHealth, RollingLog};
pub use ir::{
    for_each_raw_ir_duration, is_raw_ir_command, midea_classic_frame, midea_classic_frames,
    parse_heatpump_command, HeatpumpCommand, HeatpumpFan, HeatpumpMode, MideaClassicFrames,
    MIDEA_GAP_US, MIDEA_PULSE_US, MIDEA_SPACE_ONE_US, MIDEA_SPACE_ZERO_US, MIDEA_START_PULSE_US,
    MIDEA_START_SPACE_US,
};
pub use led::{pattern_for_event, signal_status, BlinkPattern, LedColor, StatusEvent, StatusLed};
pub use protocol::{
    build_sensor_post_body, command_is_new, extract_command_created_dt, extract_command_json,
    parse_server_time_utc_epoch,
};
pub use sensors::{
    read_sensors_or_fallback, AccurateSensor, SensorReadFailure, SensorReading, SensorSource,
    FALLBACK_SENSOR_READING,
};
