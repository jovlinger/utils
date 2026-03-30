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

## 5. Next Steps

1. **Choose**: Cloud Run (simplest name service) or e2-micro (always-on, more control).
2. **If Cloud Run**: Deploy DMZ image with `--max-instances=1`, `--cpu 0.08`, `--memory 256Mi`, `--concurrency 1`, use the `*.run.app` URL.
3. **If e2-micro**: Create VM in free-tier region (us-east1/us-central1/us-west1), deploy container, add DNS (DuckDNS or own domain).
4. **Cost cap**: Set up budget + Pub/Sub + Cloud Function to disable billing at threshold (see [Safest Strategy](#safest-strategy-to-cap-max-cost)).
