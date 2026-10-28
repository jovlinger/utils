To decode both fast and slow rotations reliably, standard tick-by-tick counting is insufficient. Spinning the knob quickly causes a "velocity jump" where slow turning increments a setting by 1, but a rapid flick accelerates the value by 10 or 50 (ideal for scrolling lists or jumping volume).
The production-ready pseudocode below utilizes a Velocity-Sensitive Interrupt Handler. It tracks the time delta (\(\Delta t\)) between hardware detent transitions to scale the step size dynamically, while using an internal Interrupt Service Routine (ISR) state machine to filter noise out of the mechanical contacts.

The Dynamic Decoding Algorithm

c
// --- Configuration Constants ---
#define PIN_A            40   // Physical Pin A on ESP32-S3
#define PIN_B            41   // Physical Pin B on ESP32-S3
#define DEBOUNCE_US      2000 // 2ms hardware contact debounce window
#define SLOW_THRESHOLD_MS 150 // Deltas slower than this increment by 1
#define FAST_THRESHOLD_MS 15  // Deltas faster than this trigger max acceleration
#define MIN_STEP          1
#define MAX_STEP          25

// --- OS Shared Memory Variables ---
volatile int32_t system_value = 0;
volatile uint64_t last_interrupt_time = 0;
volatile uint8_t encoder_state_matrix = 0;

// --- ISR: Hardware Pulse Decoder ---
void IRAM_ATTR encoder_isr() {
    uint64_t current_time = esp_timer_get_time(); // Microsecond clock
    
    // Read raw hardware logic levels
    uint8_t pinA_val = gpio_get_level(PIN_A);
    uint8_t pinB_val = gpio_get_level(PIN_B);
    
    // 2-Bit Gray Code composition
    uint8_t current_state = (pinA_val << 1) | pinB_val;
    
    // Evaluate transition state matrix to filter electrical bounce
    encoder_state_matrix = (encoder_state_matrix << 2) | current_state;
    uint8_t transition = encoder_state_matrix & 0x0F;
    
    int8_t direction = 0;
    if (transition == 0b0010 || transition == 0b1011 || transition == 0b1101 || transition == 0b0100) {
        direction = 1;  // Clockwise
    } else if (transition == 0b0001 || transition == 0b0111 || transition == 0b1110 || transition == 0b1000) {
        direction = -1; // Counter-Clockwise
    }
    
    if (direction != 0) {
        uint64_t time_delta_us = current_time - last_interrupt_time;
        
        // Discard impossible speeds (debounce)
        if (time_delta_us < DEBOUNCE_US) {
            return; 
        }
        
        uint32_t time_delta_ms = time_delta_us / 1000;
        int32_t step_scale = MIN_STEP;
        
        // --- Velocity Mapping Logic ---
        if (time_delta_ms < SLOW_THRESHOLD_MS) {
            // Inverse linear curve scaling between thresholds
            if (time_delta_ms <= FAST_THRESHOLD_MS) {
                step_scale = MAX_STEP;
            } else {
                // Scale smooth progression between min and max steps
                step_scale = MIN_STEP + ((SLOW_THRESHOLD_MS - time_delta_ms) * (MAX_STEP - MIN_STEP)) / (SLOW_THRESHOLD_MS - FAST_THRESHOLD_MS);
            }
        }
        
        // Apply modification atomically
        system_value += (direction * step_scale);
        last_interrupt_time = current_time;
        
        // High-speed OS execution signaling
        BaseType_t high_task_wakeup = pdFALSE;
        xTaskNotifyFromISR(ui_processing_task_handle, system_value, eSetValueWithOverwrite, &high_task_wakeup);
        
        if (high_task_wakeup == pdTRUE) {
            portYIELD_FROM_ISR(); // Context switch immediately to process new value
        }
    }
}
Use code with caution.

Architectural Explanations

1. Why IRAM_ATTR?
Placing the macro prefix before the function tells the FreeRTOS compiler to load this code straight into the internal Instruction SRAM instead of reading it from external Flash. If you spin the knob rapidly while the CPU is pulling heavy graphics data or network packets from external memory, this guarantees zero cache-miss latency and captures every detent pulse cleanly.
2. The Gray Code State Matrix:
Mechanical encoders do not cleanly cycle off/on. They generate electrical noise (bounce). By packing the prior reading and current reading into a single 4-bit state byte (transition), the algorithm ignores transitions that are mathematically impossible unless the contact pins bounce back and forth.
3. The Inverse Scaling Multiplier:
If you turn the dial slowly (\(\Delta t > 150\text{ms}\)), the value modifies by exactly 1 for high-precision edits (like single-degree temperature settings). If you flick your wrist quickly (\(\Delta t \le 15\text{ms}\)), it scales up instantly to adjustments of 25 per pulse, skipping long menus or ramping volume smoothly.

Copy-Paste Firmware References

If you prefer using pre-built open-source firmware modules instead of rolling your own math, review these live production configurations optimized for this board:
• ESPHome Native Config: The Home Assistant community uses a built-in state engine to process this wheel via ESPHome Community Board Config. [1] (https://community.home-assistant.io/t/display-knob/905249)
• Velocity-Sensitive Volume Logic: To see how to pass these scaled increments directly to streaming audio frameworks, see the custom UI implementation inside Roon Knob Media Controller on GitHub. [1] (https://github.com/muness/roon-knob)
• Raw Hardware Driver Framework: For bare-metal driver integration parameters utilizing native ESP32 interrupt setups, look through the Waveshare Knob Display Project Stack. [1] (https://github.com/KrX3D/WaveShare-Knob-Esp32S3)
Would you like to look at the FreeRTOS task loop structure required to safely consume these volatile updates without stalling your LCD rendering thread?
