#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HeatpumpMode {
    Auto,
    Dry,
    Cool,
    Heat,
    Fan,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HeatpumpFan {
    F1,
    F2,
    F3,
    F4,
    F5,
    Auto,
    Silent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HeatpumpCommand {
    pub power: bool,
    pub mode: HeatpumpMode,
    pub half_c: i16,
    pub fan: HeatpumpFan,
}

impl HeatpumpCommand {
    pub const fn default() -> Self {
        Self {
            power: false,
            mode: HeatpumpMode::Auto,
            half_c: 40,
            fan: HeatpumpFan::Auto,
        }
    }
}

pub const MIDEA_START_PULSE_US: u64 = 4_500;
pub const MIDEA_START_SPACE_US: u64 = 4_500;
pub const MIDEA_PULSE_US: u64 = 560;
pub const MIDEA_SPACE_ZERO_US: u64 = 560;
pub const MIDEA_SPACE_ONE_US: u64 = 1_680;
pub const MIDEA_GAP_US: u64 = 5_200;
pub const RAW_IR_COMMAND_TYPE: &str = "raw_ir_sequence";
pub const RAW_IR_CARRIER_HZ: i32 = 38_000;
pub const RAW_IR_MAX_SEQUENCE_LEN: usize = 1024;
pub const RAW_IR_MAX_DURATION_US: i32 = 1_250_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MideaClassicFrames {
    pub frames: [[u8; 6]; 3],
    pub count: usize,
}

pub fn is_raw_ir_command(command_json: &str) -> bool {
    json_string(command_json, "command_type") == Some(RAW_IR_COMMAND_TYPE)
}

pub fn for_each_raw_ir_duration<F>(command_json: &str, f: F) -> Option<usize>
where
    F: FnMut(i32),
{
    if !is_raw_ir_command(command_json) {
        return None;
    }
    if let Some(carrier_hz) = json_i32(command_json, "carrier_hz") {
        if carrier_hz != RAW_IR_CARRIER_HZ {
            return None;
        }
    } else if json_value_after_key(command_json, "carrier_hz").is_some() {
        return None;
    }
    let sequence = json_value_after_key(command_json, "sequence")?;
    parse_raw_ir_sequence(sequence, f)
}

pub fn parse_heatpump_command(command_json: &str) -> Option<HeatpumpCommand> {
    let mut command = HeatpumpCommand::default();
    if let Some(power) = json_bool(command_json, "power") {
        command.power = power;
    }
    if let Some(mode) = json_string(command_json, "mode").and_then(parse_mode) {
        command.mode = mode;
    }
    if let Some(temp_c) = json_number_rounded(command_json, "temp_c") {
        command.half_c = temp_c.saturating_mul(2);
    } else if let Some(half_c) = json_number_rounded(command_json, "half_c") {
        command.half_c = half_c;
    }
    if let Some(fan) = json_string(command_json, "fan").and_then(parse_fan) {
        command.fan = fan;
    }
    Some(command)
}

pub fn midea_classic_frame(command: HeatpumpCommand) -> [u8; 6] {
    let data = midea_state_bytes(command);
    [data[0], !data[0], data[1], !data[1], data[2], !data[2]]
}

pub fn midea_classic_frames(command: HeatpumpCommand) -> MideaClassicFrames {
    let data = midea_state_bytes(command);
    let state_frame = [data[0], !data[0], data[1], !data[1], data[2], !data[2]];
    let count = if command.power { 3 } else { 2 };
    MideaClassicFrames {
        frames: [state_frame, state_frame, midea_office_secondary_frame(data)],
        count,
    }
}

fn midea_state_bytes(command: HeatpumpCommand) -> [u8; 3] {
    let mut fan_nibble = match command.fan {
        HeatpumpFan::F1 | HeatpumpFan::F2 | HeatpumpFan::Silent => 0x9,
        HeatpumpFan::F3 => 0x5,
        HeatpumpFan::F4 | HeatpumpFan::F5 => 0x3,
        HeatpumpFan::Auto => 0xB,
    };
    let state_nibble = if command.power { 0xF } else { 0xB };
    let mode_nibble = match command.mode {
        HeatpumpMode::Auto => 0x8,
        HeatpumpMode::Cool => 0x0,
        HeatpumpMode::Dry | HeatpumpMode::Fan => 0x4,
        HeatpumpMode::Heat => 0xC,
    };
    let temp_c = (command.half_c / 2).clamp(17, 30);
    let mut temp_nibble = midea_temp_nibble(temp_c);
    if !command.power {
        fan_nibble = 0x7;
        temp_nibble = 0xE;
    }
    [
        0xB2,
        ((fan_nibble << 4) | state_nibble) as u8,
        ((temp_nibble << 4) | mode_nibble) as u8,
    ]
}

fn midea_office_secondary_frame(data: [u8; 3]) -> [u8; 6] {
    let fan_code: u8 = match data[1] >> 4 {
        0x1 => 0x65,
        0x3 => 0x64,
        0x5 => 0x3C,
        0x9 => 0x28,
        0xB => 0x66,
        _ => 0x28,
    };
    let temp_flag: u8 = if data[2] >> 4 == 0x6 { 0x20 } else { 0x00 };
    let mut frame = [0xD5, fan_code, temp_flag, 0x01, 0x00, 0x00];
    frame[5] = frame[0]
        .wrapping_add(frame[1])
        .wrapping_add(frame[2])
        .wrapping_add(frame[3])
        .wrapping_add(frame[4]);
    frame
}

fn midea_temp_nibble(temp_c: i16) -> u8 {
    match temp_c {
        17 => 0x0,
        18 => 0x1,
        19 => 0x3,
        20 => 0x2,
        21 => 0x6,
        22 => 0x7,
        23 => 0x5,
        24 => 0x4,
        25 => 0xC,
        26 => 0xD,
        27 => 0x9,
        28 => 0x8,
        29 => 0xA,
        _ => 0xB,
    }
}

fn parse_mode(value: &str) -> Option<HeatpumpMode> {
    if ascii_eq_ignore_case(value, "AUTO") {
        Some(HeatpumpMode::Auto)
    } else if ascii_eq_ignore_case(value, "DRY") {
        Some(HeatpumpMode::Dry)
    } else if ascii_eq_ignore_case(value, "COOL") {
        Some(HeatpumpMode::Cool)
    } else if ascii_eq_ignore_case(value, "HEAT") {
        Some(HeatpumpMode::Heat)
    } else if ascii_eq_ignore_case(value, "FAN") {
        Some(HeatpumpMode::Fan)
    } else {
        None
    }
}

fn parse_fan(value: &str) -> Option<HeatpumpFan> {
    if ascii_eq_ignore_case(value, "F1") {
        Some(HeatpumpFan::F1)
    } else if ascii_eq_ignore_case(value, "F2") {
        Some(HeatpumpFan::F2)
    } else if ascii_eq_ignore_case(value, "F3") {
        Some(HeatpumpFan::F3)
    } else if ascii_eq_ignore_case(value, "F4") {
        Some(HeatpumpFan::F4)
    } else if ascii_eq_ignore_case(value, "F5") {
        Some(HeatpumpFan::F5)
    } else if ascii_eq_ignore_case(value, "AUTO") {
        Some(HeatpumpFan::Auto)
    } else if ascii_eq_ignore_case(value, "SILENT") {
        Some(HeatpumpFan::Silent)
    } else {
        None
    }
}

fn ascii_eq_ignore_case(left: &str, right: &str) -> bool {
    left.len() == right.len()
        && left
            .bytes()
            .zip(right.bytes())
            .all(|(a, b)| a.eq_ignore_ascii_case(&b))
}

fn parse_raw_ir_sequence<F>(value: &str, mut f: F) -> Option<usize>
where
    F: FnMut(i32),
{
    let bytes = value.as_bytes();
    if bytes.first() != Some(&b'[') {
        return None;
    }
    let mut index = 1;
    let mut count = 0;
    loop {
        skip_ascii_ws(bytes, &mut index);
        if bytes.get(index) == Some(&b']') {
            return if count == 0 { None } else { Some(count) };
        }
        if count >= RAW_IR_MAX_SEQUENCE_LEN {
            return None;
        }

        let mut sign: i32 = 1;
        if bytes.get(index) == Some(&b'-') {
            sign = -1;
            index += 1;
        }
        let mut value: i32 = 0;
        let mut saw_digit = false;
        while let Some(byte) = bytes.get(index) {
            if !byte.is_ascii_digit() {
                break;
            }
            saw_digit = true;
            value = value.checked_mul(10)?.checked_add(i32::from(byte - b'0'))?;
            index += 1;
        }
        if !saw_digit {
            return None;
        }
        let duration = value.checked_mul(sign)?;
        if duration == 0 || value > RAW_IR_MAX_DURATION_US {
            return None;
        }
        f(duration);
        count += 1;

        skip_ascii_ws(bytes, &mut index);
        match bytes.get(index) {
            Some(b',') => index += 1,
            Some(b']') => return Some(count),
            _ => return None,
        }
    }
}

fn skip_ascii_ws(bytes: &[u8], index: &mut usize) {
    while bytes
        .get(*index)
        .is_some_and(|byte| byte.is_ascii_whitespace())
    {
        *index += 1;
    }
}

fn json_bool(body: &str, key: &str) -> Option<bool> {
    let value = json_value_after_key(body, key)?;
    if value.starts_with("true") || value.starts_with("\"true\"") {
        Some(true)
    } else if value.starts_with("false") || value.starts_with("\"false\"") {
        Some(false)
    } else {
        None
    }
}

fn json_i32(body: &str, key: &str) -> Option<i32> {
    let value = json_value_after_key(body, key)?;
    let bytes = value.as_bytes();
    let mut index = 0;
    let mut sign: i32 = 1;
    if bytes.get(index) == Some(&b'-') {
        sign = -1;
        index += 1;
    }
    let mut out: i32 = 0;
    let mut saw_digit = false;
    while let Some(byte) = bytes.get(index) {
        if !byte.is_ascii_digit() {
            break;
        }
        saw_digit = true;
        out = out.checked_mul(10)?.checked_add(i32::from(byte - b'0'))?;
        index += 1;
    }
    if !saw_digit {
        return None;
    }
    if bytes
        .get(index)
        .is_some_and(|byte| byte.is_ascii_alphanumeric() || *byte == b'.' || *byte == b'-')
    {
        return None;
    }
    out.checked_mul(sign)
}

fn json_string<'a>(body: &'a str, key: &str) -> Option<&'a str> {
    let value = json_value_after_key(body, key)?;
    let value = value.strip_prefix('"')?;
    let end = value.find('"')?;
    Some(&value[..end])
}

fn json_number_rounded(body: &str, key: &str) -> Option<i16> {
    let value = json_value_after_key(body, key)?;
    let value = value.strip_prefix('"').unwrap_or(value);
    let mut sign: i16 = 1;
    let mut value = value;
    if let Some(rest) = value.strip_prefix('-') {
        sign = -1;
        value = rest;
    }
    let mut whole: i16 = 0;
    let mut saw_digit = false;
    for byte in value.bytes() {
        if !byte.is_ascii_digit() {
            break;
        }
        saw_digit = true;
        whole = whole.checked_mul(10)?.checked_add(i16::from(byte - b'0'))?;
    }
    if !saw_digit {
        return None;
    }
    let after_whole = &value[value.bytes().take_while(u8::is_ascii_digit).count()..];
    if let Some(fraction) = after_whole.strip_prefix('.') {
        if fraction
            .as_bytes()
            .first()
            .is_some_and(|digit| *digit >= b'5' && *digit <= b'9')
        {
            whole = whole.checked_add(1)?;
        }
    }
    whole.checked_mul(sign)
}

fn json_value_after_key<'a>(body: &'a str, key: &str) -> Option<&'a str> {
    let key_pos = find_json_key(body, key)?;
    let after_key = &body[key_pos + key.len() + 2..];
    let colon_pos = after_key.find(':')?;
    Some(after_key[colon_pos + 1..].trim_start())
}

fn find_json_key(body: &str, key: &str) -> Option<usize> {
    let needle_len = key.len() + 2;
    for (index, _) in body.match_indices('"') {
        let tail = &body[index..];
        if tail.len() < needle_len || !tail.starts_with('"') {
            continue;
        }
        let name_start = index + 1;
        let name_end = name_start + key.len();
        if body.get(name_start..name_end) == Some(key)
            && body.as_bytes().get(name_end) == Some(&b'"')
        {
            return Some(index);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::{
        for_each_raw_ir_duration, midea_classic_frame, midea_classic_frames,
        parse_heatpump_command, HeatpumpCommand, HeatpumpFan, HeatpumpMode,
    };

    #[test]
    fn parses_office_cool_on_command() {
        let command = parse_heatpump_command(
            "{\"power\":true,\"mode\":\"COOL\",\"temp_c\":20.0,\"fan\":\"F4\"}",
        )
        .unwrap();

        assert_eq!(
            command,
            HeatpumpCommand {
                power: true,
                mode: HeatpumpMode::Cool,
                half_c: 40,
                fan: HeatpumpFan::F4,
            }
        );
    }

    #[test]
    fn encodes_office_cool_on_midea_frame() {
        let command = HeatpumpCommand {
            power: true,
            mode: HeatpumpMode::Cool,
            half_c: 40,
            fan: HeatpumpFan::F4,
        };

        assert_eq!(
            midea_classic_frame(command),
            [0xB2, 0x4D, 0x3F, 0xC0, 0x20, 0xDF]
        );
    }

    #[test]
    fn encodes_office_cool_off_midea_frame() {
        let command = HeatpumpCommand {
            power: false,
            mode: HeatpumpMode::Cool,
            half_c: 40,
            fan: HeatpumpFan::F4,
        };

        assert_eq!(
            midea_classic_frame(command),
            [0xB2, 0x4D, 0x7B, 0x84, 0xE0, 0x1F]
        );
    }

    #[test]
    fn encodes_office_cool_on_midea_sequence_with_secondary_frame() {
        let command = HeatpumpCommand {
            power: true,
            mode: HeatpumpMode::Cool,
            half_c: 44,
            fan: HeatpumpFan::F1,
        };

        assert_eq!(
            midea_classic_frames(command),
            super::MideaClassicFrames {
                frames: [
                    [0xB2, 0x4D, 0x9F, 0x60, 0x70, 0x8F],
                    [0xB2, 0x4D, 0x9F, 0x60, 0x70, 0x8F],
                    [0xD5, 0x28, 0x00, 0x01, 0x00, 0xFE],
                ],
                count: 3,
            }
        );
    }

    #[test]
    fn encodes_office_power_off_without_secondary_frame() {
        let command = HeatpumpCommand {
            power: false,
            mode: HeatpumpMode::Cool,
            half_c: 44,
            fan: HeatpumpFan::F1,
        };

        assert_eq!(
            midea_classic_frames(command),
            super::MideaClassicFrames {
                frames: [
                    [0xB2, 0x4D, 0x7B, 0x84, 0xE0, 0x1F],
                    [0xB2, 0x4D, 0x7B, 0x84, 0xE0, 0x1F],
                    [0xD5, 0x28, 0x00, 0x01, 0x00, 0xFE],
                ],
                count: 2,
            }
        );
    }

    #[test]
    fn parses_raw_ir_sequence_command() {
        let mut durations = Vec::new();
        let count = for_each_raw_ir_duration(
            "{\"command_type\":\"raw_ir_sequence\",\"sequence\":[4500,-4500,560,-1600],\"carrier_hz\":38000}",
            |duration| durations.push(duration),
        )
        .unwrap();

        assert_eq!(count, 4);
        assert_eq!(durations, [4500, -4500, 560, -1600]);
    }

    #[test]
    fn rejects_raw_ir_sequence_with_wrong_carrier() {
        assert_eq!(
            for_each_raw_ir_duration(
                "{\"command_type\":\"raw_ir_sequence\",\"sequence\":[4500,-4500],\"carrier_hz\":36000}",
                |_| {},
            ),
            None
        );
    }

    #[test]
    fn rejects_raw_ir_sequence_with_zero_duration() {
        assert_eq!(
            for_each_raw_ir_duration(
                "{\"command_type\":\"raw_ir_sequence\",\"sequence\":[4500,0,-4500]}",
                |_| {},
            ),
            None
        );
    }
}
