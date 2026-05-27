#![cfg_attr(not(feature = "std"), no_std)]

pub mod auth;
pub mod config;
pub mod health;
pub mod led;
pub mod protocol;
pub mod sensors;

pub use auth::{SignedHeaders, ZoneAuth, ZoneAuthError};
pub use config::{wifi_password, wifi_ssid, zone_private_key_b64, DeviceConfig};
pub use health::{PicoHealth, RollingLog};
pub use led::{pattern_for_event, signal_status, BlinkPattern, LedColor, StatusEvent, StatusLed};
pub use protocol::{
    build_sensor_post_body, command_is_new, extract_command_created_dt, extract_command_json,
    parse_server_time_utc_epoch,
};
pub use sensors::{
    read_sensors_or_fallback, AccurateSensor, SensorReadFailure, SensorReading, SensorSource,
    FALLBACK_SENSOR_READING,
};
