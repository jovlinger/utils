use core::fmt::Write;

use heapless::String;

use crate::protocol::{write_json_string, write_json_string_field};
use crate::DeviceConfig;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Esp32s3RuntimeStatus {
    pub uptime_seconds: u64,
    pub wifi_ready: bool,
    pub sntp_ready: bool,
    pub last_poll_ok: bool,
    pub poll_successes: u64,
    pub poll_errors: u64,
    pub ir_sends: u64,
    pub ir_stub_sends: u64,
    pub free_heap_bytes: u32,
    pub minimum_free_heap_bytes: u32,
    pub app_core: u8,
}

impl Esp32s3RuntimeStatus {
    pub const fn booting(app_core: u8) -> Self {
        Self {
            uptime_seconds: 0,
            wifi_ready: false,
            sntp_ready: false,
            last_poll_ok: false,
            poll_successes: 0,
            poll_errors: 0,
            ir_sends: 0,
            ir_stub_sends: 0,
            free_heap_bytes: 0,
            minimum_free_heap_bytes: 0,
            app_core,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HealthQueues {
    pub daikin_size: usize,
    pub daikin_capacity: usize,
}

impl HealthQueues {
    pub const fn empty() -> Self {
        Self {
            daikin_size: 0,
            daikin_capacity: 0,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LogStorage {
    pub path: Option<&'static str>,
    pub capacity: usize,
    pub newest_limit: usize,
    pub len: usize,
}

impl LogStorage {
    pub const fn memory(capacity: usize, newest_limit: usize, len: usize) -> Self {
        Self {
            path: None,
            capacity,
            newest_limit,
            len,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RollingLog<const N: usize> {
    entries: [Option<&'static str>; N],
    next: usize,
    len: usize,
}

impl<const N: usize> Default for RollingLog<N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<const N: usize> RollingLog<N> {
    pub const fn new() -> Self {
        Self {
            entries: [None; N],
            next: 0,
            len: 0,
        }
    }

    pub fn push(&mut self, message: &'static str) {
        if N == 0 {
            return;
        }
        self.entries[self.next] = Some(message);
        self.next = (self.next + 1) % N;
        if self.len < N {
            self.len += 1;
        }
    }

    pub const fn len(&self) -> usize {
        self.len
    }

    pub const fn capacity(&self) -> usize {
        N
    }

    pub fn newest_first<const OUT: usize>(&self) -> [&'static str; OUT] {
        let mut out = [""; OUT];
        if N == 0 || OUT == 0 {
            return out;
        }

        let mut written = 0;
        while written < OUT && written < self.len {
            let newest = (self.next + N - 1 - written) % N;
            out[written] = self.entries[newest].unwrap_or("");
            written += 1;
        }
        out
    }

    pub fn storage<const LIMIT: usize>(&self) -> LogStorage {
        LogStorage::memory(N, LIMIT, self.len)
    }
}

pub fn build_healthz_body<const N: usize>(
    config: &DeviceConfig,
    runtime: &Esp32s3RuntimeStatus,
    queues: HealthQueues,
    log_storage: LogStorage,
    time_utc: &str,
) -> Result<String<N>, core::fmt::Error> {
    let mut body: String<N> = String::new();
    write!(
        body,
        "{{\"ok\":{},\"service\":\"onboard-app\",\"hardware_backend\":\"esp32s3\",\"time\":",
        bool_json(runtime.wifi_ready && runtime.sntp_ready)
    )?;
    write_json_string(&mut body, time_utc)?;
    write!(body, ",\"deployment\":{{")?;
    write_json_string_field(&mut body, "zone_name", config.zone_name)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "hardware_profile", config.hardware_profile)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "send_behavior", config.send_behavior)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "report_behavior", config.report_behavior)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "sensor_driver", config.sensor_driver)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "ir_transport", config.ir_transport)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "ir_device", config.ir_device)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "ir_protocol", config.ir_protocol)?;
    write!(body, ",")?;
    write_json_string_field(&mut body, "status_led_driver", config.status_led_driver)?;
    write!(
        body,
        "}},\"queues\":{{\"daikin_size\":{},\"daikin_capacity\":{}}}",
        queues.daikin_size, queues.daikin_capacity
    )?;
    write_log_storage(&mut body, log_storage)?;
    write!(
        body,
        ",\"esp32s3\":{{\"uptime_seconds\":{},\"wifi_ready\":{},\"sntp_ready\":{},\"last_poll_ok\":{},\"poll_successes\":{},\"poll_errors\":{},\"ir_sends\":{},\"ir_stub_sends\":{},\"free_heap_bytes\":{},\"minimum_free_heap_bytes\":{},\"app_core\":{}}}}}",
        runtime.uptime_seconds,
        bool_json(runtime.wifi_ready),
        bool_json(runtime.sntp_ready),
        bool_json(runtime.last_poll_ok),
        runtime.poll_successes,
        runtime.poll_errors,
        runtime.ir_sends,
        runtime.ir_stub_sends,
        runtime.free_heap_bytes,
        runtime.minimum_free_heap_bytes,
        runtime.app_core
    )?;
    Ok(body)
}

fn write_log_storage<const N: usize>(
    body: &mut String<N>,
    log_storage: LogStorage,
) -> Result<(), core::fmt::Error> {
    write!(body, ",\"log_storage\":{{\"path\":")?;
    if let Some(path) = log_storage.path {
        write_json_string(body, path)?;
    } else {
        write!(body, "null")?;
    }
    write!(
        body,
        ",\"type\":\"memory\",\"capacity\":{},\"newest_limit\":{},\"len\":{}}}",
        log_storage.capacity, log_storage.newest_limit, log_storage.len
    )
}

fn bool_json(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

#[cfg(test)]
mod tests {
    use super::{build_healthz_body, Esp32s3RuntimeStatus, HealthQueues, RollingLog};
    use crate::DeviceConfig;

    #[test]
    fn rolling_log_returns_newest_first() {
        let mut log: RollingLog<3> = RollingLog::new();

        log.push("one");
        log.push("two");
        log.push("three");
        log.push("four");

        assert_eq!(log.len(), 3);
        assert_eq!(log.capacity(), 3);
        assert_eq!(log.newest_first::<3>(), ["four", "three", "two"]);
    }

    #[test]
    fn healthz_reports_esp32s3_metadata() {
        let config = DeviceConfig::kitchen_esp32s3();
        let log: RollingLog<64> = RollingLog::new();
        let mut runtime = Esp32s3RuntimeStatus::booting(config.app_core);
        runtime.wifi_ready = true;
        runtime.sntp_ready = true;

        let body = build_healthz_body::<1536>(
            &config,
            &runtime,
            HealthQueues::empty(),
            log.storage::<32>(),
            "2026-06-14T21:00:00Z",
        )
        .unwrap();

        assert!(body.contains("\"hardware_backend\":\"esp32s3\""));
        assert!(body.contains("\"hardware_profile\":\"esp32s3_aht20_ir\""));
        assert!(body.contains("\"ir_transport\":\"esp32s3_rmt\""));
        assert!(body.contains("\"status_led_driver\":\"log_only\""));
        assert!(body.contains("\"app_core\":1"));
    }
}
