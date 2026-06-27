#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SensorReading {
    pub temp_centigrade: f32,
    pub humid_percent: f32,
    pub source: SensorSource,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensorSource {
    Aht20,
    Fallback,
}

pub const FALLBACK_SENSOR_READING: SensorReading = SensorReading {
    temp_centigrade: 21.0,
    humid_percent: 50.0,
    source: SensorSource::Fallback,
};

pub trait AccurateSensor {
    type Error;

    fn read(&mut self) -> Result<SensorReading, Self::Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensorReadFailure<E> {
    RequiredSensorMissing(E),
}

pub fn read_sensors_or_fallback<S>(
    sensor: &mut S,
    sensor_required_at_boot: bool,
) -> Result<SensorReading, SensorReadFailure<S::Error>>
where
    S: AccurateSensor,
{
    match sensor.read() {
        Ok(mut reading) => {
            reading.source = SensorSource::Aht20;
            Ok(reading)
        }
        Err(error) if sensor_required_at_boot => {
            Err(SensorReadFailure::RequiredSensorMissing(error))
        }
        Err(_) => Ok(FALLBACK_SENSOR_READING),
    }
}

#[cfg(test)]
mod tests {
    use super::{
        read_sensors_or_fallback, AccurateSensor, SensorReadFailure, SensorReading, SensorSource,
        FALLBACK_SENSOR_READING,
    };

    struct MockSensor {
        reading: Result<SensorReading, MockSensorError>,
    }

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum MockSensorError {
        Missing,
    }

    impl AccurateSensor for MockSensor {
        type Error = MockSensorError;

        fn read(&mut self) -> Result<SensorReading, Self::Error> {
            self.reading
        }
    }

    #[test]
    fn returns_accurate_sensor_reading_when_available() {
        let mut sensor = MockSensor {
            reading: Ok(SensorReading {
                temp_centigrade: 22.5,
                humid_percent: 41.0,
                source: SensorSource::Fallback,
            }),
        };

        let reading: SensorReading = read_sensors_or_fallback(&mut sensor, false).unwrap();

        assert_eq!(reading.temp_centigrade, 22.5);
        assert_eq!(reading.humid_percent, 41.0);
        assert_eq!(reading.source, SensorSource::Aht20);
    }

    #[test]
    fn falls_back_when_sensor_is_missing_and_not_required() {
        let mut sensor = MockSensor {
            reading: Err(MockSensorError::Missing),
        };

        let reading: SensorReading = read_sensors_or_fallback(&mut sensor, false).unwrap();

        assert_eq!(reading, FALLBACK_SENSOR_READING);
    }

    #[test]
    fn fails_when_sensor_is_missing_and_required() {
        let mut sensor = MockSensor {
            reading: Err(MockSensorError::Missing),
        };

        let result = read_sensors_or_fallback(&mut sensor, true);

        assert_eq!(
            result,
            Err(SensorReadFailure::RequiredSensorMissing(
                MockSensorError::Missing
            ))
        );
    }
}
