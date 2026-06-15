#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeviceConfig {
    pub zone_name: &'static str,
    pub dmz_scheme: &'static str,
    pub dmz_host: &'static str,
    pub dmz_port: u16,
    pub onboard_port: u16,
    pub post_timeout_secs: u64,
    pub hardware_profile: &'static str,
    pub deploy_backend: &'static str,
    pub git_sha: Option<&'static str>,
    pub git_sha_short: Option<&'static str>,
    pub send_behavior: &'static str,
    pub report_behavior: &'static str,
    pub sensor_driver: &'static str,
    pub sensor_required_at_boot: bool,
    pub ir_transport: &'static str,
    pub ir_device: &'static str,
    pub ir_protocol: &'static str,
    pub ir_tx_gpio: u8,
    pub ir_rx_gpio: u8,
    pub i2c_sda_gpio: u8,
    pub i2c_scl_gpio: u8,
    pub aht20_addr: u8,
    pub status_led_driver: &'static str,
    pub app_core: u8,
}

impl DeviceConfig {
    pub const fn kitchen_esp32s3() -> Self {
        Self {
            zone_name: "kitchen",
            dmz_scheme: "http",
            dmz_host: "jovlinger.duckdns.org",
            dmz_port: 5000,
            onboard_port: 5000,
            post_timeout_secs: 600,
            hardware_profile: "esp32s3_aht20_ir",
            deploy_backend: "esp32s3",
            git_sha: option_env!("THERMO_DEPLOY_GIT_SHA"),
            git_sha_short: option_env!("THERMO_DEPLOY_GIT_SHA_SHORT"),
            send_behavior: "ir_heatpump",
            report_behavior: "sensor_readings",
            sensor_driver: "aht20",
            sensor_required_at_boot: false,
            ir_transport: "esp32s3_rmt",
            ir_device: "gpio17",
            ir_protocol: "midea24_coolix",
            ir_tx_gpio: 17,
            ir_rx_gpio: 6,
            i2c_sda_gpio: 35,
            i2c_scl_gpio: 36,
            aht20_addr: 0x38,
            status_led_driver: "log_only",
            app_core: 1,
        }
    }

    pub fn from_compile_env() -> Self {
        let mut config: Self = Self::kitchen_esp32s3();

        if let Some(zone_name) = option_env!("ZONE_NAME") {
            config.zone_name = zone_name;
        }
        if let Some(dmz_scheme) = option_env!("DMZ_SCHEME") {
            config.dmz_scheme = dmz_scheme;
        }
        if let Some(dmz_host) = option_env!("DMZ_HOST") {
            config.dmz_host = dmz_host;
        }
        config.dmz_port = u16_from_env(option_env!("DMZ_PORT"), config.dmz_port);
        config.onboard_port = u16_from_env(option_env!("PORT"), config.onboard_port);
        config.post_timeout_secs = u64_from_env(
            option_env!("ESP32S3_POST_TIMEOUT_SECS"),
            u64_from_env(option_env!("POST_TIMEOUT_SECS"), config.post_timeout_secs),
        );
        if let Some(hardware_profile) = option_env!("ONBOARD_HARDWARE_PROFILE") {
            config.hardware_profile = hardware_profile;
        }
        if let Some(deploy_backend) = option_env!("THERMO_DEPLOY_BACKEND") {
            config.deploy_backend = deploy_backend;
        }
        if let Some(git_sha) = option_env!("THERMO_DEPLOY_GIT_SHA") {
            config.git_sha = Some(git_sha);
        }
        if let Some(git_sha_short) = option_env!("THERMO_DEPLOY_GIT_SHA_SHORT") {
            config.git_sha_short = Some(git_sha_short);
        }
        if let Some(send_behavior) = option_env!("ONBOARD_SEND_BEHAVIOR") {
            config.send_behavior = send_behavior;
        }
        if let Some(report_behavior) = option_env!("ONBOARD_REPORT_BEHAVIOR") {
            config.report_behavior = report_behavior;
        }
        if let Some(sensor_driver) = option_env!("SENSOR_DRIVER") {
            config.sensor_driver = sensor_driver;
        }
        if let Some(ir_transport) = option_env!("IR_TRANSPORT") {
            config.ir_transport = ir_transport;
        }
        if let Some(ir_device) = option_env!("IR_DEVICE") {
            config.ir_device = ir_device;
        }
        if let Some(ir_protocol) = option_env!("ONBOARD_IR_PROTOCOL") {
            config.ir_protocol = ir_protocol;
        }
        if let Some(status_led_driver) = option_env!("ESP32S3_STATUS_LED_DRIVER") {
            config.status_led_driver = status_led_driver;
        }
        config.sensor_required_at_boot = bool_from_env(
            option_env!("SENSOR_BOOT_REQUIRED"),
            config.sensor_required_at_boot,
        );
        config.ir_tx_gpio = u8_from_env(option_env!("ESP32S3_IR_TX_GPIO"), config.ir_tx_gpio);
        config.ir_rx_gpio = u8_from_env(option_env!("ESP32S3_IR_RX_GPIO"), config.ir_rx_gpio);
        config.i2c_sda_gpio =
            u8_from_env(option_env!("ESP32S3_AHT20_SDA_GPIO"), config.i2c_sda_gpio);
        config.i2c_scl_gpio =
            u8_from_env(option_env!("ESP32S3_AHT20_SCL_GPIO"), config.i2c_scl_gpio);
        config.aht20_addr = u8_from_env(option_env!("ESP32S3_AHT20_ADDR"), config.aht20_addr);
        config.app_core = u8_from_env(option_env!("ESP32S3_APP_CORE"), config.app_core);
        config
    }

    pub fn zone_path(&self) -> ZonePath {
        ZonePath {
            zone_name: self.zone_name,
        }
    }
}

impl Default for DeviceConfig {
    fn default() -> Self {
        Self::kitchen_esp32s3()
    }
}

pub fn wifi_ssid() -> Option<&'static str> {
    option_env!("ESP32S3_WIFI_SSID").or(option_env!("WIFI_SSID"))
}

pub fn wifi_password() -> Option<&'static str> {
    option_env!("ESP32S3_WIFI_PASSWORD").or(option_env!("WIFI_PASSWORD"))
}

pub fn zone_private_key_b64() -> Option<&'static str> {
    option_env!("ESP32S3_ZONE_PRIVATE_KEY_B64").or(option_env!("ZONE_PRIVATE_KEY"))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ZonePath {
    zone_name: &'static str,
}

impl ZonePath {
    pub fn as_parts(&self) -> (&'static str, &'static str, &'static str) {
        ("/zone/", self.zone_name, "/sensors")
    }
}

fn bool_from_env(raw: Option<&'static str>, default: bool) -> bool {
    match raw {
        Some("1") | Some("true") | Some("TRUE") | Some("yes") | Some("YES") => true,
        Some("0") | Some("false") | Some("FALSE") | Some("no") | Some("NO") => false,
        Some(_) | None => default,
    }
}

fn u16_from_env(raw: Option<&'static str>, default: u16) -> u16 {
    let value = u64_from_env(raw, u64::from(default));
    u16::try_from(value).unwrap_or(default)
}

fn u8_from_env(raw: Option<&'static str>, default: u8) -> u8 {
    let Some(raw) = raw else {
        return default;
    };
    if let Some(hex) = raw.strip_prefix("0x").or_else(|| raw.strip_prefix("0X")) {
        return u8::from_str_radix(hex, 16).unwrap_or(default);
    }
    let value = u64_from_env(Some(raw), u64::from(default));
    u8::try_from(value).unwrap_or(default)
}

fn u64_from_env(raw: Option<&'static str>, default: u64) -> u64 {
    let Some(raw) = raw else {
        return default;
    };
    let mut value: u64 = 0;
    for byte in raw.as_bytes() {
        if !byte.is_ascii_digit() {
            return default;
        }
        let Some(next) = value
            .checked_mul(10)
            .and_then(|value| value.checked_add(u64::from(*byte - b'0')))
        else {
            return default;
        };
        value = next;
    }
    value
}

#[cfg(test)]
mod tests {
    use super::{bool_from_env, u16_from_env, u64_from_env, u8_from_env, DeviceConfig};

    #[test]
    fn default_config_matches_esp32s3_plan() {
        let config: DeviceConfig = DeviceConfig::kitchen_esp32s3();

        assert_eq!(config.zone_name, "kitchen");
        assert_eq!(config.hardware_profile, "esp32s3_aht20_ir");
        assert_eq!(config.deploy_backend, "esp32s3");
        assert_eq!(config.dmz_port, 5000);
        assert_eq!(config.onboard_port, 5000);
        assert_eq!(config.post_timeout_secs, 600);
        assert_eq!(config.sensor_driver, "aht20");
        assert_eq!(config.ir_transport, "esp32s3_rmt");
        assert_eq!(config.ir_protocol, "midea24_coolix");
        assert_eq!(config.ir_tx_gpio, 17);
        assert_eq!(config.ir_rx_gpio, 6);
        assert_eq!(config.i2c_scl_gpio, 36);
        assert_eq!(config.i2c_sda_gpio, 35);
        assert_eq!(config.aht20_addr, 0x38);
        assert_eq!(config.status_led_driver, "log_only");
        assert_eq!(config.app_core, 1);
    }

    #[test]
    fn parses_bool_env_values() {
        assert!(bool_from_env(Some("1"), false));
        assert!(!bool_from_env(Some("0"), true));
        assert!(bool_from_env(Some("unexpected"), true));
        assert!(!bool_from_env(None, false));
    }

    #[test]
    fn parses_u16_env_values() {
        assert_eq!(u16_from_env(Some("5000"), 80), 5000);
        assert_eq!(u16_from_env(Some("bad"), 80), 80);
        assert_eq!(u16_from_env(Some("70000"), 80), 80);
        assert_eq!(u16_from_env(None, 80), 80);
    }

    #[test]
    fn parses_u8_env_values() {
        assert_eq!(u8_from_env(Some("0x38"), 0x40), 0x38);
        assert_eq!(u8_from_env(Some("38"), 0x40), 38);
        assert_eq!(u8_from_env(Some("bad"), 0x40), 0x40);
        assert_eq!(u8_from_env(None, 0x40), 0x40);
    }

    #[test]
    fn parses_u64_env_values() {
        assert_eq!(u64_from_env(Some("600"), 75), 600);
        assert_eq!(u64_from_env(Some("bad"), 75), 75);
        assert_eq!(u64_from_env(None, 75), 75);
    }
}
