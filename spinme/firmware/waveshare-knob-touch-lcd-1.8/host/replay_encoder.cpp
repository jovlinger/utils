/* Replay one captured encoder-debug log through encoder_on_edge.
 * stdin: the serial lines. stdout: "step rot" for each enc edge, in order.
 * The decoder state starts cleared, which is the glass after boot.
 */
#include <stdint.h>
#include <stdio.h>

#include "encoder_decode.h"

int main(void) {
  uint8_t pin = 0;
  uint32_t lock_us = 0;
  uint32_t high_us = 0;
  int rotation = 0;
  char line[256];
  while (fgets(line, sizeof(line), stdin) != nullptr) {
    unsigned long us = 0;
    unsigned int prev = 0;
    unsigned int cur = 0;
    if (sscanf(line, "enc us=%lu prev=%u cur=%u", &us, &prev, &cur) != 3) {
      continue;
    }
    int8_t step = 0;
    encoder_on_edge(static_cast<uint8_t>(prev), static_cast<uint8_t>(cur),
                    static_cast<uint32_t>(us), &pin, &lock_us, &high_us,
                    &rotation, &step);
    printf("%d %d\n", static_cast<int>(step), rotation);
  }
  return 0;
}
