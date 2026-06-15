#![no_std]
#![no_main]

use core::cell::RefCell;
use core::fmt::Write;
use core::str;

use cyw43::{aligned_bytes, JoinOptions};
use cyw43_pio::{PioSpi, RM2_CLOCK_DIVIDER};
use embassy_executor::Spawner;
use embassy_net::dns::DnsQueryType;
use embassy_net::tcp::TcpSocket;
use embassy_net::{Config, DhcpConfig, Stack, StackResources};
use embassy_rp::gpio::{Level, Output, OutputOpenDrain};
use embassy_rp::peripherals::{DMA_CH0, PIO0, USB};
use embassy_rp::pio::{InterruptHandler, Pio};
use embassy_rp::usb::{Driver as UsbDriver, InterruptHandler as UsbInterruptHandler};
use embassy_rp::{bind_interrupts, dma};
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::blocking_mutex::Mutex;
use embassy_time::{block_for, Duration, Instant, Timer};
use embassy_usb::class::cdc_acm::{CdcAcmClass, State as CdcAcmState};
use embassy_usb::driver::EndpointError;
use embassy_usb::{Builder as UsbBuilder, Config as UsbConfig, UsbDevice};
use heapless::String;
use panic_halt as _;
use static_cell::StaticCell;
use thermo_pico2w::{
    build_sensor_post_body, command_is_new, extract_command_created_dt, extract_command_json,
    for_each_raw_ir_duration, is_raw_ir_command, midea_classic_frames, parse_heatpump_command,
    parse_server_time_utc_epoch, pattern_for_event, read_sensors_or_fallback, wifi_password,
    wifi_ssid, zone_private_key_b64, AccurateSensor, Aht20, DeviceConfig, MideaClassicFrames,
    RollingLog, SensorSource, SoftI2c, StatusEvent, ZoneAuth, MIDEA_GAP_US, MIDEA_PULSE_US,
    MIDEA_SPACE_ONE_US, MIDEA_SPACE_ZERO_US, MIDEA_START_PULSE_US, MIDEA_START_SPACE_US,
    PICO2W_AHT20_SCL_GPIO, PICO2W_AHT20_SDA_GPIO, PICO2W_IR_RX_GPIO, PICO2W_IR_TX_GPIO,
};

type HealthMutex = Mutex<CriticalSectionRawMutex, RefCell<HealthState>>;
const HEALTH_LOG_CAPACITY: usize = 64;
const HEALTH_LOG_RETURNED: usize = 32;

const _: () = {
    assert!(PICO2W_AHT20_SCL_GPIO == 27);
    assert!(PICO2W_AHT20_SDA_GPIO == 28);
    assert!(PICO2W_IR_TX_GPIO == 10);
    assert!(PICO2W_IR_RX_GPIO == 13);
};

#[derive(Clone, Debug, Eq, PartialEq)]
struct HealthState {
    log: RollingLog<HEALTH_LOG_CAPACITY>,
    wifi_ready: bool,
    last_poll_ok: bool,
    poll_successes: u32,
    poll_errors: u32,
    ir_sends: u32,
}

impl HealthState {
    const fn new() -> Self {
        Self {
            log: RollingLog::new(),
            wifi_ready: false,
            last_poll_ok: false,
            poll_successes: 0,
            poll_errors: 0,
            ir_sends: 0,
        }
    }
}

#[link_section = ".bi_entries"]
#[used]
pub static PICOTOOL_ENTRIES: [embassy_rp::binary_info::EntryAddr; 4] = [
    embassy_rp::binary_info::rp_program_name!(c"Thermo Pico2W Poller"),
    embassy_rp::binary_info::rp_program_description!(
        c"Thermo Pico2W DMZ long-poll with AHT20 sensor and Midea IR TX"
    ),
    embassy_rp::binary_info::rp_cargo_version!(),
    embassy_rp::binary_info::rp_program_build_attribute!(),
];

bind_interrupts!(struct Irqs {
    PIO0_IRQ_0 => InterruptHandler<PIO0>;
    DMA_IRQ_0 => dma::InterruptHandler<DMA_CH0>;
    USBCTRL_IRQ => UsbInterruptHandler<USB>;
});

#[embassy_executor::task]
async fn cyw43_task(
    runner: cyw43::Runner<'static, cyw43::SpiBus<Output<'static>, PioSpi<'static, PIO0, 0>>>,
) -> ! {
    runner.run().await
}

#[embassy_executor::task]
async fn net_task(mut runner: embassy_net::Runner<'static, cyw43::NetDriver<'static>>) -> ! {
    runner.run().await
}

#[embassy_executor::task]
async fn healthz_task(
    stack: Stack<'static>,
    config: DeviceConfig,
    health: &'static HealthMutex,
) -> ! {
    run_healthz_server(stack, config, health).await
}

#[embassy_executor::task]
async fn usb_device_task(mut usb: UsbDevice<'static, UsbDriver<'static, USB>>) -> ! {
    usb.run().await
}

#[embassy_executor::task]
async fn usb_log_task(
    mut class: CdcAcmClass<'static, UsbDriver<'static, USB>>,
    health: &'static HealthMutex,
) -> ! {
    loop {
        class.wait_connection().await;
        let _ = cdc_write_line(&mut class, "Thermo Pico2W USB debug log connected").await;
        let mut last_latest = "";
        loop {
            let latest = latest_health_log(health);
            if !latest.is_empty() && latest != last_latest {
                if write_health_log_snapshot(&mut class, health).await.is_err() {
                    break;
                }
                last_latest = latest;
            }
            Timer::after(Duration::from_millis(500)).await;
        }
    }
}

fn start_usb_debug(
    spawner: &Spawner,
    driver: UsbDriver<'static, USB>,
    health: &'static HealthMutex,
) {
    let mut config = UsbConfig::new(0xc0de, 0x0202);
    config.manufacturer = Some("jovlinger");
    config.product = Some("Thermo Pico2W Debug");
    config.serial_number = Some("thermo-pico2w");

    static CONFIG_DESCRIPTOR: StaticCell<[u8; 256]> = StaticCell::new();
    static BOS_DESCRIPTOR: StaticCell<[u8; 256]> = StaticCell::new();
    static MSOS_DESCRIPTOR: StaticCell<[u8; 256]> = StaticCell::new();
    static CONTROL_BUF: StaticCell<[u8; 64]> = StaticCell::new();
    static CDC_STATE: StaticCell<CdcAcmState<'static>> = StaticCell::new();

    let mut builder = UsbBuilder::new(
        driver,
        config,
        CONFIG_DESCRIPTOR.init([0; 256]),
        BOS_DESCRIPTOR.init([0; 256]),
        MSOS_DESCRIPTOR.init([0; 256]),
        CONTROL_BUF.init([0; 64]),
    );
    let state = CDC_STATE.init(CdcAcmState::new());
    let class = CdcAcmClass::new(&mut builder, state, 64);
    let usb = builder.build();

    match usb_device_task(usb) {
        Ok(task) => spawner.spawn(task),
        Err(_) => health_log(health, "usb device task spawn failed"),
    }
    match usb_log_task(class, health) {
        Ok(task) => spawner.spawn(task),
        Err(_) => health_log(health, "usb log task spawn failed"),
    }
    health_log(health, "usb debug serial started");
}

fn latest_health_log(health: &'static HealthMutex) -> &'static str {
    health.lock(|cell| {
        let state = cell.borrow();
        state.log.newest_first::<1>()[0]
    })
}

fn recent_log_lines<const N: usize>(health: &'static HealthMutex) -> [&'static str; N] {
    health.lock(|cell| {
        let state = cell.borrow();
        state.log.newest_first::<N>()
    })
}

async fn write_health_log_snapshot(
    class: &mut CdcAcmClass<'static, UsbDriver<'static, USB>>,
    health: &'static HealthMutex,
) -> Result<(), EndpointError> {
    let logs = health.lock(|cell| {
        let state = cell.borrow();
        state.log.newest_first::<16>()
    });
    let mut index = logs.len();
    while index > 0 {
        index -= 1;
        let message = logs[index];
        if message.is_empty() {
            continue;
        }
        let mut line: String<128> = String::new();
        let _ = write!(line, "[{}s] {}", Instant::now().as_secs(), message);
        cdc_write_line(class, &line).await?;
    }
    Ok(())
}

async fn cdc_write_line(
    class: &mut CdcAcmClass<'static, UsbDriver<'static, USB>>,
    line: &str,
) -> Result<(), EndpointError> {
    cdc_write_str(class, line).await?;
    cdc_write_str(class, "\r\n").await
}

async fn cdc_write_str(
    class: &mut CdcAcmClass<'static, UsbDriver<'static, USB>>,
    text: &str,
) -> Result<(), EndpointError> {
    let mut remaining = text.as_bytes();
    while !remaining.is_empty() {
        let chunk_len = if remaining.len() > 64 {
            64
        } else {
            remaining.len()
        };
        class.write_packet(&remaining[..chunk_len]).await?;
        remaining = &remaining[chunk_len..];
    }
    Ok(())
}

fn dhcp_hostname(zone_name: &str) -> String<32> {
    let mut hostname: String<32> = String::new();
    let _ = hostname.push_str("pico");
    if !zone_name.is_empty() {
        let _ = hostname.push('-');
        for byte in zone_name.bytes() {
            let next = if byte.is_ascii_alphanumeric() || byte == b'-' {
                byte as char
            } else {
                '-'
            };
            if hostname.push(next).is_err() {
                break;
            }
        }
    }
    hostname
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());
    static HEALTH: StaticCell<HealthMutex> = StaticCell::new();
    let health = HEALTH.init(Mutex::new(RefCell::new(HealthState::new())));
    health_log(health, "boot start");
    start_usb_debug(&spawner, UsbDriver::new(p.USB, Irqs), health);

    let fw = aligned_bytes!("../../cyw43-firmware/43439A0.bin");
    let clm = aligned_bytes!("../../cyw43-firmware/43439A0_clm.bin");
    let nvram = aligned_bytes!("../../cyw43-firmware/nvram_rp2040.bin");

    let pwr = Output::new(p.PIN_23, Level::Low);
    let cs = Output::new(p.PIN_25, Level::High);
    let mut pio = Pio::new(p.PIO0, Irqs);
    let spi = PioSpi::new(
        &mut pio.common,
        pio.sm0,
        RM2_CLOCK_DIVIDER,
        pio.irq0,
        cs,
        p.PIN_24,
        p.PIN_29,
        dma::Channel::new(p.DMA_CH0, Irqs),
    );

    static STATE: StaticCell<cyw43::State> = StaticCell::new();
    let state = STATE.init(cyw43::State::new());
    let (net_device, mut control, runner) = cyw43::new(state, pwr, spi, fw, nvram).await;
    match cyw43_task(runner) {
        Ok(task) => spawner.spawn(task),
        Err(_) => loop {
            Timer::after(Duration::from_secs(1)).await;
        },
    }

    control.init(clm).await;
    control
        .set_power_management(cyw43::PowerManagementMode::PowerSave)
        .await;

    status(&mut control, StatusEvent::ReadingEnv).await;
    let config = DeviceConfig::from_compile_env();
    let i2c = SoftI2c::new(
        OutputOpenDrain::new(p.PIN_28, Level::High),
        OutputOpenDrain::new(p.PIN_27, Level::High),
    );
    let mut aht20 = Aht20::new(i2c, config.aht20_addr);
    if config.sensor_required_at_boot {
        match read_sensors_or_fallback(&mut aht20, true) {
            Ok(_) => health_log(health, "sensor boot ok"),
            Err(_) => error_forever(&mut control, health, "required sensor did not respond").await,
        }
    }
    let mut ir_tx = Output::new(p.PIN_10, Level::Low);
    health_log(health, "cyw43 init complete");
    health_log(health, "config loaded");

    let (ssid, password, key_b64) = match (wifi_ssid(), wifi_password(), zone_private_key_b64()) {
        (Some(ssid), Some(password), Some(key_b64)) => (ssid, password, key_b64),
        _ => {
            error_forever(
                &mut control,
                health,
                "missing compile-time WiFi or zone key",
            )
            .await
        }
    };
    let auth = match ZoneAuth::from_base64_key(key_b64) {
        Ok(auth) => auth,
        Err(_) => error_forever(&mut control, health, "zone key parse failed").await,
    };
    health_log(health, "zone key parsed");

    let mut dhcp_config = DhcpConfig::default();
    dhcp_config.hostname = Some(dhcp_hostname(config.zone_name));
    let stack_config = Config::dhcpv4(dhcp_config);
    static RESOURCES: StaticCell<StackResources<4>> = StaticCell::new();
    health_log(health, "net stack create start");
    let (stack, runner) = embassy_net::new(
        net_device,
        stack_config,
        RESOURCES.init(StackResources::new()),
        0xfeed_cafe_dead_beef,
    );
    match net_task(runner) {
        Ok(task) => {
            spawner.spawn(task);
        }
        Err(_) => error_forever(&mut control, health, "net task create failed").await,
    }
    health_log(health, "net task spawned");

    connect_wifi(&mut control, health, ssid, password, stack).await;
    health_log(health, "healthz task create start");
    match healthz_task(stack, config, health) {
        Ok(task) => spawner.spawn(task),
        Err(_) => error_forever(&mut control, health, "healthz task create failed").await,
    }
    health_log(health, "healthz task spawned");

    let mut clock = match fetch_dmz_clock(&config, stack, health).await {
        Ok(clock) => clock,
        Err(_) => retry_dmz_clock(&mut control, health, &config, stack).await,
    };

    let mut last_command_json: String<1024> = String::new();
    let mut last_applied_created_dt: String<64> = String::new();
    let mut retry_secs: u64 = 5;

    loop {
        match poll_once(
            &mut control,
            health,
            &config,
            &auth,
            stack,
            &clock,
            &mut aht20,
            &mut ir_tx,
            &mut last_command_json,
            &mut last_applied_created_dt,
        )
        .await
        {
            Ok(()) => {
                retry_secs = 5;
            }
            Err(PollError::ClockExpired) => {
                status(&mut control, StatusEvent::Error).await;
                health_error(health, "clock expired");
                clock = retry_dmz_clock(&mut control, health, &config, stack).await;
            }
            Err(error) => {
                status(&mut control, StatusEvent::Error).await;
                health_error(health, error.log_message());
                Timer::after(Duration::from_secs(retry_secs)).await;
                retry_secs = (retry_secs * 2).min(60);
            }
        }
    }
}

async fn connect_wifi(
    control: &mut cyw43::Control<'_>,
    health: &'static HealthMutex,
    ssid: &str,
    password: &str,
    stack: Stack<'static>,
) {
    loop {
        health_log(health, "wifi join start");
        match control
            .join(ssid, JoinOptions::new(password.as_bytes()))
            .await
        {
            Ok(()) => {
                health_log(health, "wifi join ok");
                break;
            }
            Err(_) => {
                health_log(health, "wifi join failed");
                status(control, StatusEvent::Error).await;
                Timer::after(Duration::from_secs(5)).await;
            }
        }
    }
    health_log(health, "wifi wait link");
    stack.wait_link_up().await;
    health_log(health, "wifi link up");
    health_log(health, "wifi wait dhcp");
    stack.wait_config_up().await;
    set_wifi_ready(health);
}

#[derive(Clone, Copy)]
struct DmzClock {
    epoch_seconds: u64,
    boot_seconds: u64,
}

impl DmzClock {
    fn now(&self) -> Result<u64, PollError> {
        let elapsed = Instant::now()
            .as_secs()
            .checked_sub(self.boot_seconds)
            .ok_or(PollError::ClockExpired)?;
        if elapsed > 3_600 {
            return Err(PollError::ClockExpired);
        }
        self.epoch_seconds
            .checked_add(elapsed)
            .ok_or(PollError::ClockExpired)
    }
}

async fn retry_dmz_clock(
    control: &mut cyw43::Control<'_>,
    health: &'static HealthMutex,
    config: &DeviceConfig,
    stack: Stack<'static>,
) -> DmzClock {
    loop {
        status(control, StatusEvent::Error).await;
        health_error(health, "fetch dmz clock failed");
        Timer::after(Duration::from_secs(10)).await;
        if let Ok(clock) = fetch_dmz_clock(config, stack, health).await {
            return clock;
        }
    }
}

async fn fetch_dmz_clock(
    config: &DeviceConfig,
    stack: Stack<'static>,
    health: &'static HealthMutex,
) -> Result<DmzClock, PollError> {
    health_log(health, "clock fetch start");
    let epoch_seconds = http_get_stream_server_time(stack, config, health).await?;
    health_log(health, "clock fetch ok");
    Ok(DmzClock {
        epoch_seconds,
        boot_seconds: Instant::now().as_secs(),
    })
}

async fn poll_once<S>(
    control: &mut cyw43::Control<'_>,
    health: &'static HealthMutex,
    config: &DeviceConfig,
    auth: &ZoneAuth,
    stack: Stack<'static>,
    clock: &DmzClock,
    aht20: &mut S,
    ir_tx: &mut Output<'static>,
    last_command_json: &mut String<1024>,
    last_applied_created_dt: &mut String<64>,
) -> Result<(), PollError>
where
    S: AccurateSensor,
{
    status(control, StatusEvent::PollStarted).await;
    health_log(health, "poll start");
    let reading = match read_sensors_or_fallback(aht20, config.sensor_required_at_boot) {
        Ok(reading) => reading,
        Err(_) => {
            health_log(health, "sensor required missing");
            return Err(PollError::SensorRequired);
        }
    };
    if reading.source == SensorSource::Aht20 {
        health_log(health, "sensor aht20 ok");
    } else {
        health_log(health, "sensor fallback ok");
    }
    let command_for_body = if last_command_json.is_empty() {
        None
    } else {
        Some(last_command_json.as_str())
    };
    let log_lines = recent_log_lines::<24>(health);
    let local_ip = local_ipv4_string::<16>(stack);
    let body = build_sensor_post_body::<4096>(
        config,
        reading,
        command_for_body,
        &log_lines,
        local_ip.as_deref(),
    )
    .map_err(|_| PollError::BuildBody)?;
    health_log(health, "poll body built");

    let mut path: String<96> = String::new();
    write!(path, "/zone/{}/sensors", config.zone_name).map_err(|_| PollError::BuildBody)?;

    let signed = auth
        .sign_headers::<96, 16>(
            "POST",
            path.as_str(),
            body.as_bytes(),
            config.zone_name,
            clock.now()?,
        )
        .map_err(|_| PollError::Sign)?;
    health_log(health, "poll sign ok");

    let mut extra_headers: String<256> = String::new();
    write!(
        extra_headers,
        "X-Zone-Signature: {}\r\nX-Zone-Timestamp: {}\r\nX-Zone-Name: {}\r\n",
        signed.signature_b64, signed.timestamp, signed.zone_name
    )
    .map_err(|_| PollError::BuildBody)?;

    let mut response_body: String<4096> = String::new();
    health_log(health, "dmz post start");
    let status_code = http_request::<6144, 8192>(
        stack,
        config,
        "POST",
        path.as_str(),
        extra_headers.as_str(),
        Some(body.as_str()),
        &mut response_body,
        health,
    )
    .await?;
    if status_code != 200 {
        health_log(health, "dmz post returned non-200");
        return Err(PollError::HttpStatus);
    }
    health_log(health, "dmz post 200");

    let response_created_dt = extract_command_created_dt(response_body.as_str());
    if command_is_new(last_applied_created_dt.as_str(), response_created_dt) {
        health_log(health, "command newer");
        let command_json = extract_command_json(response_body.as_str()).ok_or(PollError::Parse)?;
        status(control, StatusEvent::SendingIr).await;
        transmit_ir_command(command_json, config, ir_tx, health)?;
        last_applied_created_dt.clear();
        last_applied_created_dt
            .push_str(response_created_dt.ok_or(PollError::Parse)?)
            .map_err(|_| PollError::Parse)?;
        last_command_json.clear();
        last_command_json
            .push_str(command_json)
            .map_err(|_| PollError::Parse)?;
    } else if response_created_dt.is_some() {
        health_log(health, "command stale");
    } else {
        health_log(health, "command none");
    }

    health_success(health, "poll succeeded");
    Ok(())
}

fn transmit_ir_command(
    command_json: &str,
    config: &DeviceConfig,
    ir_tx: &mut Output<'static>,
    health: &'static HealthMutex,
) -> Result<(), PollError> {
    if is_raw_ir_command(command_json) {
        transmit_raw_ir_sequence(command_json, ir_tx, health)?;
        return Ok(());
    }
    if config.ir_protocol != "midea_classic" {
        health_log(health, "IR protocol unsupported");
        return Err(PollError::IrProtocol);
    }
    let command = parse_heatpump_command(command_json).ok_or(PollError::Parse)?;
    let frames = midea_classic_frames(command);
    transmit_midea_classic(ir_tx, frames);
    health.lock(|cell| {
        let mut state = cell.borrow_mut();
        state.ir_sends = state.ir_sends.saturating_add(1);
        state.log.push("IR sent command");
    });
    Ok(())
}

fn transmit_raw_ir_sequence(
    command_json: &str,
    ir_tx: &mut Output<'static>,
    health: &'static HealthMutex,
) -> Result<(), PollError> {
    for_each_raw_ir_duration(command_json, |_| {}).ok_or(PollError::Parse)?;
    for_each_raw_ir_duration(command_json, |duration_us| {
        if duration_us > 0 {
            transmit_mark(ir_tx, duration_us as u64);
        } else {
            transmit_space(ir_tx, i64::from(duration_us).unsigned_abs());
        }
    })
    .ok_or(PollError::Parse)?;
    health.lock(|cell| {
        let mut state = cell.borrow_mut();
        state.ir_sends = state.ir_sends.saturating_add(1);
        state.log.push("IR sent raw command");
    });
    Ok(())
}

fn transmit_midea_classic(ir_tx: &mut Output<'static>, frames: MideaClassicFrames) {
    let mut frame_index = 0;
    while frame_index < frames.count {
        transmit_mark(ir_tx, MIDEA_START_PULSE_US);
        transmit_space(ir_tx, MIDEA_START_SPACE_US);
        let frame = frames.frames[frame_index];
        for byte in frame {
            let mut bit_index = 8;
            while bit_index > 0 {
                bit_index -= 1;
                transmit_mark(ir_tx, MIDEA_PULSE_US);
                if ((byte >> bit_index) & 1) == 1 {
                    transmit_space(ir_tx, MIDEA_SPACE_ONE_US);
                } else {
                    transmit_space(ir_tx, MIDEA_SPACE_ZERO_US);
                }
            }
        }
        transmit_mark(ir_tx, MIDEA_PULSE_US);
        transmit_space(ir_tx, MIDEA_GAP_US);
        frame_index += 1;
    }
}

fn transmit_mark(ir_tx: &mut Output<'static>, duration_us: u64) {
    let cycles = (duration_us + 13) / 26;
    for _ in 0..cycles {
        ir_tx.set_high();
        block_for(Duration::from_micros(13));
        ir_tx.set_low();
        block_for(Duration::from_micros(13));
    }
}

fn transmit_space(ir_tx: &mut Output<'static>, duration_us: u64) {
    ir_tx.set_low();
    block_for(Duration::from_micros(duration_us));
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PollError {
    BuildBody,
    ClockExpired,
    Connect,
    Dns,
    HttpStatus,
    IrProtocol,
    Parse,
    Read,
    SensorRequired,
    Sign,
    Write,
}

impl PollError {
    fn log_message(self) -> &'static str {
        match self {
            PollError::BuildBody => "poll failed: build body",
            PollError::ClockExpired => "poll failed: clock expired",
            PollError::Connect => "poll failed: connect",
            PollError::Dns => "poll failed: dns",
            PollError::HttpStatus => "poll failed: http status",
            PollError::IrProtocol => "poll failed: ir protocol",
            PollError::Parse => "poll failed: parse",
            PollError::Read => "poll failed: read",
            PollError::SensorRequired => "poll failed: sensor required",
            PollError::Sign => "poll failed: sign",
            PollError::Write => "poll failed: write",
        }
    }
}

async fn http_request<const REQ: usize, const RAW: usize>(
    stack: Stack<'static>,
    config: &DeviceConfig,
    method: &str,
    path: &str,
    extra_headers: &str,
    body: Option<&str>,
    response_body: &mut String<4096>,
    health: &'static HealthMutex,
) -> Result<u16, PollError> {
    health_log(health, "http dns start");
    let addrs = stack
        .dns_query(config.dmz_host, DnsQueryType::A)
        .await
        .map_err(|_| PollError::Dns)?;
    let addr = addrs.first().copied().ok_or(PollError::Dns)?;
    health_log(health, "http dns ok");

    let mut rx_buffer = [0_u8; 4096];
    let mut tx_buffer = [0_u8; 2048];
    let mut socket = TcpSocket::new(stack, &mut rx_buffer, &mut tx_buffer);
    socket.set_timeout(Some(Duration::from_secs(config.post_timeout_secs)));
    health_log(health, "http connect start");
    socket
        .connect((addr, config.dmz_port))
        .await
        .map_err(|_| PollError::Connect)?;
    health_log(health, "http connect ok");

    let mut request: String<REQ> = String::new();
    health_log(health, "http request build start");
    write!(
        request,
        "{} {} HTTP/1.1\r\nHost: {}:{}\r\nAccept: application/json\r\nConnection: close\r\n",
        method, path, config.dmz_host, config.dmz_port
    )
    .map_err(|_| {
        health_log(health, "http request line build failed");
        PollError::BuildBody
    })?;
    if let Some(body) = body {
        health_log(health, "http request has body");
        write!(
            request,
            "Content-Type: application/json\r\nContent-Length: {}\r\n",
            body.len()
        )
        .map_err(|_| {
            health_log(health, "http body header build failed");
            PollError::BuildBody
        })?;
    } else {
        health_log(health, "http request no body");
    }
    request.push_str(extra_headers).map_err(|_| {
        health_log(health, "http extra headers build failed");
        PollError::BuildBody
    })?;
    request.push_str("\r\n").map_err(|_| {
        health_log(health, "http header terminator build failed");
        PollError::BuildBody
    })?;
    if let Some(body) = body {
        request.push_str(body).map_err(|_| {
            health_log(health, "http request body build failed");
            PollError::BuildBody
        })?;
    }
    health_log(health, "http request build ok");

    health_log(health, "http write start");
    write_all(&mut socket, request.as_bytes())
        .await
        .map_err(|error| {
            health_log(health, "http write failed");
            error
        })?;
    health_log(health, "http flush start");
    socket.flush().await.map_err(|_| {
        health_log(health, "http flush failed");
        PollError::Write
    })?;
    health_log(health, "http write ok");

    let mut raw_response: String<RAW> = String::new();
    let mut read_buffer = [0_u8; 512];
    health_log(health, "http read start");
    loop {
        match socket.read(&mut read_buffer).await {
            Ok(0) => break,
            Ok(n) => {
                health_log(health, "http read chunk");
                let chunk = str::from_utf8(&read_buffer[..n]).map_err(|_| PollError::Read)?;
                raw_response.push_str(chunk).map_err(|_| {
                    health_log(health, "http raw response too large");
                    PollError::Read
                })?;
            }
            Err(_) => {
                health_log(health, "http read failed");
                return Err(PollError::Read);
            }
        }
    }
    health_log(health, "http read eof");

    health_log(health, "http parse status start");
    let status_code = match parse_http_status(raw_response.as_str()) {
        Some(status_code) => status_code,
        None => {
            health_log(health, "http parse status failed");
            return Err(PollError::Parse);
        }
    };
    health_log(health, "http parse header end start");
    let body_start = match raw_response.find("\r\n\r\n") {
        Some(body_start) => body_start + 4,
        None => {
            health_log(health, "http parse header end failed");
            return Err(PollError::Parse);
        }
    };
    response_body.clear();
    response_body
        .push_str(&raw_response[body_start..])
        .map_err(|_| {
            health_log(health, "http response body copy failed");
            PollError::Read
        })?;
    health_log(health, "http parse ok");
    Ok(status_code)
}

async fn http_get_stream_server_time(
    stack: Stack<'static>,
    config: &DeviceConfig,
    health: &'static HealthMutex,
) -> Result<u64, PollError> {
    health_log(health, "clock stream dns start");
    let addrs = stack
        .dns_query(config.dmz_host, DnsQueryType::A)
        .await
        .map_err(|_| PollError::Dns)?;
    let addr = addrs.first().copied().ok_or(PollError::Dns)?;
    health_log(health, "clock stream dns ok");

    let mut rx_buffer = [0_u8; 2048];
    let mut tx_buffer = [0_u8; 512];
    let mut socket = TcpSocket::new(stack, &mut rx_buffer, &mut tx_buffer);
    socket.set_timeout(Some(Duration::from_secs(config.post_timeout_secs)));
    health_log(health, "clock stream connect start");
    socket
        .connect((addr, config.dmz_port))
        .await
        .map_err(|_| PollError::Connect)?;
    health_log(health, "clock stream connect ok");

    let mut request: String<256> = String::new();
    write!(
        request,
        "GET /ui/diagnostics HTTP/1.1\r\nHost: {}:{}\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
        config.dmz_host, config.dmz_port
    )
    .map_err(|_| PollError::BuildBody)?;
    health_log(health, "clock stream request built");

    write_all(&mut socket, request.as_bytes())
        .await
        .map_err(|error| {
            health_log(health, "clock stream write failed");
            error
        })?;
    socket.flush().await.map_err(|_| {
        health_log(health, "clock stream flush failed");
        PollError::Write
    })?;
    health_log(health, "clock stream write ok");

    let mut window: String<512> = String::new();
    let mut read_buffer = [0_u8; 256];
    let mut status_seen = false;
    let mut headers_done = false;
    health_log(health, "clock stream read start");
    loop {
        match socket.read(&mut read_buffer).await {
            Ok(0) => {
                health_log(health, "clock stream read eof");
                break;
            }
            Ok(n) => {
                health_log(health, "clock stream read chunk");
                let chunk = str::from_utf8(&read_buffer[..n]).map_err(|_| {
                    health_log(health, "clock stream utf8 failed");
                    PollError::Read
                })?;
                append_rolling(&mut window, chunk);

                if !status_seen {
                    if let Some(status_code) = parse_http_status(window.as_str()) {
                        status_seen = true;
                        if status_code == 200 {
                            health_log(health, "clock stream status 200");
                        } else {
                            health_log(health, "clock stream non-200");
                            return Err(PollError::HttpStatus);
                        }
                    }
                }

                if !headers_done && window.find("\r\n\r\n").is_some() {
                    headers_done = true;
                    health_log(health, "clock stream headers done");
                }

                if headers_done {
                    health_log(health, "clock stream parse time start");
                    if let Some(epoch_seconds) = parse_server_time_utc_epoch(window.as_str()) {
                        health_log(health, "clock stream parse time ok");
                        return Ok(epoch_seconds);
                    }
                }
            }
            Err(_) => {
                health_log(health, "clock stream read failed");
                return Err(PollError::Read);
            }
        }
    }

    if !status_seen {
        health_log(health, "clock stream status missing");
    } else if !headers_done {
        health_log(health, "clock stream headers missing");
    } else {
        health_log(health, "clock stream time missing");
    }
    Err(PollError::Parse)
}

fn append_rolling<const N: usize>(window: &mut String<N>, chunk: &str) {
    if window.push_str(chunk).is_ok() {
        return;
    }

    let keep_from = window
        .len()
        .saturating_sub(N.saturating_div(2))
        .min(window.len());
    let mut rolled: String<N> = String::new();
    let _ = rolled.push_str(&window.as_str()[keep_from..]);
    window.clear();
    let _ = window.push_str(rolled.as_str());

    if window.push_str(chunk).is_err() {
        let start = chunk.len().saturating_sub(N.saturating_sub(1));
        window.clear();
        let _ = window.push_str(&chunk[start..]);
    }
}

async fn write_all(socket: &mut TcpSocket<'_>, mut bytes: &[u8]) -> Result<(), PollError> {
    while !bytes.is_empty() {
        let written = socket.write(bytes).await.map_err(|_| PollError::Write)?;
        if written == 0 {
            return Err(PollError::Write);
        }
        bytes = &bytes[written..];
    }
    Ok(())
}

fn parse_http_status(response: &str) -> Option<u16> {
    let line_end = response.find("\r\n")?;
    let line = &response[..line_end];
    let status = line.split(' ').nth(1)?;
    status.parse().ok()
}

async fn error_forever(
    control: &mut cyw43::Control<'_>,
    health: &'static HealthMutex,
    message: &'static str,
) -> ! {
    health_error(health, message);
    loop {
        status(control, StatusEvent::Error).await;
        Timer::after(Duration::from_secs(60)).await;
    }
}

async fn status(control: &mut cyw43::Control<'_>, event: StatusEvent) {
    pulse(control, pattern_for_event(event).pulses).await;
}

async fn pulse(control: &mut cyw43::Control<'_>, count: u8) {
    let mut remaining = count;
    while remaining > 0 {
        control.gpio_set(0, true).await;
        Timer::after(Duration::from_millis(150)).await;
        control.gpio_set(0, false).await;
        Timer::after(Duration::from_millis(150)).await;
        remaining -= 1;
    }
}

fn health_log(health: &'static HealthMutex, message: &'static str) {
    health.lock(|cell| cell.borrow_mut().log.push(message));
}

fn health_success(health: &'static HealthMutex, message: &'static str) {
    health.lock(|cell| {
        let mut state = cell.borrow_mut();
        state.last_poll_ok = true;
        state.poll_successes = state.poll_successes.saturating_add(1);
        state.log.push(message);
    });
}

fn health_error(health: &'static HealthMutex, message: &'static str) {
    health.lock(|cell| {
        let mut state = cell.borrow_mut();
        state.last_poll_ok = false;
        state.poll_errors = state.poll_errors.saturating_add(1);
        state.log.push(message);
    });
}

fn set_wifi_ready(health: &'static HealthMutex) {
    health.lock(|cell| {
        let mut state = cell.borrow_mut();
        state.wifi_ready = true;
        state.log.push("wifi and dhcp ready");
    });
}

async fn run_healthz_server(
    stack: Stack<'static>,
    config: DeviceConfig,
    health: &'static HealthMutex,
) -> ! {
    let mut rx_buffer = [0_u8; 1536];
    let mut tx_buffer = [0_u8; 4096];
    let mut read_buffer = [0_u8; 512];

    loop {
        let mut socket = TcpSocket::new(stack, &mut rx_buffer, &mut tx_buffer);
        socket.set_timeout(Some(Duration::from_secs(10)));
        if socket.accept(config.onboard_port).await.is_err() {
            health_log(health, "healthz accept failed");
            Timer::after(Duration::from_secs(1)).await;
            continue;
        }
        health_log(health, "healthz accepted");

        let Ok(n) = socket.read(&mut read_buffer).await else {
            health_log(health, "healthz read failed");
            continue;
        };
        health_log(health, "healthz read ok");
        let request = match str::from_utf8(&read_buffer[..n]) {
            Ok(request) => request,
            Err(_) => {
                health_log(health, "healthz request utf8 failed");
                if send_onboard_response(
                    &mut socket,
                    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    health,
                    "healthz bad request",
                )
                .await
                .is_err()
                {
                    health_log(health, "healthz bad request send failed");
                }
                continue;
            }
        };
        if request.starts_with("GET /healthz ")
            || request.starts_with("GET /healthz?")
            || request.starts_with("GET /healthz HTTP/")
        {
            health_log(health, "healthz route matched");
            let mut body: String<3072> = String::new();
            build_healthz_body(&mut body, &config, stack, health);
            health_log(health, "healthz body built");
            let mut response: String<4096> = String::new();
            if write!(
                response,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .is_err()
            {
                health_log(health, "healthz response build failed");
                continue;
            }
            health_log(health, "healthz response built");
            match send_onboard_response(
                &mut socket,
                response.as_bytes(),
                health,
                "healthz response",
            )
            .await
            {
                Ok(()) => health_log(health, "healthz served"),
                Err(_) => health_log(health, "healthz serve failed"),
            }
        } else if request.starts_with("GET /logs ")
            || request.starts_with("GET /logs?")
            || request.starts_with("GET /logs HTTP/")
        {
            health_log(health, "logs route matched");
            let mut body: String<3072> = String::new();
            build_logs_body(&mut body, health);
            health_log(health, "logs body built");
            let mut response: String<4096> = String::new();
            if write!(
                response,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .is_err()
            {
                health_log(health, "logs response build failed");
                continue;
            }
            health_log(health, "logs response built");
            match send_onboard_response(&mut socket, response.as_bytes(), health, "logs response")
                .await
            {
                Ok(()) => health_log(health, "logs served"),
                Err(_) => health_log(health, "logs serve failed"),
            }
        } else {
            health_log(health, "healthz route not found");
            let response =
                b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
            if send_onboard_response(&mut socket, response, health, "healthz not found")
                .await
                .is_err()
            {
                health_log(health, "healthz not found send failed");
            }
        }
    }
}

async fn send_onboard_response(
    socket: &mut TcpSocket<'_>,
    response: &[u8],
    health: &'static HealthMutex,
    label: &'static str,
) -> Result<(), PollError> {
    health_log(health, label);
    health_log(health, "onboard write start");
    write_all(socket, response).await.map_err(|error| {
        health_log(health, "onboard write failed");
        error
    })?;
    health_log(health, "onboard flush start");
    socket.flush().await.map_err(|_| {
        health_log(health, "onboard flush failed");
        PollError::Write
    })?;
    health_log(health, "onboard close start");
    socket.close();
    health_log(health, "onboard close flush start");
    socket.flush().await.map_err(|_| {
        health_log(health, "onboard close flush failed");
        PollError::Write
    })?;
    health_log(health, "onboard close done");
    Ok(())
}

fn build_healthz_body<const N: usize>(
    out: &mut String<N>,
    config: &DeviceConfig,
    stack: Stack<'static>,
    health: &'static HealthMutex,
) {
    let local_ip = local_ipv4_string::<16>(stack);
    health.lock(|cell| {
        let state = cell.borrow();
        let logs = state.log.newest_first::<HEALTH_LOG_RETURNED>();
        let _ = write!(
            out,
            "{{\"ok\":true,\"service\":\"onboard-app\",\"hardware_backend\":\"pico2w\",\"time\":null,\"pid\":null,\"log_level\":\"INFO\",\"deployment\":{{\"zone_name\":\"{}\",\"hardware_profile\":\"{}\",\"send_behavior\":\"{}\",\"report_behavior\":\"sensor_readings\",\"sensor_driver\":\"{}\",\"ir_transport\":\"{}\",\"ir_device\":\"gp{}\",\"ir_protocol\":\"{}\"}},\"queues\":{{\"daikin_size\":0,\"daikin_capacity\":0}},\"log_storage\":{{\"path\":null,\"type\":\"memory\"}},\"pico\":{{\"uptime_seconds\":{},\"wifi_ready\":{},\"last_poll_ok\":{},\"poll_successes\":{},\"poll_errors\":{},\"ir_sends\":{},\"ir_stub_sends\":{}}},",
            config.zone_name,
            config.hardware_profile,
            config.send_behavior,
            config.sensor_driver,
            config.ir_transport,
            config.ir_tx_gpio,
            config.ir_protocol,
            Instant::now().as_secs(),
            json_bool(state.wifi_ready),
            json_bool(state.last_poll_ok),
            state.poll_successes,
            state.poll_errors,
            state.ir_sends,
            state.ir_sends
        );
        if let Some(local_ip) = local_ip.as_ref() {
            let _ = write!(
                out,
                "\"network\":{{\"local_ip\":\"{}\",\"onboard_url\":\"http://{}:{}\"}},",
                local_ip, local_ip, config.onboard_port
            );
        } else {
            let _ = out.push_str("\"network\":{},");
        }
        let _ = write!(
            out,
            "\"log_buffer\":{{\"capacity\":{},\"returned\":{},\"lines\":[",
            state.log.capacity(),
            state.log.len().min(HEALTH_LOG_RETURNED)
        );
        let mut first = true;
        for line in logs {
            if line.is_empty() {
                continue;
            }
            if !first {
                let _ = out.push(',');
            }
            first = false;
            write_json_string(out, line);
        }
        let _ = out.push_str("]}}");
    });
}

fn build_logs_body<const N: usize>(out: &mut String<N>, health: &'static HealthMutex) {
    health.lock(|cell| {
        let state = cell.borrow();
        let logs = state.log.newest_first::<HEALTH_LOG_RETURNED>();
        let _ = out.push_str("{\"lines\":[");
        write_log_array(out, logs);
        let _ = out.push_str("],\"path\":null}");
    });
}

fn local_ipv4_string<const N: usize>(stack: Stack<'static>) -> Option<String<N>> {
    let config = stack.config_v4()?;
    let octets = config.address.address().octets();
    let mut out: String<N> = String::new();
    write!(
        out,
        "{}.{}.{}.{}",
        octets[0], octets[1], octets[2], octets[3]
    )
    .ok()?;
    Some(out)
}

fn write_log_array<const N: usize, const L: usize>(out: &mut String<N>, logs: [&str; L]) {
    let mut first = true;
    for line in logs {
        if line.is_empty() {
            continue;
        }
        if !first {
            let _ = out.push(',');
        }
        first = false;
        write_json_string(out, line);
    }
}

fn json_bool(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

fn write_json_string<const N: usize>(out: &mut String<N>, value: &str) {
    let _ = out.push('"');
    for byte in value.as_bytes() {
        match *byte {
            b'"' => {
                let _ = out.push_str("\\\"");
            }
            b'\\' => {
                let _ = out.push_str("\\\\");
            }
            0x20..=0x7e => {
                let _ = out.push(char::from(*byte));
            }
            _ => {
                let _ = out.push('?');
            }
        }
    }
    let _ = out.push('"');
}
