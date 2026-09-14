# Hosting ED LawBase on a Google Cloud e2-micro VM

This puts the app at a URL with a login page, and costs **about US$3.60–3.72/month** — roughly half the cost of Render. That estimate assumes normal usage stays within the free data allowance.

## What it costs, exactly

| Item | Cost | Source |
|---|---|---|
| e2-micro VM in us-central1 / us-west1 / us-east1 | Free (Always Free tier) | [GCP Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features) |
| 30 GB standard persistent disk | Free (Always Free tier) | same |
| **External IPv4 address** | **US$0.005/hour ≈ US$3.60–3.72/month — NOT covered by the free tier** | [GCP external IP pricing](https://cloud.google.com/vpc/pricing-announce-external-ips) |
| Outbound data, first 1 GB/month | Free | [GCP Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features) |
| Outbound data beyond 1 GB/month (to India) | ≈ US$0.12/GiB | [GCP network pricing](https://cloud.google.com/vpc/network-pricing) |

An earlier version of this file called the setup "$0 forever". **That was wrong**: every VM that is publicly reachable needs an external IPv4 address, and Google charges for it.

**Data usage.** Five officers each opening about 20 judgments per working day is estimated at 150–400 MB/month, which is under the free 1 GB. Heavy review of long judgments could exceed it, but every additional 5 GiB costs only about US$0.60.

**The deploy script creates a monthly budget of 1 unit of your billing currency**, with alerts at 1%, 50% and 100%. Budget alerts are notifications that arrive with a delay. **They do not cap spending.**

## Deploying — the script does it

The steps are scripted in `deploy/deploy-gcp.ps1`. Codex drafted it through the cross-agent bridge on 14.09.2026, and Claude reviewed it and fixed two bugs.

**Ajay alone does steps 1–4.** They need his own Google login and card.

1. Create or sign in to a Google account at console.cloud.google.com.
2. Create a project (e.g. `ed-lawbase`) and attach a billing account to it.
3. In PowerShell, run the script once with no flags. If `gcloud` is missing, it installs the Google Cloud CLI through winget and then stops:
   ```powershell
   & ".\deploy\deploy-gcp.ps1"
   ```
4. Open a **new** PowerShell window and sign in:
   ```powershell
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

**Then review and deploy.**

5. Run the script again with no flags. It prints the account, the project, the plan and the IPv4 charge, and creates nothing.
6. Deploy:
   ```powershell
   & ".\deploy\deploy-gcp.ps1" -Execute -AcknowledgeExternalIpv4Charge
   ```
7. When prompted, type the **session-signing secret** (at least 32 random characters) and the **initial admin password** (at least 12 characters). Neither is ever written to a file. The secret goes to Google Secret Manager; the password goes over encrypted SSH.
8. Open the `https://<ip>.sslip.io/` URL the script prints. The first load can take 20–30 seconds while the HTTPS certificate is issued. Sign in as `admin` and add officers from the **Admin** link.

### What the script builds

- It installs the Google Cloud CLI if missing, and checks the login, project and attached billing.
- It creates the budget alert **before** any compute resource.
- **Network:** a dedicated VPC and a static IPv4 address. Ports 80 and 443 are open to the public. Port 22 is opened only to the IP of the machine running the script, and closed again when the script finishes. Port 8080 stays private.
- **VM:** an e2-micro running Debian 12, with a 30 GB standard disk and a 2 GB swap file (the VM has only 1 GiB of RAM).
- **App:** runs in a Python virtual environment, not the system Python. The database comes from the GitHub Release through `app/update.py`, with its checksum verified.
- **Services:** systemd runs the app with a hardened unit, and reads the session secret from Secret Manager at start-up. Caddy provides automatic HTTPS for `<ip>.sslip.io` and adds `Secure` to session cookies.

## Day-to-day

- **Officer accounts:** add, remove and reset them on the Admin page.
- **Updating the case-law data after a new release.** SSH in and run the command below. Do not delete the database first: `update.py` verifies the download and replaces the file atomically, so if the download fails the old database stays in place.
  ```bash
  cd ~/ed-lawbase && sudo systemctl stop ed-lawbase && .venv/bin/python app/update.py && sudo systemctl start ed-lawbase
  ```
- **Reboots:** the app and Caddy restart automatically.
- **Staying at ~US$3.65/month:**
  - keep one VM, and keep it e2-micro;
  - keep the disk standard (not SSD or Balanced) and no larger than 30 GB;
  - release the static IP if you ever delete the VM, because a reserved IP that isn't attached to anything is also charged.

## What stays off this VM

Never deploy the internal pack (`ed-lawbase-internal`). This VM serves only the public repository's data.
