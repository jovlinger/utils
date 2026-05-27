# Thermo Onboard

This directory is split by portability:

- `common/` contains Python modules that can plausibly be shared by multiple onboard hardware targets.
- `hardware/pizero2w/` contains the Pi Zero 2 W Flask app, sensor and IR helpers, Docker images, compose deploy files, and Pi-specific operating notes.
- `hardware/pico2w/` contains the Pico2W Rust firmware scaffold and wiring plan.
- `install/` contains dispatcher scripts that read the room config and route deployment to `hardware/<backend>/install/`.

The current production backend is `pizero2w`:

```bash
export THERMO_ENV_FILE=config/kitchen.env
make -C thermo/onboard deploy
```

Pi Zero 2 W details: [`hardware/pizero2w/README.md`](hardware/pizero2w/README.md).
