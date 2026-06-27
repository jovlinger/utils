//! AHT20 temperature/humidity sensor (I2C address 0x38).

pub const AHT20_DEFAULT_ADDR: u8 = 0x38;

const STATUS_BUSY: u8 = 0x80;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Aht20Error {
    I2cWrite,
    I2cRead,
    BusyTimeout,
    NotCalibrated,
    InvalidData,
}

/// Decode a 6-byte AHT20 measurement frame into humidity and temperature.
pub fn decode_measurement(data: [u8; 6]) -> Result<(f32, f32), Aht20Error> {
    if data[0] & STATUS_BUSY != 0 {
        return Err(Aht20Error::InvalidData);
    }
    let raw_humidity: u32 =
        ((u32::from(data[1]) << 12) | (u32::from(data[2]) << 4) | (u32::from(data[3]) >> 4))
            & 0xFFFFF;
    let raw_temperature: u32 =
        (((u32::from(data[3]) & 0x0F) << 16) | (u32::from(data[4]) << 8) | u32::from(data[5]))
            & 0xFFFFF;
    let humid_tenths: u32 = ((raw_humidity * 1000) + 524_288) / 1_048_576;
    let temp_tenths: i32 = (((raw_temperature * 2000) + 524_288) / 1_048_576) as i32 - 500;
    let humid_percent = humid_tenths as f32 / 10.0;
    let temp_centigrade = temp_tenths as f32 / 10.0;
    if !(0.0..=100.0).contains(&humid_percent) || !(-40.0..=85.0).contains(&temp_centigrade) {
        return Err(Aht20Error::InvalidData);
    }
    Ok((humid_percent, temp_centigrade))
}

#[cfg(feature = "firmware")]
mod driver {
    use super::{decode_measurement, Aht20Error, STATUS_BUSY};
    use crate::{AccurateSensor, SensorReading, SensorSource};
    use embassy_rp::gpio::OutputOpenDrain;
    use embassy_rp::i2c::{Error as I2cError, I2c, Instance, Mode};
    use embassy_time::{block_for, Duration};

    const CMD_INIT: [u8; 3] = [0xBE, 0x08, 0x00];
    const CMD_TRIGGER: [u8; 3] = [0xAC, 0x33, 0x00];
    const STATUS_CALIBRATED: u8 = 0x08;
    const SOFT_I2C_DELAY_US: u64 = 5;

    pub trait Aht20Bus {
        fn write(&mut self, addr: u8, bytes: &[u8]) -> Result<(), Aht20Error>;
        fn read(&mut self, addr: u8, bytes: &mut [u8]) -> Result<(), Aht20Error>;
    }

    pub struct Aht20<B> {
        bus: B,
        addr: u8,
        initialized: bool,
    }

    impl<B: Aht20Bus> Aht20<B> {
        pub fn new(bus: B, addr: u8) -> Self {
            Self {
                bus,
                addr,
                initialized: false,
            }
        }

        fn ensure_initialized(&mut self) -> Result<(), Aht20Error> {
            if self.initialized {
                return Ok(());
            }
            block_for(Duration::from_millis(40));
            let mut status = [0u8; 1];
            self.bus.read(self.addr, &mut status)?;
            if status[0] & STATUS_CALIBRATED == 0 {
                self.bus.write(self.addr, &CMD_INIT)?;
                block_for(Duration::from_millis(10));
                self.bus.read(self.addr, &mut status)?;
                if status[0] & STATUS_CALIBRATED == 0 {
                    return Err(Aht20Error::NotCalibrated);
                }
            }
            self.initialized = true;
            Ok(())
        }

        fn wait_not_busy(&mut self) -> Result<(), Aht20Error> {
            for _ in 0..20 {
                block_for(Duration::from_millis(5));
                let mut status = [0u8; 1];
                self.bus.read(self.addr, &mut status)?;
                if status[0] & STATUS_BUSY == 0 {
                    return Ok(());
                }
            }
            Err(Aht20Error::BusyTimeout)
        }

        pub fn read_raw(&mut self) -> Result<SensorReading, Aht20Error> {
            self.ensure_initialized()?;
            self.bus.write(self.addr, &CMD_TRIGGER)?;
            self.wait_not_busy()?;
            let mut data = [0u8; 6];
            self.bus.read(self.addr, &mut data)?;
            let (humid_percent, temp_centigrade) = decode_measurement(data)?;
            Ok(SensorReading {
                temp_centigrade,
                humid_percent,
                source: SensorSource::Aht20,
            })
        }
    }

    impl<B: Aht20Bus> AccurateSensor for Aht20<B> {
        type Error = Aht20Error;

        fn read(&mut self) -> Result<SensorReading, Self::Error> {
            self.read_raw()
        }
    }

    impl<'d, T: Instance, M: Mode> Aht20Bus for I2c<'d, T, M> {
        fn write(&mut self, addr: u8, bytes: &[u8]) -> Result<(), Aht20Error> {
            self.blocking_write(addr, bytes)
                .map_err(map_i2c_write_error)
        }

        fn read(&mut self, addr: u8, bytes: &mut [u8]) -> Result<(), Aht20Error> {
            self.blocking_read(addr, bytes).map_err(map_i2c_read_error)
        }
    }

    fn map_i2c_write_error(error: I2cError) -> Aht20Error {
        match error {
            I2cError::InvalidReadBufferLength => Aht20Error::I2cRead,
            I2cError::InvalidWriteBufferLength => Aht20Error::I2cWrite,
            I2cError::AddressOutOfRange(_) | I2cError::Abort(_) => Aht20Error::I2cWrite,
            _ => Aht20Error::I2cWrite,
        }
    }

    fn map_i2c_read_error(error: I2cError) -> Aht20Error {
        match error {
            I2cError::InvalidReadBufferLength => Aht20Error::I2cRead,
            I2cError::InvalidWriteBufferLength => Aht20Error::I2cWrite,
            I2cError::AddressOutOfRange(_) | I2cError::Abort(_) => Aht20Error::I2cRead,
            _ => Aht20Error::I2cRead,
        }
    }

    pub struct SoftI2c<'d> {
        sda: OutputOpenDrain<'d>,
        scl: OutputOpenDrain<'d>,
    }

    impl<'d> SoftI2c<'d> {
        pub fn new(mut sda: OutputOpenDrain<'d>, mut scl: OutputOpenDrain<'d>) -> Self {
            sda.set_pullup(true);
            scl.set_pullup(true);
            sda.set_high();
            scl.set_high();
            Self { sda, scl }
        }

        fn delay(&self) {
            block_for(Duration::from_micros(SOFT_I2C_DELAY_US));
        }

        fn start(&mut self) {
            self.sda.set_high();
            self.scl.set_high();
            self.delay();
            self.sda.set_low();
            self.delay();
            self.scl.set_low();
            self.delay();
        }

        fn stop(&mut self) {
            self.sda.set_low();
            self.delay();
            self.scl.set_high();
            self.delay();
            self.sda.set_high();
            self.delay();
        }

        fn write_byte(&mut self, byte: u8) -> bool {
            for bit in (0..8).rev() {
                if byte & (1 << bit) == 0 {
                    self.sda.set_low();
                } else {
                    self.sda.set_high();
                }
                self.delay();
                self.scl.set_high();
                self.delay();
                self.scl.set_low();
                self.delay();
            }
            self.sda.set_high();
            self.delay();
            self.scl.set_high();
            self.delay();
            let ack = self.sda.is_low();
            self.scl.set_low();
            self.delay();
            ack
        }

        fn read_byte(&mut self, ack: bool) -> u8 {
            let mut byte: u8 = 0;
            self.sda.set_high();
            for _ in 0..8 {
                byte <<= 1;
                self.delay();
                self.scl.set_high();
                self.delay();
                if self.sda.is_high() {
                    byte |= 1;
                }
                self.scl.set_low();
                self.delay();
            }
            if ack {
                self.sda.set_low();
            } else {
                self.sda.set_high();
            }
            self.delay();
            self.scl.set_high();
            self.delay();
            self.scl.set_low();
            self.sda.set_high();
            self.delay();
            byte
        }
    }

    impl Aht20Bus for SoftI2c<'_> {
        fn write(&mut self, addr: u8, bytes: &[u8]) -> Result<(), Aht20Error> {
            self.start();
            if !self.write_byte(addr << 1) {
                self.stop();
                return Err(Aht20Error::I2cWrite);
            }
            for byte in bytes {
                if !self.write_byte(*byte) {
                    self.stop();
                    return Err(Aht20Error::I2cWrite);
                }
            }
            self.stop();
            Ok(())
        }

        fn read(&mut self, addr: u8, bytes: &mut [u8]) -> Result<(), Aht20Error> {
            self.start();
            if !self.write_byte((addr << 1) | 1) {
                self.stop();
                return Err(Aht20Error::I2cRead);
            }
            let last = bytes.len().saturating_sub(1);
            for (index, byte) in bytes.iter_mut().enumerate() {
                *byte = self.read_byte(index != last);
            }
            self.stop();
            Ok(())
        }
    }
}

#[cfg(feature = "firmware")]
pub use driver::{Aht20, SoftI2c};

#[cfg(test)]
mod tests {
    use super::{decode_measurement, Aht20Error};

    #[test]
    fn decodes_reference_measurement_frame() {
        // humidity ~ 50.0 %, temperature ~ 21.0 C
        let data: [u8; 6] = [0x18, 0x80, 0x00, 0x05, 0xAE, 0x14];
        let (humid_percent, temp_centigrade) =
            decode_measurement(data).expect("decode_measurement failed");
        assert_eq!(humid_percent, 50.0);
        assert_eq!(temp_centigrade, 21.0);
    }

    #[test]
    fn rejects_busy_status_byte() {
        let data: [u8; 6] = [0x98, 0x80, 0x00, 0x05, 0xAE, 0x14];
        assert_eq!(decode_measurement(data), Err(Aht20Error::InvalidData));
    }
}
