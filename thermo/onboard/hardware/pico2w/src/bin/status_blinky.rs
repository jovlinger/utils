#![no_std]
#![no_main]

use embedded_hal::delay::DelayNs;
use embedded_hal::digital::OutputPin;
use panic_halt as _;
use rp235x_hal as hal;

#[link_section = ".start_block"]
#[used]
pub static IMAGE_DEF: hal::block::ImageDef = hal::block::ImageDef::secure_exe();

const XTAL_FREQ_HZ: u32 = 12_000_000;
const BLINK_MS: u32 = 250;
const PAUSE_MS: u32 = 350;

#[hal::entry]
fn main() -> ! {
    let mut pac = hal::pac::Peripherals::take().unwrap();
    let mut watchdog = hal::Watchdog::new(pac.WATCHDOG);
    let clocks = hal::clocks::init_clocks_and_plls(
        XTAL_FREQ_HZ,
        pac.XOSC,
        pac.CLOCKS,
        pac.PLL_SYS,
        pac.PLL_USB,
        &mut pac.RESETS,
        &mut watchdog,
    )
    .unwrap();
    let mut timer = hal::Timer::new_timer0(pac.TIMER0, &mut pac.RESETS, &clocks);
    let sio = hal::Sio::new(pac.SIO);
    let pins = hal::gpio::Pins::new(
        pac.IO_BANK0,
        pac.PADS_BANK0,
        sio.gpio_bank0,
        &mut pac.RESETS,
    );

    let mut red = pins.gpio10.into_push_pull_output();
    let mut green = pins.gpio11.into_push_pull_output();
    let mut blue = pins.gpio12.into_push_pull_output();

    loop {
        blink(
            &mut timer, &mut red, &mut green, &mut blue, true, true, false,
        );
        blink(
            &mut timer, &mut red, &mut green, &mut blue, false, false, true,
        );
        blink(
            &mut timer, &mut red, &mut green, &mut blue, false, true, false,
        );
        blink(
            &mut timer, &mut red, &mut green, &mut blue, true, false, false,
        );
    }
}

fn blink<D, R, G, B>(
    timer: &mut hal::Timer<D>,
    red: &mut R,
    green: &mut G,
    blue: &mut B,
    red_on: bool,
    green_on: bool,
    blue_on: bool,
) where
    D: hal::timer::TimerDevice,
    R: OutputPin,
    G: OutputPin,
    B: OutputPin,
{
    set_pin(red, red_on);
    set_pin(green, green_on);
    set_pin(blue, blue_on);
    timer.delay_ms(BLINK_MS);
    set_pin(red, false);
    set_pin(green, false);
    set_pin(blue, false);
    timer.delay_ms(PAUSE_MS);
}

fn set_pin<P>(pin: &mut P, on: bool)
where
    P: OutputPin,
{
    if on {
        let _ = pin.set_high();
    } else {
        let _ = pin.set_low();
    }
}

#[link_section = ".bi_entries"]
#[used]
pub static PICOTOOL_ENTRIES: [hal::binary_info::EntryAddr; 5] = [
    hal::binary_info::rp_cargo_bin_name!(),
    hal::binary_info::rp_cargo_version!(),
    hal::binary_info::rp_program_description!(c"Thermo Pico2W status LED blinky"),
    hal::binary_info::rp_cargo_homepage_url!(),
    hal::binary_info::rp_program_build_attribute!(),
];
