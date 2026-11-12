# Host tests layout

| Dir | Runs where | Contents |
|-----|------------|----------|
| `local/` | Build machine | All PC unit + golden tests (`make test`) |
| `ondevice/` | Build machine -> board | Post-flash / post-OTA via HTTP event gateway |

```bash
cd spinme/host && make test
./tests/ondevice/run_test.sh smoke    # after flash; needs board on LAN
```

## local/ pixel goldens (examples)

| Binary | What |
|--------|------|
| `test_xy_timed_redraw` | Digits **0-9** under veil, letters **a-j** over veil; **bit-identical** PNG vs `screenshots/xy_timed/t00.png`..`t09.png` |
| `test_screenshots` | Full glass UI; **pixel RGB** equal vs `screenshots/*.png` |

Refresh: `REGEN_XY_TIMED=1` / `SPINME_UI_UPDATE_GOLDEN=1` (cwd `spinme/host`).
