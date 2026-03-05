# Cloud Alternative: AWS EC2 / GCP e2-micro

Deploy the DMZ app on a free-tier cloud VM instead of Pi 1B + MikroTik. Simpler to get running; different security and cost trade-offs.

## Comparison

| Aspect | Pi + MikroTik | Cloud |
|--------|---------------|-------|
| Initial setup | High (Alpine diskless, ARMv6, SD, RouterOS) | Low (launch VM, deploy) |
| Physical work | Yes (Pi, SD, cabling) | No |
| Platform | ARMv6, initramfs, apkovl | x86_64/ARM64, standard Linux |
| Router config | Yes (DMZ, NAT, firewall) | No (cloud firewall only) |
| Ongoing cost | None | Free tier limits, then paid |

## AWS EC2 Free Tier (12 months)

- **Instance**: t2.micro or t3.micro (750 hrs/month free)
- **Steps**:
  1. Launch instance → Ubuntu 24.04 LTS AMI
  2. Security group: allow inbound 80 (HTTP), 22 (SSH)
  3. SSH in: `ssh -i key.pem ubuntu@<public-ip>`
  4. Deploy: see [Deploy](#deploy) below

## GCP e2-micro (Always Free)

- **Instance**: e2-micro (1 instance free within limits)
- **Steps**:
  1. Create VM → e2-micro, Ubuntu 24.04
  2. Firewall: allow tcp:80, tcp:22
  3. SSH in (browser or gcloud)
  4. Deploy: see [Deploy](#deploy) below

## Deploy

```bash
# On the VM
sudo apt update && sudo apt install -y docker.io
sudo usermod -aG docker $USER
# Log out and back in for docker group

# Clone or copy the thermo/dmz app
git clone <repo> thermo && cd thermo/dmz

# Build and run (x86_64 - no ARMv6)
docker build -t dmz .
docker run -d -p 80:8080 \
  -e GOOGLE_CLIENT_ID=... \
  -e GOOGLE_CLIENT_SECRET=... \
  -e SECRET_KEY=... \
  dmz
```

Or run without Docker:

```bash
cd thermo/dmz
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
PORT=80 python app.py
```

## Network

Zones and controller reach the DMZ via the VM's public IP or domain. No port forward on your home router. Ensure zones (if on LAN) can reach the cloud URL, or run zones in cloud as well.

## OAuth / Env Vars

Set in container or environment:

- `GOOGLE_CLIENT_ID` — from Google Cloud Console OAuth 2.0 credentials
- `GOOGLE_CLIENT_SECRET`
- `SECRET_KEY` — Flask session signing (random 32+ bytes)
- `ALLOWED_EMAIL` — e.g. `jovlinger@gmail.com` (optional; defaults to single-user allowlist)
