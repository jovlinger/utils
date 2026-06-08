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
    use embassy_rp::i2c::{Error as I2cError, I2c, Instance, Mode};
    use embassy_time::{block_for, Duration};

    const CMD_INIT: [u8; 3] = [0xBE, 0x08, 0x00];
    const CMD_TRIGGER: [u8; 3] = [0xAC, 0x33, 0x00];
    const STATUS_CALIBRATED: u8 = 0x08;

    pub struct Aht20<'d, T: Instance, M: Mode> {
        i2c: I2c<'d, T, M>,
        addr: u8,
        initialized: bool,
    }

    impl<'d, T: Instance, M: Mode> Aht20<'d, T, M> {
        pub fn new(i2c: I2c<'d, T, M>, addr: u8) -> Self {
            Self {
                i2c,
                addr,
                initialized: false,
            }
        }

        fn map_i2c_error(error: I2cError) -> Aht20Error {
            match error {
                I2cError::InvalidReadBufferLength | I2cError::InvalidWriteBufferLength => {
                    Aht20Error::I2cRead
                }
                I2cError::AddressOutOfRange(_) => Aht20Error::I2cWrite,
                I2cError::Abort(_) => Aht20Error::I2cWrite,
                _ => Aht20Error::I2cWrite,
            }
        }

        fn ensure_initialized(&mut self) -> Result<(), Aht20Error> {
            if self.initialized {
                return Ok(());
            }
            block_for(Duration::from_millis(40));
            let mut status = [0u8; 1];
            self.i2c
                .blocking_read(self.addr, &mut status)
                .map_err(Self::map_i2c_error)?;
            if status[0] & STATUS_CALIBRATED == 0 {
                self.i2c
                    .blocking_write(self.addr, &CMD_INIT)
                    .map_err(Self::map_i2c_error)?;
                block_for(Duration::from_millis(10));
                self.i2c
                    .blocking_read(self.addr, &mut status)
                    .map_err(Self::map_i2c_error)?;
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
                self.i2c
                    .blocking_read(self.addr, &mut status)
                    .map_err(Self::map_i2c_error)?;
                if status[0] & STATUS_BUSY == 0 {
                    return Ok(());
                }
            }
            Err(Aht20Error::BusyTimeout)
        }

        pub fn read_raw(&mut self) -> Result<SensorReading, Aht20Error> {
            self.ensure_initialized()?;
            self.i2c
                .blocking_write(self.addr, &CMD_TRIGGER)
                .map_err(Self::map_i2c_error)?;
            self.wait_not_busy()?;
            let mut data = [0u8; 6];
            self.i2c
                .blocking_read(self.addr, &mut data)
                .map_err(Self::map_i2c_error)?;
            let (humid_percent, temp_centigrade) = decode_measurement(data)?;
            Ok(SensorReading {
                temp_centigrade,
                humid_percent,
                source: SensorSource::Aht20,
            })
        }
    }

    impl<'d, T: Instance> AccurateSensor for Aht20<'d, T, embassy_rp::i2c::Blocking> {
        type Error = Aht20Error;

        fn read(&mut self) -> Result<SensorReading, Self::Error> {
            self.read_raw()
        }
    }
}

#[cfg(feature = "firmware")]
pub use driver::Aht20;

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
