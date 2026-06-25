#![cfg_attr(not(feature = "std"), no_std)]

pub mod aht20;
pub mod app_core;
pub mod auth;
pub mod config;
#[path = "../../pico2w/src/debug.rs"]
pub mod debug;
pub mod hardware;
pub mod health;
pub mod ir;
pub mod led;
pub mod protocol;
pub mod sensors;

#[cfg(test)]
mod esp32s3_contract_tests;

pub use aht20::{decode_measurement, Aht20Error, AHT20_DEFAULT_ADDR};
pub use app_core::{
    poll_once, AppCoreState, DmzClient, DmzClientError, PollContext, PollOutcome, SensorPostRequest,
};
pub use auth::{SignedHeaders, ZoneAuth, ZoneAuthError};
pub use config::{wifi_password, wifi_ssid, zone_private_key_b64, DeviceConfig};
pub use debug::{
    hat_named_pins, parse_debug_line, write_err, write_gpio_read, write_gpio_set, write_help,
    write_ir_edge, write_ok, write_pins, DebugCommand, NamedPin,
};
pub use hardware::{Esp32s3Pins, HardwareError, IrEdge, ThermoHardware};
pub use health::{build_healthz_body, Esp32s3RuntimeStatus, HealthQueues, LogStorage, RollingLog};
pub use ir::{
    for_each_raw_ir_duration, is_raw_ir_command, midea_classic_frame, midea_classic_frames,
    parse_heatpump_command, HeatpumpCommand, HeatpumpFan, HeatpumpMode, MideaClassicFrames,
    MIDEA_GAP_US, MIDEA_PULSE_US, MIDEA_SPACE_ONE_US, MIDEA_SPACE_ZERO_US, MIDEA_START_PULSE_US,
    MIDEA_START_SPACE_US,
};
pub use led::{pattern_for_event, signal_status, BlinkPattern, LedColor, StatusEvent, StatusLed};
pub use protocol::{
    build_logs_body, build_sensor_post_body, command_is_new, extract_command_created_dt,
    extract_command_json, parse_server_time_utc_epoch,
};
pub use sensors::{
    read_sensors_or_fallback, AccurateSensor, SensorReadFailure, SensorReading, SensorSource,
    FALLBACK_SENSOR_READING,
};
