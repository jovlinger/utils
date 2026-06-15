use crate::{DeviceConfig, HeatpumpCommand, SensorReading, StatusEvent};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Esp32s3Pins {
    pub aht20_scl_gpio: u8,
    pub aht20_sda_gpio: u8,
    pub ir_tx_gpio: u8,
    pub ir_rx_gpio: u8,
    pub aht20_addr: u8,
}

impl Esp32s3Pins {
    pub const fn plan_defaults() -> Self {
        Self {
            aht20_scl_gpio: 36,
            aht20_sda_gpio: 35,
            ir_tx_gpio: 17,
            ir_rx_gpio: 6,
            aht20_addr: 0x38,
        }
    }

    pub const fn from_config(config: &DeviceConfig) -> Self {
        Self {
            aht20_scl_gpio: config.i2c_scl_gpio,
            aht20_sda_gpio: config.i2c_sda_gpio,
            ir_tx_gpio: config.ir_tx_gpio,
            ir_rx_gpio: config.ir_rx_gpio,
            aht20_addr: config.aht20_addr,
        }
    }
}

impl Default for Esp32s3Pins {
    fn default() -> Self {
        Self::plan_defaults()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HardwareError {
    Sensor,
    IrTransmit,
    IrReceive,
    Status,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IrEdge {
    pub timestamp_us: u64,
    pub level_high: bool,
}

pub trait ThermoHardware {
    fn read_aht20(&mut self) -> Result<SensorReading, HardwareError>;
    fn send_midea_ir(&mut self, command: &HeatpumpCommand) -> Result<(), HardwareError>;
    fn send_raw_ir(&mut self, carrier_hz: u32, durations_us: &[i32]) -> Result<(), HardwareError>;
    fn record_ir_rx_edge(&mut self) -> Result<Option<IrEdge>, HardwareError>;
    fn set_status(&mut self, event: StatusEvent) -> Result<(), HardwareError>;
    fn monotonic_millis(&self) -> u64;
}
