use std::collections::VecDeque;
use std::string::String as StdString;
use std::vec::Vec;

use crate::{
    build_healthz_body, build_sensor_post_body, poll_once, AppCoreState, DeviceConfig, DmzClient,
    Esp32s3RuntimeStatus, HardwareError, HealthQueues, HeatpumpCommand, IrEdge, PollContext,
    PollOutcome, RollingLog, SensorPostRequest, SensorReading, SensorSource, StatusEvent,
    ThermoHardware,
};

const VALID_EPOCH_SECONDS: u64 = 1_779_855_900;

#[test]
fn defaults_match_esp32s3_plan() {
    let config = DeviceConfig::kitchen_esp32s3();

    assert_eq!(config.hardware_profile, "esp32s3_aht20_ir");
    assert_eq!(config.deploy_backend, "esp32s3");
    assert_eq!(config.dmz_port, 5000);
    assert_eq!(config.onboard_port, 5000);
    assert_eq!(config.post_timeout_secs, 600);
    assert_eq!(config.sensor_driver, "aht20");
    assert!(!config.sensor_required_at_boot);
    assert_eq!(config.ir_transport, "esp32s3_rmt");
    assert_eq!(config.ir_device, "gpio17");
    assert_eq!(config.ir_protocol, "midea24_coolix");
    assert_eq!(config.ir_tx_gpio, 17);
    assert_eq!(config.ir_rx_gpio, 6);
    assert_eq!(config.i2c_scl_gpio, 36);
    assert_eq!(config.i2c_sda_gpio, 35);
    assert_eq!(config.aht20_addr, 0x38);
    assert_eq!(config.status_led_driver, "log_only");
    assert_eq!(config.app_core, 1);
}

#[test]
fn cold_start_sensor_post_has_esp32s3_metadata_and_no_command() {
    let config = DeviceConfig::kitchen_esp32s3();
    let reading = SensorReading {
        temp_centigrade: 23.7,
        humid_percent: 51.2,
        source: SensorSource::Aht20,
    };

    let body = build_sensor_post_body::<1024>(&config, reading, None, &[], Some("192.168.1.55"))
        .expect("sensor post body should fit");

    assert!(body.contains("\"temp_centigrade\":23.7"));
    assert!(body.contains("\"humid_percent\":51.2"));
    assert!(body.contains("\"hardware_profile\":\"esp32s3_aht20_ir\""));
    assert!(body.contains("\"backend\":\"esp32s3\""));
    assert!(body.contains("\"zone_name\":\"kitchen\""));
    assert!(body.contains("\"send_behavior\":\"ir_heatpump\""));
    assert!(body.contains("\"report_behavior\":\"sensor_readings\""));
    assert!(body.contains("\"sensor_driver\":\"aht20\""));
    assert!(body.contains("\"ir_transport\":\"esp32s3_rmt\""));
    assert!(body.contains("\"ir_device\":\"gpio17\""));
    assert!(body.contains("\"ir_protocol\":\"midea24_coolix\""));
    assert!(body.contains("\"onboard_url\":\"http://192.168.1.55:5000\""));
    assert!(!body.contains("\"command\""));
}

#[test]
fn null_command_does_not_send_ir() {
    let mut fixture = PollFixture::new(vec![Ok(reading(23.7, 51.2))], vec!["{\"command\":null}"]);

    let outcome = fixture.poll(false, Some(VALID_EPOCH_SECONDS));

    assert_eq!(outcome, PollOutcome::Posted);
    assert_eq!(fixture.dmz.posts.len(), 1);
    assert!(fixture.hardware.midea_commands.is_empty());
    assert!(fixture.hardware.raw_ir_sends.is_empty());
    assert!(!fixture.state.has_last_applied_command);
}

#[test]
fn newer_command_sends_once_and_is_reported_on_next_post() {
    let response = "{\"command\":{\"created_dt\":\"2026-06-14T21:00:01.000000\",\"power\":true,\"mode\":\"COOL\",\"temp_c\":20,\"fan\":\"AUTO\"}}";
    let mut fixture = PollFixture::new(
        vec![Ok(reading(23.7, 51.2)), Ok(reading(23.8, 51.3))],
        vec![response, "{\"command\":null}"],
    );

    assert_eq!(
        fixture.poll(false, Some(VALID_EPOCH_SECONDS)),
        PollOutcome::Posted
    );
    assert_eq!(
        fixture.poll(false, Some(VALID_EPOCH_SECONDS)),
        PollOutcome::Posted
    );

    assert_eq!(fixture.hardware.midea_commands.len(), 1);
    assert!(!fixture.dmz.posts[0].contains("\"command\""));
    assert!(fixture.dmz.posts[1].contains("\"command\":"));
    assert!(fixture.dmz.posts[1].contains("\"created_dt\":\"2026-06-14T21:00:01.000000\""));
}

#[test]
fn same_or_older_command_is_not_repeated() {
    let mut fixture = PollFixture::new(
        vec![
            Ok(reading(23.7, 51.2)),
            Ok(reading(23.8, 51.3)),
            Ok(reading(23.9, 51.4)),
        ],
        vec![
            "{\"command\":{\"created_dt\":\"2026-06-14T21:00:01.000000\",\"power\":true}}",
            "{\"command\":{\"created_dt\":\"2026-06-14T21:00:01.000000\",\"power\":false}}",
            "{\"command\":{\"created_dt\":\"2026-06-14T21:00:00.000000\",\"power\":false}}",
        ],
    );

    assert_eq!(
        fixture.poll(false, Some(VALID_EPOCH_SECONDS)),
        PollOutcome::Posted
    );
    assert_eq!(
        fixture.poll(false, Some(VALID_EPOCH_SECONDS)),
        PollOutcome::Posted
    );
    assert_eq!(
        fixture.poll(false, Some(VALID_EPOCH_SECONDS)),
        PollOutcome::Posted
    );

    assert_eq!(fixture.hardware.midea_commands.len(), 1);
}

#[test]
fn optional_sensor_failure_posts_fallback_values() {
    let mut fixture =
        PollFixture::new(vec![Err(HardwareError::Sensor)], vec!["{\"command\":null}"]);

    let outcome = fixture.poll(false, Some(VALID_EPOCH_SECONDS));

    assert_eq!(outcome, PollOutcome::Posted);
    assert!(fixture.dmz.posts[0].contains("\"temp_centigrade\":1.0"));
    assert!(fixture.dmz.posts[0].contains("\"humid_percent\":1.0"));
}

#[test]
fn required_sensor_failure_blocks_polling() {
    let mut fixture =
        PollFixture::new(vec![Err(HardwareError::Sensor)], vec!["{\"command\":null}"]);

    let outcome = fixture.poll(true, Some(VALID_EPOCH_SECONDS));

    assert_eq!(outcome, PollOutcome::SensorRequired);
    assert!(fixture.dmz.posts.is_empty());
    assert!(fixture.hardware.midea_commands.is_empty());
}

#[test]
fn no_post_before_valid_time() {
    let mut fixture = PollFixture::new(vec![Ok(reading(23.7, 51.2))], vec!["{\"command\":null}"]);

    let outcome = fixture.poll(false, None);

    assert_eq!(outcome, PollOutcome::TimeNotReady);
    assert!(fixture.dmz.posts.is_empty());
    assert!(fixture.hardware.status_events.is_empty());
}

#[test]
fn healthz_reports_esp32s3_backend_core_heap_and_memory_logs() {
    let config = DeviceConfig::kitchen_esp32s3();
    let mut log: RollingLog<64> = RollingLog::new();
    log.push("startup");
    log.push("poll start");
    let runtime = Esp32s3RuntimeStatus {
        uptime_seconds: 12,
        wifi_ready: true,
        sntp_ready: true,
        last_poll_ok: true,
        poll_successes: 2,
        poll_errors: 0,
        ir_sends: 1,
        ir_stub_sends: 0,
        free_heap_bytes: 123_456,
        minimum_free_heap_bytes: 100_000,
        app_core: config.app_core,
    };

    let body = build_healthz_body::<1536>(
        &config,
        &runtime,
        HealthQueues::empty(),
        log.storage::<32>(),
        "2026-06-14T21:00:00Z",
    )
    .expect("health body should fit");

    assert!(body.contains("\"hardware_backend\":\"esp32s3\""));
    assert!(body.contains("\"hardware_profile\":\"esp32s3_aht20_ir\""));
    assert!(body.contains("\"free_heap_bytes\":123456"));
    assert!(body.contains("\"minimum_free_heap_bytes\":100000"));
    assert!(body.contains("\"app_core\":1"));
    assert!(body.contains("\"log_storage\":{\"path\":null,\"type\":\"memory\""));
    assert!(body.contains("\"capacity\":64"));
    assert!(body.contains("\"newest_limit\":32"));
    assert_eq!(log.newest_first::<2>(), ["poll start", "startup"]);
}

fn reading(temp_centigrade: f32, humid_percent: f32) -> SensorReading {
    SensorReading {
        temp_centigrade,
        humid_percent,
        source: SensorSource::Aht20,
    }
}

struct PollFixture {
    config: DeviceConfig,
    state: AppCoreState,
    dmz: FakeDmz,
    hardware: FakeHardware,
}

impl PollFixture {
    fn new(
        sensor_results: Vec<Result<SensorReading, HardwareError>>,
        responses: Vec<&'static str>,
    ) -> Self {
        Self {
            config: DeviceConfig::kitchen_esp32s3(),
            state: AppCoreState::new(),
            dmz: FakeDmz {
                posts: Vec::new(),
                responses: VecDeque::from(responses),
            },
            hardware: FakeHardware {
                sensor_results: VecDeque::from(sensor_results),
                midea_commands: Vec::new(),
                raw_ir_sends: Vec::new(),
                status_events: Vec::new(),
            },
        }
    }

    fn poll(&mut self, sensor_required_at_boot: bool, epoch_seconds: Option<u64>) -> PollOutcome {
        self.config.sensor_required_at_boot = sensor_required_at_boot;
        poll_once::<2048, _, _>(
            &self.config,
            &mut self.state,
            &mut self.dmz,
            &mut self.hardware,
            PollContext {
                epoch_seconds,
                local_ip: None,
                log_lines: &[],
            },
        )
    }
}

struct FakeDmz {
    posts: Vec<StdString>,
    responses: VecDeque<&'static str>,
}

impl DmzClient for FakeDmz {
    type Error = ();

    fn post_sensors<'a, const N: usize>(
        &'a mut self,
        request: &SensorPostRequest<N>,
    ) -> Result<&'a str, Self::Error> {
        assert_eq!(request.method, "POST");
        assert_eq!(request.path.as_str(), "/zone/kitchen/sensors");
        assert_eq!(request.zone_name, "kitchen");
        assert_eq!(request.epoch_seconds, VALID_EPOCH_SECONDS);
        assert_eq!(request.timeout_secs, 600);
        self.posts.push(request.body.to_string());
        Ok(self.responses.pop_front().unwrap_or("{\"command\":null}"))
    }
}

struct FakeHardware {
    sensor_results: VecDeque<Result<SensorReading, HardwareError>>,
    midea_commands: Vec<HeatpumpCommand>,
    raw_ir_sends: Vec<(u32, Vec<i32>)>,
    status_events: Vec<StatusEvent>,
}

impl ThermoHardware for FakeHardware {
    fn read_aht20(&mut self) -> Result<SensorReading, HardwareError> {
        self.sensor_results
            .pop_front()
            .unwrap_or(Err(HardwareError::Sensor))
    }

    fn send_midea_ir(&mut self, command: &HeatpumpCommand) -> Result<(), HardwareError> {
        self.midea_commands.push(*command);
        Ok(())
    }

    fn send_raw_ir(&mut self, carrier_hz: u32, durations_us: &[i32]) -> Result<(), HardwareError> {
        self.raw_ir_sends.push((carrier_hz, durations_us.to_vec()));
        Ok(())
    }

    fn record_ir_rx_edge(&mut self) -> Result<Option<IrEdge>, HardwareError> {
        Ok(None)
    }

    fn set_status(&mut self, event: StatusEvent) -> Result<(), HardwareError> {
        self.status_events.push(event);
        Ok(())
    }

    fn monotonic_millis(&self) -> u64 {
        0
    }
}
