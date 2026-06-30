use core::fmt::Write;

use heapless::String;

use crate::{
    build_sensor_post_body, command_is_new, extract_command_created_dt, extract_command_json,
    for_each_raw_ir_duration, is_raw_ir_command, parse_heatpump_command, DeviceConfig,
    HardwareError, SensorReading, SensorSource, StatusEvent, ThermoHardware,
    FALLBACK_SENSOR_READING,
};

const RAW_IR_CARRIER_HZ: u32 = 38_000;
const RAW_IR_MAX_SEQUENCE_LEN: usize = 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppCoreState {
    pub last_applied_created_dt: String<64>,
    pub last_applied_command_json: String<1024>,
    pub has_last_applied_command: bool,
    pub poll_successes: u64,
    pub poll_errors: u64,
    pub ir_sends: u64,
    pub ir_stub_sends: u64,
}

impl AppCoreState {
    pub const fn new() -> Self {
        Self {
            last_applied_created_dt: String::new(),
            last_applied_command_json: String::new(),
            has_last_applied_command: false,
            poll_successes: 0,
            poll_errors: 0,
            ir_sends: 0,
            ir_stub_sends: 0,
        }
    }

    pub fn last_applied_command_json(&self) -> Option<&str> {
        if self.has_last_applied_command {
            Some(self.last_applied_command_json.as_str())
        } else {
            None
        }
    }
}

impl Default for AppCoreState {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PollContext<'a> {
    pub epoch_seconds: Option<u64>,
    pub local_ip: Option<&'a str>,
    pub log_lines: &'a [&'a str],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorPostRequest<const N: usize> {
    pub method: &'static str,
    pub path: String<128>,
    pub body: String<N>,
    pub zone_name: &'static str,
    pub epoch_seconds: u64,
    pub timeout_secs: u64,
}

pub trait DmzClient {
    type Error;

    fn post_sensors<'a, const N: usize>(
        &'a mut self,
        request: &SensorPostRequest<N>,
    ) -> Result<&'a str, Self::Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DmzClientError {
    Network,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PollOutcome {
    Posted,
    TimeNotReady,
    SensorRequired,
    NetworkError,
    HardwareError,
    InvalidCommand,
    BufferTooSmall,
}

pub fn poll_once<const BODY_N: usize, D, H>(
    config: &DeviceConfig,
    state: &mut AppCoreState,
    dmz: &mut D,
    hardware: &mut H,
    context: PollContext<'_>,
) -> PollOutcome
where
    D: DmzClient,
    H: ThermoHardware,
{
    let Some(epoch_seconds) = context.epoch_seconds else {
        return PollOutcome::TimeNotReady;
    };

    if hardware.set_status(StatusEvent::PollStarted).is_err() {
        return PollOutcome::HardwareError;
    }

    let reading = match read_sensor(config, hardware) {
        Ok(reading) => reading,
        Err(PollOutcome::SensorRequired) => return PollOutcome::SensorRequired,
        Err(_) => return PollOutcome::HardwareError,
    };
    let body = match build_sensor_post_body::<BODY_N>(
        config,
        reading,
        state.last_applied_command_json(),
        context.log_lines,
        context.local_ip,
    ) {
        Ok(body) => body,
        Err(_) => return PollOutcome::BufferTooSmall,
    };
    let path = match zone_path(config) {
        Ok(path) => path,
        Err(_) => return PollOutcome::BufferTooSmall,
    };
    let request = SensorPostRequest {
        method: "POST",
        path,
        body,
        zone_name: config.zone_name,
        epoch_seconds,
        timeout_secs: config.post_timeout_secs,
    };

    let response = match dmz.post_sensors(&request) {
        Ok(response) => response,
        Err(_) => {
            state.poll_errors = state.poll_errors.saturating_add(1);
            let _ = hardware.set_status(StatusEvent::Error);
            return PollOutcome::NetworkError;
        }
    };

    if let Some(response_created_dt) = extract_command_created_dt(response) {
        if command_is_new(
            state.last_applied_created_dt.as_str(),
            Some(response_created_dt),
        ) {
            let Some(command_json) = extract_command_json(response) else {
                return PollOutcome::InvalidCommand;
            };
            match send_command(hardware, command_json) {
                Ok(()) => {
                    if remember_applied_command(state, response_created_dt, command_json).is_err() {
                        return PollOutcome::BufferTooSmall;
                    }
                }
                Err(PollOutcome::InvalidCommand) => return PollOutcome::InvalidCommand,
                Err(_) => return PollOutcome::HardwareError,
            }
        }
    }

    state.poll_successes = state.poll_successes.saturating_add(1);
    let _ = hardware.set_status(StatusEvent::PollSucceeded);
    PollOutcome::Posted
}

fn read_sensor<H>(config: &DeviceConfig, hardware: &mut H) -> Result<SensorReading, PollOutcome>
where
    H: ThermoHardware,
{
    match hardware.read_aht20() {
        Ok(mut reading) => {
            reading.source = SensorSource::Aht20;
            Ok(reading)
        }
        Err(_) if config.sensor_required_at_boot => Err(PollOutcome::SensorRequired),
        Err(_) => Ok(FALLBACK_SENSOR_READING),
    }
}

fn zone_path(config: &DeviceConfig) -> Result<String<128>, core::fmt::Error> {
    let (prefix, zone_name, suffix) = config.zone_path().as_parts();
    let mut path: String<128> = String::new();
    write!(path, "{}{}{}", prefix, zone_name, suffix)?;
    Ok(path)
}

fn send_command<H>(hardware: &mut H, command_json: &str) -> Result<(), PollOutcome>
where
    H: ThermoHardware,
{
    if is_raw_ir_command(command_json) {
        let mut durations_us = [0_i32; RAW_IR_MAX_SEQUENCE_LEN];
        let mut index: usize = 0;
        let count = for_each_raw_ir_duration(command_json, |duration| {
            if index < durations_us.len() {
                durations_us[index] = duration;
                index += 1;
            }
        })
        .ok_or(PollOutcome::InvalidCommand)?;
        return hardware
            .send_raw_ir(RAW_IR_CARRIER_HZ, &durations_us[..count])
            .map_err(map_hardware_error);
    }

    let command = parse_heatpump_command(command_json).ok_or(PollOutcome::InvalidCommand)?;
    hardware.send_midea_ir(&command).map_err(map_hardware_error)
}

fn remember_applied_command(
    state: &mut AppCoreState,
    created_dt: &str,
    command_json: &str,
) -> Result<(), core::fmt::Error> {
    state.last_applied_created_dt.clear();
    state.last_applied_command_json.clear();
    state
        .last_applied_created_dt
        .push_str(created_dt)
        .map_err(|_| core::fmt::Error)?;
    state
        .last_applied_command_json
        .push_str(command_json)
        .map_err(|_| core::fmt::Error)?;
    state.has_last_applied_command = true;
    state.ir_sends = state.ir_sends.saturating_add(1);
    Ok(())
}

fn map_hardware_error(_error: HardwareError) -> PollOutcome {
    PollOutcome::HardwareError
}

#[cfg(test)]
mod tests {
    use super::{poll_once, AppCoreState, DmzClient, PollContext, PollOutcome, SensorPostRequest};
    use crate::{
        DeviceConfig, HardwareError, HeatpumpCommand, IrEdge, SensorReading, SensorSource,
        StatusEvent, ThermoHardware,
    };

    struct FakeDmz {
        response: &'static str,
        posts: usize,
    }

    impl DmzClient for FakeDmz {
        type Error = ();

        fn post_sensors<'a, const N: usize>(
            &'a mut self,
            request: &SensorPostRequest<N>,
        ) -> Result<&'a str, Self::Error> {
            assert_eq!(request.method, "POST");
            assert_eq!(request.path.as_str(), "/zone/kitchen/sensors");
            assert!(request.body.contains("\"backend\":\"esp32s3\""));
            self.posts += 1;
            Ok(self.response)
        }
    }

    struct FakeHardware {
        ir_sends: usize,
    }

    impl ThermoHardware for FakeHardware {
        fn read_aht20(&mut self) -> Result<SensorReading, HardwareError> {
            Ok(SensorReading {
                temp_centigrade: 23.7,
                humid_percent: 51.2,
                source: SensorSource::Fallback,
            })
        }

        fn send_midea_ir(&mut self, _command: &HeatpumpCommand) -> Result<(), HardwareError> {
            self.ir_sends += 1;
            Ok(())
        }

        fn send_raw_ir(
            &mut self,
            _carrier_hz: u32,
            _durations_us: &[i32],
        ) -> Result<(), HardwareError> {
            self.ir_sends += 1;
            Ok(())
        }

        fn record_ir_rx_edge(&mut self) -> Result<Option<IrEdge>, HardwareError> {
            Ok(None)
        }

        fn set_status(&mut self, _event: StatusEvent) -> Result<(), HardwareError> {
            Ok(())
        }

        fn monotonic_millis(&self) -> u64 {
            0
        }
    }

    #[test]
    fn poll_once_posts_with_valid_time() {
        let config = DeviceConfig::kitchen_esp32s3();
        let mut state = AppCoreState::new();
        let mut dmz = FakeDmz {
            response: "{\"command\":null}",
            posts: 0,
        };
        let mut hardware = FakeHardware { ir_sends: 0 };

        let outcome = poll_once::<2048, _, _>(
            &config,
            &mut state,
            &mut dmz,
            &mut hardware,
            PollContext {
                epoch_seconds: Some(1_779_855_900),
                local_ip: None,
                log_lines: &[],
            },
        );

        assert_eq!(outcome, PollOutcome::Posted);
        assert_eq!(dmz.posts, 1);
        assert_eq!(hardware.ir_sends, 0);
    }
}
