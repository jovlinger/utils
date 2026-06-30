use core::fmt::Write;

use heapless::String;

use crate::{DeviceConfig, SensorReading};

pub fn command_is_new(last_applied_created_dt: &str, response_created_dt: Option<&str>) -> bool {
    match response_created_dt {
        Some(created_dt) => !created_dt.is_empty() && created_dt > last_applied_created_dt,
        None => false,
    }
}

pub fn build_sensor_post_body<const N: usize>(
    config: &DeviceConfig,
    reading: SensorReading,
    last_applied_command_json: Option<&str>,
    log_lines: &[&str],
    local_ip: Option<&str>,
) -> Result<String<N>, core::fmt::Error> {
    let mut body: String<N> = String::new();
    write!(
        body,
        "{{\"sensors\":{{\"temp_centigrade\":{:.1},\"humid_percent\":{:.1}}}",
        reading.temp_centigrade, reading.humid_percent
    )?;
    if let Some(command_json) = last_applied_command_json {
        if !command_json.is_empty() {
            write!(body, ",\"command\":{}", command_json)?;
        }
    }
    if let Some(local_ip) = local_ip {
        if !local_ip.is_empty() {
            write!(
                body,
                ",\"network\":{{\"local_ip\":\"{}\",\"onboard_url\":\"http://{}:{}\"}}",
                local_ip, local_ip, config.onboard_port
            )?;
        }
    }
    if !log_lines.is_empty() {
        write!(body, ",\"logs\":{{\"lines\":[")?;
        let mut first = true;
        for line in log_lines {
            if line.is_empty() {
                continue;
            }
            if !first {
                write!(body, ",")?;
            }
            first = false;
            write_json_string(&mut body, line)?;
        }
        write!(body, "]}}")?;
    }
    write_deployment_object(&mut body, config)?;
    Ok(body)
}

fn write_deployment_object<const N: usize>(
    body: &mut String<N>,
    config: &DeviceConfig,
) -> Result<(), core::fmt::Error> {
    write!(body, ",\"deployment\":{{")?;
    write_json_string_field(body, "hardware_profile", config.hardware_profile)?;
    write!(body, ",")?;
    write_json_string_field(body, "zone_name", config.zone_name)?;
    write!(body, ",")?;
    write_json_string_field(body, "send_behavior", config.send_behavior)?;
    write!(body, ",")?;
    write_json_string_field(body, "ir_protocol", config.ir_protocol)?;
    write!(body, ",")?;
    write_json_string_field(body, "backend", config.deploy_backend)?;
    if let Some(git_sha) = config.git_sha {
        if !git_sha.is_empty() {
            write!(body, ",")?;
            write_json_string_field(body, "git_sha", git_sha)?;
        }
    }
    if let Some(git_sha_short) = config.git_sha_short {
        if !git_sha_short.is_empty() {
            write!(body, ",")?;
            write_json_string_field(body, "git_sha_short", git_sha_short)?;
        }
    }
    write!(body, "}}}}")?;
    Ok(())
}

fn write_json_string_field<const N: usize>(
    body: &mut String<N>,
    key: &str,
    value: &str,
) -> Result<(), core::fmt::Error> {
    write!(body, "\"{}\":", key)?;
    write_json_string(body, value)
}

fn write_json_string<const N: usize>(
    out: &mut String<N>,
    value: &str,
) -> Result<(), core::fmt::Error> {
    out.push('"').map_err(|_| core::fmt::Error)?;
    for byte in value.bytes() {
        match byte {
            b'"' => out.push_str("\\\"").map_err(|_| core::fmt::Error)?,
            b'\\' => out.push_str("\\\\").map_err(|_| core::fmt::Error)?,
            b'\n' => out.push_str("\\n").map_err(|_| core::fmt::Error)?,
            b'\r' => out.push_str("\\r").map_err(|_| core::fmt::Error)?,
            b'\t' => out.push_str("\\t").map_err(|_| core::fmt::Error)?,
            0x20..=0x7e => out.push(byte as char).map_err(|_| core::fmt::Error)?,
            _ => out.push('?').map_err(|_| core::fmt::Error)?,
        }
    }
    out.push('"').map_err(|_| core::fmt::Error)
}

pub fn extract_command_created_dt(response_body: &str) -> Option<&str> {
    let command_value = command_value(response_body)?;
    if command_value.starts_with("null") {
        return None;
    }
    extract_json_string(command_value, "\"created_dt\"")
}

pub fn extract_command_json(response_body: &str) -> Option<&str> {
    let command_value = command_value(response_body)?;
    if !command_value.starts_with('{') {
        return None;
    }
    let end = matching_object_end(command_value)?;
    Some(&command_value[..end])
}

pub fn parse_server_time_utc_epoch(response_body: &str) -> Option<u64> {
    let iso = extract_json_string(response_body, "\"server_time_utc\"")?;
    parse_utc_iso_epoch(iso)
}

fn command_value(response_body: &str) -> Option<&str> {
    let key_pos = response_body.find("\"command\"")?;
    let after_key = &response_body[key_pos + "\"command\"".len()..];
    let colon_pos = after_key.find(':')?;
    Some(after_key[colon_pos + 1..].trim_start())
}

fn extract_json_string<'a>(body: &'a str, key: &str) -> Option<&'a str> {
    let key_pos = body.find(key)?;
    let after_key = &body[key_pos + key.len()..];
    let colon_pos = after_key.find(':')?;
    let after_colon = after_key[colon_pos + 1..].trim_start();
    let value = after_colon.strip_prefix('"')?;
    let end = value.find('"')?;
    Some(&value[..end])
}

fn matching_object_end(value: &str) -> Option<usize> {
    let bytes = value.as_bytes();
    if bytes.first() != Some(&b'{') {
        return None;
    }

    let mut depth: usize = 0;
    let mut in_string = false;
    let mut escaped = false;
    for (index, byte) in bytes.iter().enumerate() {
        if in_string {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                in_string = false;
            }
            continue;
        }

        match *byte {
            b'"' => in_string = true,
            b'{' => depth += 1,
            b'}' => {
                depth = depth.checked_sub(1)?;
                if depth == 0 {
                    return Some(index + 1);
                }
            }
            _ => {}
        }
    }
    None
}

fn parse_utc_iso_epoch(iso: &str) -> Option<u64> {
    if iso.len() < "YYYY-MM-DDTHH:MM:SS".len() {
        return None;
    }
    let year = parse_u32(&iso[0..4])?;
    let month = parse_u32(&iso[5..7])?;
    let day = parse_u32(&iso[8..10])?;
    let hour = parse_u32(&iso[11..13])?;
    let minute = parse_u32(&iso[14..16])?;
    let second = parse_u32(&iso[17..19])?;
    if iso.as_bytes().get(4) != Some(&b'-')
        || iso.as_bytes().get(7) != Some(&b'-')
        || iso.as_bytes().get(10) != Some(&b'T')
        || iso.as_bytes().get(13) != Some(&b':')
        || iso.as_bytes().get(16) != Some(&b':')
        || !(1..=12).contains(&month)
        || !(1..=days_in_month(year, month)).contains(&day)
        || hour > 23
        || minute > 59
        || second > 60
    {
        return None;
    }

    let days = days_before_year(year)? + days_before_month(year, month) + u64::from(day - 1);
    Some(days * 86_400 + u64::from(hour * 3_600 + minute * 60 + second))
}

fn parse_u32(raw: &str) -> Option<u32> {
    let mut value: u32 = 0;
    for byte in raw.as_bytes() {
        if !byte.is_ascii_digit() {
            return None;
        }
        value = value
            .checked_mul(10)?
            .checked_add(u32::from(*byte - b'0'))?;
    }
    Some(value)
}

fn days_before_year(year: u32) -> Option<u64> {
    if year < 1970 {
        return None;
    }
    let y = u64::from(year - 1);
    let before_year = y * 365 + y / 4 - y / 100 + y / 400;
    let base = 1969_u64 * 365 + 1969_u64 / 4 - 1969_u64 / 100 + 1969_u64 / 400;
    Some(before_year - base)
}

fn days_before_month(year: u32, month: u32) -> u64 {
    let mut days: u64 = 0;
    let mut current: u32 = 1;
    while current < month {
        days += u64::from(days_in_month(year, current));
        current += 1;
    }
    days
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

fn is_leap_year(year: u32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

#[cfg(test)]
mod tests {
    use super::{
        build_sensor_post_body, command_is_new, extract_command_created_dt, extract_command_json,
        parse_server_time_utc_epoch,
    };
    use crate::{DeviceConfig, SensorReading, SensorSource};

    #[test]
    fn accepts_strictly_newer_iso_timestamp() {
        assert!(command_is_new(
            "2026-05-25T10:00:00.000000",
            Some("2026-05-25T10:01:00.000000")
        ));
    }

    #[test]
    fn rejects_missing_or_stale_timestamps() {
        assert!(!command_is_new("2026-05-25T10:00:00.000000", None));
        assert!(!command_is_new("2026-05-25T10:00:00.000000", Some("")));
        assert!(!command_is_new(
            "2026-05-25T10:00:00.000000",
            Some("2026-05-25T10:00:00.000000")
        ));
        assert!(!command_is_new(
            "2026-05-25T10:00:00.000000",
            Some("2026-05-25T09:59:00.000000")
        ));
    }

    #[test]
    fn builds_nested_dmz_post_body() {
        let config = DeviceConfig::kitchen_pico2w();
        let reading = SensorReading {
            temp_centigrade: 21.0,
            humid_percent: 50.0,
            source: SensorSource::Fallback,
        };

        let body = build_sensor_post_body::<1024>(&config, reading, None, &[], None)
            .unwrap_or_else(|_| panic!("build_sensor_post_body failed"));

        assert!(body.contains("\"hardware_profile\":\"pico2w_aht20_ir\""));
        assert!(body.contains("\"backend\":\"pico2w\""));
        assert!(body.ends_with("}}"));
        if let Some(git_sha) = config.git_sha {
            if !git_sha.is_empty() {
                assert!(body.contains("\"git_sha\":"));
            }
        }
    }

    #[test]
    fn builds_post_body_with_network_metadata() {
        let config = DeviceConfig::kitchen_pico2w();
        let reading = SensorReading {
            temp_centigrade: 21.0,
            humid_percent: 50.0,
            source: SensorSource::Fallback,
        };

        let body = build_sensor_post_body::<512>(&config, reading, None, &[], Some("192.168.1.23"))
            .unwrap();

        assert!(body.contains("\"network\":{\"local_ip\":\"192.168.1.23\""));
        assert!(body.contains("\"onboard_url\":\"http://192.168.1.23:5000\""));
    }

    #[test]
    fn extracts_new_command_from_zone_response() {
        let body = "{\"command\":{\"power\":true,\"created_dt\":\"2026-05-25T10:01:00.000000\",\"note\":\"brace } in string\"},\"sensors\":{\"temp_centigrade\":21.0}}";

        assert_eq!(
            extract_command_created_dt(body),
            Some("2026-05-25T10:01:00.000000")
        );
        assert_eq!(
            extract_command_json(body),
            Some(
                "{\"power\":true,\"created_dt\":\"2026-05-25T10:01:00.000000\",\"note\":\"brace } in string\"}"
            )
        );
    }

    #[test]
    fn ignores_null_command() {
        let body = "{\"command\":null,\"sensors\":{\"temp_centigrade\":21.0}}";

        assert_eq!(extract_command_created_dt(body), None);
        assert_eq!(extract_command_json(body), None);
    }

    #[test]
    fn parses_dmz_diagnostics_time() {
        let body = "{\"server_time_utc\":\"2026-05-27T04:25:00.123456Z\"}";

        assert_eq!(parse_server_time_utc_epoch(body), Some(1_779_855_900));
    }

    #[test]
    fn builds_post_body_with_logs() {
        let config = DeviceConfig::kitchen_pico2w();
        let reading = SensorReading {
            temp_centigrade: 21.0,
            humid_percent: 50.0,
            source: SensorSource::Fallback,
        };

        let body = build_sensor_post_body::<512>(
            &config,
            reading,
            None,
            &["poll start", "command stale", "quote \" escaped"],
            None,
        )
        .unwrap();

        assert!(body.contains("\"logs\":{\"lines\":[\"poll start\",\"command stale\""));
        assert!(body.contains("quote \\\" escaped"));
    }
}
