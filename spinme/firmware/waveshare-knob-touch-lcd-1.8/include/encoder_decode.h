#pragma once

#include <stdint.h>

/* Other-pin chatter is ignored for this long after a click.
 * The same pin may click again once it has been high for kEncMinHighUs,
 * so a fast spin is not capped at one step per lock. */
static const uint32_t kEncLockUs = 200000;
static const uint32_t kEncMinHighUs = 2000;

/* prev/cur pack ab = (GPIO8 << 1) | GPIO7.
 * pin is 0x2 (GPIO8, +1) or 0x1 (GPIO7, -1), or 0 before the first click.
 * high_us is when that pin was last seen high after a count, or 0 while it
 * is still low. lock_us is the deadline for ignoring the other pin.
 * Outside the lock a click is a falling edge. A rise is the contact
 * releasing, including after the lock expired while that pin was still low.
 * Inside the lock, a later fall of the same pin, once it has been high for
 * kEncMinHighUs, is another click. */
static inline void encoder_on_edge(uint8_t prev, uint8_t cur, uint32_t now,
                                   volatile uint8_t *pin,
                                   volatile uint32_t *lock_us,
                                   volatile uint32_t *high_us,
                                   volatile int *rotation, int8_t *step)
    __attribute__((always_inline));

static inline void encoder_on_edge(uint8_t prev, uint8_t cur, uint32_t now,
                                   volatile uint8_t *pin,
                                   volatile uint32_t *lock_us,
                                   volatile uint32_t *high_us,
                                   volatile int *rotation, int8_t *step) {
  *step = 0;
  if (prev == cur) {
    return;
  }
  const bool in_lock = *pin != 0 && static_cast<int32_t>(now - *lock_us) < 0;
  if (in_lock) {
    const uint8_t changed = static_cast<uint8_t>(prev ^ cur);
    const uint8_t other = (*pin == 0x2) ? static_cast<uint8_t>(0x1)
                                        : static_cast<uint8_t>(0x2);
    const bool click_changed = (changed & *pin) != 0;
    const bool other_changed = (changed & other) != 0;
    if (!click_changed || other_changed) {
      return;
    }
    const bool fell = (prev & *pin) != 0 && (cur & *pin) == 0;
    const bool rose = (prev & *pin) == 0 && (cur & *pin) != 0;
    if (rose) {
      *high_us = now;
      return;
    }
    if (fell && *high_us != 0 &&
        static_cast<int32_t>(now - *high_us) >=
            static_cast<int32_t>(kEncMinHighUs)) {
      *step = (*pin & 0x2) != 0 ? static_cast<int8_t>(1)
                                : static_cast<int8_t>(-1);
      *rotation += *step;
      *high_us = 0;
      *lock_us = now + kEncLockUs;
    }
    return;
  }

  const uint8_t changed = static_cast<uint8_t>(prev ^ cur);
  const bool a_changed = (changed & 0x2) != 0;
  const bool b_changed = (changed & 0x1) != 0;
  uint8_t next_pin = 0;
  if (a_changed && !b_changed) {
    const bool fell = (prev & 0x2) != 0 && (cur & 0x2) == 0;
    if (fell) {
      next_pin = 0x2;
      *step = 1;
    }
  } else if (b_changed && !a_changed) {
    const bool fell = (prev & 0x1) != 0 && (cur & 0x1) == 0;
    if (fell) {
      next_pin = 0x1;
      *step = -1;
    }
  } else if (a_changed && b_changed) {
    const bool a_fell = (prev & 0x2) != 0 && (cur & 0x2) == 0;
    const bool b_fell = (prev & 0x1) != 0 && (cur & 0x1) == 0;
    if (a_fell && !b_fell) {
      next_pin = 0x2;
      *step = 1;
    } else if (b_fell && !a_fell) {
      next_pin = 0x1;
      *step = -1;
    }
  }
  if (*step == 0) {
    return;
  }
  *rotation += *step;
  *pin = next_pin;
  *lock_us = now + kEncLockUs;
  const bool rose = (prev & next_pin) == 0 && (cur & next_pin) != 0;
  *high_us = rose ? now : 0;
}
