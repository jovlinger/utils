# Firmware scaffold -- CrowPanel 1.28 (DHE38128D)

PlatformIO Arduino env with OTA-ready `partitions_ota.csv` and wiki pin headers.

```bash
cd spinme/firmware/elecrow-crowpanel-1.28
pio run
pio run -t upload
pio device monitor
```

Requires PlatformIO (`pio`) installed on the host. Not built in CI yet.
Hardware docs: [`../../hardware/elecrow-crowpanel-1.28/`](../../hardware/elecrow-crowpanel-1.28/).
