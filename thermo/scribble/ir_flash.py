#!/usr/bin/env python3
"""Flash the ANAVI IR pHAT's IR LEDs in a pattern using raw LIRC pulses.

IR hardware on this Pi Zero W2:
  /dev/lirc0 = TX (gpio-ir-tx, GPIO 18) - sends raw IR
  /dev/lirc1 = RX (gpio-ir,    GPIO 17) - receives raw IR

We send bursts of 38kHz-modulated IR (the carrier is handled by the hardware).
The pulse/space values are in microseconds. The IR LEDs are invisible to the
naked eye, but you can see them flash through a phone camera.

Future: replace these test patterns with proper Daikin comfort heatpump frames.
"""

import subprocess
import tempfile
import time
import sys

LIRC_TX = "/dev/lirc0"


def send_pulse_train(pulses_us):
    """Send a raw pulse train via ir-ctl.

    pulses_us is a list of ints: [pulse, space, pulse, space, ...].
    ir-ctl expects a text file with lines like 'pulse 9000' / 'space 4500'.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for i, val in enumerate(pulses_us):
            kind = "pulse" if i % 2 == 0 else "space"
            f.write(f"{kind} {val}\n" if i < len(pulses_us) - 1 else f"{kind} {val}")
        fname = f.name
    subprocess.run(["ir-ctl", "-d", LIRC_TX, "--send", fname], check=True)


def make_burst(on_us=500, off_us=500, count=10):
    """Generate a simple on/off burst pattern."""
    train = []
    for _ in range(count):
        train.append(on_us)
        train.append(off_us)
    return train


# --- patterns ---


def short_blip():
    """Single short blip."""
    send_pulse_train([2000, 1000])


def slow_blink(n=5):
    """N distinct blinks with pauses between."""
    for i in range(n):
        send_pulse_train(make_burst(on_us=3000, off_us=1000, count=5))
        time.sleep(0.3)


def sos():
    """SOS in morse: ... --- ..."""
    dot = make_burst(on_us=500, off_us=500, count=3)
    dash = make_burst(on_us=1500, off_us=500, count=3)
    for pattern in [dot, dot, dot, dash, dash, dash, dot, dot, dot]:
        send_pulse_train(pattern)
        time.sleep(0.2)


if __name__ == "__main__":
    patterns = {
        "blip": short_blip,
        "blink": slow_blink,
        "sos": sos,
    }

    name = sys.argv[1] if len(sys.argv) > 1 else "blink"
    if name not in patterns:
        avail = ", ".join(patterns.keys())
        print(f"Unknown pattern: {name}")
        print(f"Available: {avail}")
        sys.exit(1)

    print(f"Flashing IR LEDs: {name}  (view through phone camera)")
    patterns[name]()
    print("Done.")
