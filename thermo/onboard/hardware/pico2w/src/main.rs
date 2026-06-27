use thermo_pico2w::{
    read_sensors_or_fallback, signal_status, AccurateSensor, BlinkPattern, DeviceConfig,
    SensorReading, StatusEvent, StatusLed,
};

struct MissingAht20;

impl AccurateSensor for MissingAht20 {
    type Error = &'static str;

    fn read(&mut self) -> Result<SensorReading, Self::Error> {
        Err("AHT20 did not respond")
    }
}

struct LoggingStatusLed;

impl StatusLed for LoggingStatusLed {
    type Error = &'static str;

    fn blink(&mut self, pattern: BlinkPattern) -> Result<(), Self::Error> {
        println!(
            "status_led blink color={:?} pulses={}",
            pattern.color, pattern.pulses
        );
        Ok(())
    }
}

fn main() {
    let mut status_led = LoggingStatusLed;
    signal_status(&mut status_led, StatusEvent::ReadingEnv).expect("status LED should log");

    let config: DeviceConfig = DeviceConfig::from_compile_env();
    let mut sensor = MissingAht20;
    let reading: SensorReading =
        match read_sensors_or_fallback(&mut sensor, config.sensor_required_at_boot) {
            Ok(reading) => reading,
            Err(_) => {
                signal_status(&mut status_led, StatusEvent::Error).expect("status LED should log");
                panic!("required sensor did not respond");
            }
        };
    signal_status(&mut status_led, StatusEvent::PollSucceeded).expect("status LED should log");

    println!(
        "pico2w zone={} sensor={} source={:?} temp_c={} humid_percent={}",
        config.zone_name,
        config.sensor_driver,
        reading.source,
        reading.temp_centigrade,
        reading.humid_percent
    );
}
