# Waveshare Knob-Touch-LCD-1.8

UI image for the ESP32-S3 knob. From this directory:

```bash
make build
make install
```

`make build` compiles the UI. `make install` compiles if needed and flashes the board. The upload port is `upload_port` in `platformio.ini`. Stop `pio device monitor` before install; it holds the same serial port.

## Line and ink

Ink height and line spacing live in `screenmock/glyphfile.py` as `BODY_H` and `LINE_VSHIM`. Letter, word, and section gaps are `LETTER_HSHIM`, `WORD_HSHIM`, and `SECTION_VSHIM` in that same file. Those constants are written into `glyphs.bin`. After editing them, regenerate from the spinme directory, then install:

```bash
./screenmock/gen_font12.py /path/to/DejaVuSans.ttf
make -C firmware/waveshare-knob-touch-lcd-1.8 install
```

The firmware reads the sizes from the mapped glyph file. It does not keep a second copy.

## Screen layout

The glass layout is `src/main.cpp` (`compose_block` and `draw_status`). `screenmock/layout.py` is the host copy of that layout and must stay in step with it.

Hardware notes: [`../../hardware/waveshare-knob-touch-lcd-1.8/`](../../hardware/waveshare-knob-touch-lcd-1.8/).
