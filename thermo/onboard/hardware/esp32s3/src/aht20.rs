//! AHT20 temperature/humidity sensor helpers for ESP32-S3 bring-up.

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

#[cfg(test)]
mod tests {
    use super::{decode_measurement, Aht20Error};

    #[test]
    fn decodes_reference_measurement_frame() {
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
