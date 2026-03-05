# Install Scripts

Order of operations: **prepare → flash → boot → test**

| Step | Script | Where |
|------|--------|-------|
| 1. Build | `docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz .` | Dev machine |
| 2. Export | `./export_rootfs.sh jovlinger/thermo/dmz dmz_rootfs.tar` | Dev machine |
| 3. Prepare SD | `./prepare-sd.sh dmz_rootfs.tar /path/to/sd` | Dev machine (SD mounted) |
| 4. Boot | dmz-init.start runs automatically | Pi 1B |
| 5. Or manual | `./run_raw.sh /tmp/dmz_rootfs` | Pi 1B (after extract) |

See [plan.md](../plan.md) for dmz-init.start setup (lbu, apkovl).

**Cloud alternative**: See [CLOUD.md](CLOUD.md) for AWS EC2 / GCP e2-micro deployment.
