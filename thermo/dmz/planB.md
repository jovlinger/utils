# Plan B: DMZ on GCP Free Tier

Run the DMZ on Google Cloud instead of Pi 1B + MikroTik. Simpler setup; different trade-offs.

## Credit Card: Can You Avoid It?

**No.** GCP requires a valid credit or debit card to sign up, even for free tier. It is used for identity verification. Oracle Cloud and AWS free tiers also require a payment method. There is no major cloud provider that offers free compute without a card on file.

### Virtual Cards for Capped Spending

Using a virtual or burner card with a spending limit adds a second layer of protection (in addition to GCP budgets).

| Provider | Virtual cards | Spending limit | Burner / single-use | Notes |
|---------|---------------|----------------|--------------------|-------|
| **Capital One** (Eno) | Yes | No user-set limit; tied to credit limit | Merchant-specific (one card per merchant) | Credit cards only; not Capital One 360 (checking). Eno creates merchant-locked numbers. |
| **Chase** | No | — | — | Chase does not currently offer virtual credit cards. |
| **Eastern Bank** (US) | No | — | — | No virtual card product found; contact bank to confirm. |
| **Privacy.com** | Yes | Per-transaction, daily, weekly, monthly, yearly, or total | Yes; can create one-off cards | Third-party; links to bank account. Set e.g. $10/month cap for GCP. |

**Recommendation:** If your bank does not offer capped virtual cards, use **Privacy.com** (free tier): create a card for "Google Cloud", set a monthly spending limit (e.g. $5–10), and use it as the GCP payment method. Charges beyond the limit are declined.

---

## Cloud Run Setup Sequence

Follow this sequence to set up a Cloud Run account with safeguards in place before any billable usage.

### Phase 1: Account and Billing (before any deployment)

1. **Create a separate Google account** (e.g. `yourname-thermo@gmail.com`) for GCP only. Do not use your personal Gmail as the billing owner.

2. **Obtain a virtual/capped card** (see [Virtual Cards](#virtual-cards-for-capped-spending)) and set a monthly limit (e.g. $5–10).

3. **Sign up for GCP** at [console.cloud.google.com/freetrial](https://console.cloud.google.com/freetrial).
   - Use the separate Google account.
   - Add the virtual card as the payment method.
   - Complete identity verification (card authorization; may show $0–1 pending).

4. **Create a project**: Console → Select project → New Project → e.g. `thermo-dmz`.

5. **Create a budget** (Billing → Budgets & alerts → Create budget):
   - Amount: e.g. $3–5 (below your card limit).
   - Alerts: 50%, 90%, 100%.
   - Add your personal email as a billing contact for notifications.

6. **(Optional) Set up disable-billing function** (see [Safest Strategy](#safest-strategy-to-cap-max-cost)): Budget → Pub/Sub topic → Cloud Function to disable billing at threshold.

### Phase 2: Pre-Deploy Checklist

Run this checklist **before** deploying the DMZ service. All items must pass.

- [ ] **Separate account**: GCP is using a dedicated Google account, not your personal Gmail.
- [ ] **Virtual/capped card**: Payment method has a spending limit (Privacy.com or bank virtual card).
- [ ] **Budget created**: Budget exists with alerts at 50%, 90%, 100%.
- [ ] **Billing contact**: Your personal email receives budget notifications.
- [ ] **Region**: Plan to deploy in `us-central1` (or another free-tier region).
- [ ] **Disable-billing** (optional): Pub/Sub + Cloud Function configured to disable billing at threshold.

### Phase 3: Deploy Cloud Run

7. **Enable APIs**: Cloud Run API, Artifact Registry API (if building images in GCP).

8. **Build and push image** (from your machine or Cloud Build):
   ```bash
   docker build -t us-central1-docker.pkg.dev/PROJECT_ID/REPO/dmz:latest .
   docker push us-central1-docker.pkg.dev/PROJECT_ID/REPO/dmz:latest
   ```

9. **Deploy with strict limits**:
   ```bash
   gcloud run deploy dmz \
     --image us-central1-docker.pkg.dev/PROJECT_ID/REPO/dmz:latest \
     --region us-central1 \
     --platform managed \
     --cpu 0.08 \
     --memory 256Mi \
     --concurrency 1 \
     --max-instances 1 \
     --min-instances 0 \
     --timeout 60 \
     --no-cpu-boost
   ```

10. **Verify**: Visit the `*.run.app` URL; confirm the service responds.

### Phase 4: Post-Deploy Verification

- [ ] **Service URL** works and returns expected response.
- [ ] **Cloud Run config**: `gcloud run services describe dmz --region us-central1` shows `max-instances: 1`, `cpu: 0.08`, `memory: 256Mi`.
- [ ] **Billing**: Billing → Reports shows $0 or minimal usage within free tier.

---

## Safest Strategy to Cap Max Cost

GCP has **no native hard spending cap**. Budget alerts only notify you; they do not stop billing. To cap cost you must automate a response.

### Recommended: Budget + Pub/Sub + Cloud Function (Disable Billing)

1. **Create a budget** scoped to your project, e.g. $5 (set below your real limit to account for delay).
2. **Connect a Pub/Sub topic** to the budget for programmatic notifications.
3. **Deploy a Cloud Function** that receives budget notifications and calls the Cloud Billing API to **disable billing** on the project when the threshold is exceeded.

When billing is disabled, all services in the project stop (including the DMZ). You must manually re-enable billing to resume.

**Docs:** [Disable billing usage with notifications](https://cloud.google.com/billing/docs/how-to/disable-billing-with-notifications)

**Caveat:** There is a delay between incurring costs and the budget notification. You may incur some overage (often a few dollars) before the function runs. Set the budget amount below your true limit (e.g. $3 if you want to cap around $5).

### Additional Hardening

| Layer | Action |
|-------|--------|
| **Cloud Run** | `--max-instances=1` so traffic spikes cannot scale out |
| **e2-micro** | Fixed cost; traffic does not increase spend |
| **Budget** | Set at $3–5; Pub/Sub + function disables billing at 100% |

---

## Options

| Option | Service | Name service | Cost |
|--------|---------|--------------|------|
| **A** | Cloud Run | Built-in `*.run.app` URL | Free tier: 2M req/mo |
| **B** | e2-micro VM | You provide DNS | Always free (1 instance) |

---

## 1. Name Service for the Public IP

### Option A: Cloud Run (no DNS setup)

Cloud Run gives you a URL automatically:

```
https://dmz-PROJECT_NUMBER.REGION.run.app
```

- No DNS configuration
- HTTPS by default
- Stable URL once deployed
- Zones and onboard use this URL directly

### Option B: e2-micro VM (you need DNS)

The VM gets an ephemeral or static external IP. You need a hostname that points to it.

| Approach | Hostname example | Setup |
|----------|-------------------|-------|
| **Own domain** | `dmz.yourdomain.com` | Add A record in your DNS (Cloudflare, etc.) → VM's static IP |
| **DuckDNS** | `thermo-dmz.duckdns.org` | Free. Register at duckdns.org, run cron script on VM to update IP |
| **Cloudflare** | `dmz.yourdomain.com` | If domain on Cloudflare, add A record; optional DDNS script if IP changes |

**Static vs ephemeral IP (e2-micro):**

- **Ephemeral**: Free. IP may change on VM stop/start. Use DuckDNS + cron to update.
- **Static**: Reserve in GCP. Stable. May incur charge when VM stopped (free tier rules vary). Use with own domain A record.

**Recommendation for VM:** Use DuckDNS if you don't have a domain — free, simple, cron updates IP every 5 min.

---

## Ensure It Stays Free Under Unforeseen Load

### Cloud Run (risk: traffic spike → scale-out → charges)

```bash
gcloud run deploy dmz --max-instances=1 ...
```

- With `max-instances=1`, extra traffic queues or returns 429; no scale-out.
- Free tier: 2M requests/mo. Beyond that, you pay.

### e2-micro VM (risk: fixed cost; traffic does not affect it)

- Cost is fixed. Traffic spikes do not increase cost.
- Stay within always-free: 1 e2-micro in eligible regions (us-central1, us-west1, etc.), 30 GB standard disk.
- Avoid: extra disks, static IP when VM stopped, premium OS images.

### Summary

| Option | Cost cap under load | Action |
|--------|---------------------|--------|
| Cloud Run | Set `--max-instances=1` | Prevents scale-out |
| e2-micro | Fixed by design | Stay in free tier |
| **Both** | **Budget + disable-billing function** | Only way to hard-cap total spend |

---

## 3. Cloud Run vs e2-micro

| Aspect | Cloud Run | e2-micro VM |
|--------|-----------|-------------|
| Name service | Built-in | DuckDNS or own domain |
| Container | Yes (deploy image) | Yes (Docker on VM) |
| Always-on | Scales to zero (cold start) | Always running |
| Free tier | 2M requests/mo | 1 instance, 30 GB disk |
| Load protection | `max-instances=1` | Fixed cost |
| OAuth / env | Set in service config | Set in container or VM |

---

## 4. Deep Dive: Constraining Scaling to Stay Within Free Tier

### Cloud Run Free Tier (Request-Based Billing)

| Resource | Free per month |
|----------|----------------|
| Requests | 2,000,000 |
| Memory | 360,000 GiB-seconds |
| CPU | 180,000 vCPU-seconds |
| Outbound data | 1 GB (North America) |

**Recommended settings to minimize usage and cap scale-out:**

| Setting | Value | Rationale |
|---------|-------|------------|
| `--max-instances` | 1 | Prevents scale-out; extra traffic queues or returns 429 |
| `--min-instances` | 0 | Scale to zero when idle; no charge when no requests |
| `--cpu` | 0.08 | Minimum vCPU; requires request-based billing + concurrency=1 |
| `--memory` | 256Mi | Minimum; 0.08 vCPU supports up to 512 MiB |
| `--concurrency` | 1 | **Required** when using &lt;1 vCPU |
| `--timeout` | 60 | Limit request duration (default 300s); shorter = less billed time |
| `--no-cpu-boost` | (default) | Avoid extra CPU during cold start (optional; disable startup boost) |

**Caveats:**

- **Traffic spikes**: Cloud Run may briefly exceed `max-instances` during rapid surges. Set `max-instances=1`; worst case you get 2 for a short period.
- **Deployments**: During a new revision rollout, old + new revisions can run simultaneously. With max=1 per revision, you might see 2 instances briefly.
- **Execution environment**: &lt;1 vCPU requires **1st gen** execution environment (not 2nd gen).

**Free-tier math (0.08 vCPU, 256 MiB):**

- Per second per instance: 0.08 vCPU-s, 0.25 GiB-s
- Memory binds first: 360,000 ÷ 0.25 = **1,440,000 seconds** ≈ 400 hours
- CPU: 180,000 ÷ 0.08 = 2,250,000 seconds ≈ 625 hours
- Effective limit: ~1.44M seconds of instance time/month before memory free tier is exceeded
- At concurrency 1: ~1.44M requests if each runs ~1 second

For a thermostat DMZ (few requests/min), usage is negligible. The main safeguard is `max-instances=1`.

**Example deploy command:**

```bash
gcloud run deploy dmz \
  --image IMAGE_URL \
  --region us-central1 \
  --platform managed \
  --cpu 0.08 \
  --memory 256Mi \
  --concurrency 1 \
  --max-instances 1 \
  --min-instances 0 \
  --timeout 60 \
  --no-cpu-boost
```

---

### e2-micro Free Tier

| Resource | Free limit |
|----------|------------|
| Instances | 1 e2-micro |
| Hours | Total hours in the month (e.g. 744 for 31 days) |
| Regions | us-east1, us-central1, us-west1 only |
| Disk | 30 GB standard persistent disk |

**Key point:** The limit is **total hours across all e2-micro instances**, not per instance. One instance running 24/7 uses 744 hours = exactly the free allowance. Two instances would exceed it.

**Scaling:** There is no scaling. An e2-micro VM is always-on. Cost is fixed regardless of traffic. No knobs to turn.

**Constraints to stay free:**

- Run **only 1** e2-micro in total (across all projects in the billing account, in free regions)
- Use **us-east1**, **us-central1**, or **us-west1**
- Use standard disk, ≤30 GB
- Avoid: extra disks, premium OS images, GPUs, static IP when VM is stopped (check current rules)

---

### Summary: How Tightly Can You Constrain?

| Option | Scaling constraint | Billing risk |
|-------|--------------------|--------------|
| **Cloud Run** | `max-instances=1`, `concurrency=1`, `cpu=0.08`, `memory=256Mi` | May briefly exceed 1 instance during spikes/deploys; free tier (2M req, 360K GiB-s) is generous for low traffic |
| **e2-micro** | No scaling; fixed 1 VM | Zero scaling risk; fixed cost if within free tier |

**Both:** Use budget + Pub/Sub + disable-billing function as the only hard cost cap.

---

## 5. Next Steps

1. **Choose**: Cloud Run (simplest name service) or e2-micro (always-on, more control).
2. **If Cloud Run**: Deploy DMZ image with `--max-instances=1`, `--cpu 0.08`, `--memory 256Mi`, `--concurrency 1`, use the `*.run.app` URL.
3. **If e2-micro**: Create VM in free-tier region (us-east1/us-central1/us-west1), deploy container, add DNS (DuckDNS or own domain).
4. **Cost cap**: Set up budget + Pub/Sub + Cloud Function to disable billing at threshold (see [Safest Strategy](#safest-strategy-to-cap-max-cost)).
