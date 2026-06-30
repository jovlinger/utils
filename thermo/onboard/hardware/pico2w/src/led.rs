#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LedColor {
    Yellow,
    Blue,
    Green,
    Red,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StatusEvent {
    ReadingEnv,
    PollStarted,
    SendingIr,
    PollSucceeded,
    Error,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BlinkPattern {
    pub color: LedColor,
    pub pulses: u8,
}

impl BlinkPattern {
    pub const fn new(color: LedColor, pulses: u8) -> Self {
        Self { color, pulses }
    }
}

pub trait StatusLed {
    type Error;

    fn blink(&mut self, pattern: BlinkPattern) -> Result<(), Self::Error>;
}

pub fn pattern_for_event(event: StatusEvent) -> BlinkPattern {
    match event {
        StatusEvent::ReadingEnv => BlinkPattern::new(LedColor::Yellow, 3),
        StatusEvent::PollStarted => BlinkPattern::new(LedColor::Green, 1),
        StatusEvent::SendingIr => BlinkPattern::new(LedColor::Blue, 2),
        StatusEvent::PollSucceeded => BlinkPattern::new(LedColor::Green, 1),
        StatusEvent::Error => BlinkPattern::new(LedColor::Red, 4),
    }
}

pub fn signal_status<L>(led: &mut L, event: StatusEvent) -> Result<(), L::Error>
where
    L: StatusLed,
{
    led.blink(pattern_for_event(event))
}

#[cfg(test)]
mod tests {
    use super::{pattern_for_event, signal_status, BlinkPattern, LedColor, StatusEvent, StatusLed};

    #[derive(Default)]
    struct RecordingLed {
        patterns: [Option<BlinkPattern>; 4],
        len: usize,
    }

    impl StatusLed for RecordingLed {
        type Error = ();

        fn blink(&mut self, pattern: BlinkPattern) -> Result<(), Self::Error> {
            self.patterns[self.len] = Some(pattern);
            self.len += 1;
            Ok(())
        }
    }

    #[test]
    fn maps_status_events_to_requested_colors() {
        assert_eq!(
            pattern_for_event(StatusEvent::ReadingEnv),
            BlinkPattern::new(LedColor::Yellow, 3)
        );
        assert_eq!(
            pattern_for_event(StatusEvent::PollStarted),
            BlinkPattern::new(LedColor::Green, 1)
        );
        assert_eq!(
            pattern_for_event(StatusEvent::SendingIr),
            BlinkPattern::new(LedColor::Blue, 2)
        );
        assert_eq!(
            pattern_for_event(StatusEvent::PollSucceeded),
            BlinkPattern::new(LedColor::Green, 1)
        );
        assert_eq!(
            pattern_for_event(StatusEvent::Error),
            BlinkPattern::new(LedColor::Red, 4)
        );
    }

    #[test]
    fn sends_pattern_to_led_driver() {
        let mut led = RecordingLed::default();

        signal_status(&mut led, StatusEvent::SendingIr).unwrap();

        assert_eq!(led.len, 1);
        assert_eq!(led.patterns[0], Some(BlinkPattern::new(LedColor::Blue, 2)));
    }
}
