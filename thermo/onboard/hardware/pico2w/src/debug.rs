//! Shared hardware debug command protocol for USB/serial bring-up.
//!
//! Line-oriented ASCII commands for GPIO continuity checks and IR RX capture.

use core::fmt::Write;

use crate::config::DeviceConfig;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NamedPin {
    pub name: &'static str,
    pub gpio: u8,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DebugCommand {
    Help,
    Pins,
    GpioSet { pin: u8, high: bool },
    GpioRead { pin: u8 },
    IrPromisc { enable: bool },
    Empty,
    Unknown,
}

pub fn hat_named_pins(config: &DeviceConfig) -> [NamedPin; 4] {
    [
        NamedPin {
            name: "aht20_scl",
            gpio: config.i2c_scl_gpio,
        },
        NamedPin {
            name: "aht20_sda",
            gpio: config.i2c_sda_gpio,
        },
        NamedPin {
            name: "ir_tx",
            gpio: config.ir_tx_gpio,
        },
        NamedPin {
            name: "ir_rx",
            gpio: config.ir_rx_gpio,
        },
    ]
}

pub fn parse_debug_line(line: &str) -> DebugCommand {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return DebugCommand::Empty;
    }
    let lower = to_lower_ascii(trimmed);
    if lower == "help" || lower == "?" {
        return DebugCommand::Help;
    }
    if lower == "pins" {
        return DebugCommand::Pins;
    }
    let mut parts = lower.split_whitespace();
    let head = parts.next().unwrap_or("");
    if head == "gpio" {
        return parse_gpio_command(parts);
    }
    if head == "ir" {
        return parse_ir_command(parts);
    }
    DebugCommand::Unknown
}

fn parse_gpio_command<'a, I>(mut parts: I) -> DebugCommand
where
    I: Iterator<Item = &'a str>,
{
    match parts.next() {
        Some("set") => {
            let pin = match parts.next().and_then(parse_u8) {
                Some(pin) => pin,
                None => return DebugCommand::Unknown,
            };
            let high = match parts.next() {
                Some("hi") | Some("high") | Some("1") => true,
                Some("lo") | Some("low") | Some("0") => false,
                _ => return DebugCommand::Unknown,
            };
            if parts.next().is_some() {
                return DebugCommand::Unknown;
            }
            DebugCommand::GpioSet { pin, high }
        }
        Some("read") => {
            let pin = match parts.next().and_then(parse_u8) {
                Some(pin) => pin,
                None => return DebugCommand::Unknown,
            };
            if parts.next().is_some() {
                return DebugCommand::Unknown;
            }
            DebugCommand::GpioRead { pin }
        }
        _ => DebugCommand::Unknown,
    }
}

fn parse_ir_command<'a, I>(mut parts: I) -> DebugCommand
where
    I: Iterator<Item = &'a str>,
{
    if parts.next() != Some("promisc") {
        return DebugCommand::Unknown;
    }
    let enable = match parts.next() {
        Some("on") | Some("1") => true,
        Some("off") | Some("0") => false,
        _ => return DebugCommand::Unknown,
    };
    if parts.next().is_some() {
        return DebugCommand::Unknown;
    }
    DebugCommand::IrPromisc { enable }
}

fn parse_u8(token: &str) -> Option<u8> {
    let mut value: u32 = 0;
    for byte in token.bytes() {
        if !byte.is_ascii_digit() {
            return None;
        }
        value = value
            .checked_mul(10)?
            .checked_add(u32::from(byte - b'0'))?;
    }
    u8::try_from(value).ok()
}

fn to_lower_ascii(input: &str) -> heapless::String<128> {
    let mut out: heapless::String<128> = heapless::String::new();
    for byte in input.bytes() {
        let ch = if byte.is_ascii_uppercase() {
            (byte + 32) as char
        } else {
            byte as char
        };
        let _ = out.push(ch);
    }
    out
}

pub fn write_help(out: &mut dyn Write) {
    let _ = writeln!(out, "Thermo hardware debug commands:");
    let _ = writeln!(out, "  help");
    let _ = writeln!(out, "  pins");
    let _ = writeln!(out, "  gpio set <pin> hi|lo");
    let _ = writeln!(out, "  gpio read <pin>");
    let _ = writeln!(out, "  ir promisc on|off");
    let _ = writeln!(
        out,
        "HAT continuity: short the net to 3V3, then gpio read <pin>."
    );
    let _ = writeln!(
        out,
        "IR test: ir promisc on, then trigger IR TX; edges stream as lines."
    );
}

pub fn write_pins(config: &DeviceConfig, out: &mut dyn Write) {
    for entry in hat_named_pins(config) {
        let _ = writeln!(out, "{} gp{}", entry.name, entry.gpio);
    }
}

pub fn write_ok(out: &mut dyn Write, message: &str) {
    let _ = writeln!(out, "OK {}", message);
}

pub fn write_err(out: &mut dyn Write, message: &str) {
    let _ = writeln!(out, "ERR {}", message);
}

pub fn write_gpio_read(out: &mut dyn Write, pin: u8, high: bool) {
    let level = if high { "hi" } else { "lo" };
    let _ = writeln!(out, "gpio {} {}", pin, level);
}

pub fn write_gpio_set(out: &mut dyn Write, pin: u8, high: bool) {
    let level = if high { "hi" } else { "lo" };
    let _ = writeln!(out, "gpio {} set {}", pin, level);
}

pub fn write_ir_edge(out: &mut dyn Write, timestamp_us: u64, high: bool) {
    let level = if high { "hi" } else { "lo" };
    let _ = writeln!(out, "ir edge {} us {}", timestamp_us, level);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_help_and_pins() {
        assert_eq!(parse_debug_line("help"), DebugCommand::Help);
        assert_eq!(parse_debug_line("  ?  "), DebugCommand::Help);
        assert_eq!(parse_debug_line("pins"), DebugCommand::Pins);
        assert_eq!(parse_debug_line(""), DebugCommand::Empty);
    }

    #[test]
    fn parse_gpio_commands() {
        assert_eq!(
            parse_debug_line("gpio set 27 hi"),
            DebugCommand::GpioSet {
                pin: 27,
                high: true
            }
        );
        assert_eq!(
            parse_debug_line("GPIO SET 13 LO"),
            DebugCommand::GpioSet {
                pin: 13,
                high: false
            }
        );
        assert_eq!(
            parse_debug_line("gpio read 28"),
            DebugCommand::GpioRead { pin: 28 }
        );
        assert_eq!(parse_debug_line("gpio set 99"), DebugCommand::Unknown);
    }

    #[test]
    fn parse_ir_promisc() {
        assert_eq!(
            parse_debug_line("ir promisc on"),
            DebugCommand::IrPromisc { enable: true }
        );
        assert_eq!(
            parse_debug_line("IR PROMISC OFF"),
            DebugCommand::IrPromisc { enable: false }
        );
    }

    #[test]
    fn parse_unknown_command() {
        assert_eq!(parse_debug_line("gpio set 99"), DebugCommand::Unknown);
        assert_eq!(parse_debug_line("nope"), DebugCommand::Unknown);
    }
}
