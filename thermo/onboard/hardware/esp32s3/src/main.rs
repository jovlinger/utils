use thermo_esp32s3::{
    build_healthz_body, DeviceConfig, Esp32s3RuntimeStatus, HealthQueues, RollingLog,
};

fn main() {
    let config = DeviceConfig::from_compile_env();
    let log: RollingLog<64> = RollingLog::new();
    let runtime = Esp32s3RuntimeStatus::booting(config.app_core);
    let health = build_healthz_body::<1536>(
        &config,
        &runtime,
        HealthQueues::empty(),
        log.storage::<32>(),
        "1970-01-01T00:00:00Z",
    )
    .expect("host health body should fit");

    println!("{}", health);
}
