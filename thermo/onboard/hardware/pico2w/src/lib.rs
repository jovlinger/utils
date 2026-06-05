#![cfg_attr(not(feature = "std"), no_std)]

pub mod auth;
pub mod config;
pub mod health;
pub mod ir;
pub mod led;
pub mod protocol;
pub mod sensors;

pub use auth::{SignedHeaders, ZoneAuth, ZoneAuthError};
pub use config::{wifi_password, wifi_ssid, zone_private_key_b64, DeviceConfig};
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
