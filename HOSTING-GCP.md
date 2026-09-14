# Hosting ED LawBase on a free Google Cloud VM

This gives officers a URL with a login page, at **$0/month, forever** — Google's "Always Free" e2-micro VM has been unchanged since 2017 and includes a real persistent disk, unlike every "free tier" that dropped out during the hosting comparison (Render, Fly.io, Koyeb) or got quietly cut mid-2026 (Oracle).

The trade-off against paying for Render: this is a real server you (briefly) administer, not a one-click platform. Budget **30-40 minutes** for the one-time setup below. After that, it runs unattended.

**A card is required to create a Google Cloud account** (identity verification) — **you will not be charged** as long as you stay within the limits this guide sets you up in (1 e2-micro VM, one region, a Standard — not SSD — disk, ≤30GB).

---

## Part A — Create the VM (in the Google Cloud Console, in your browser)

1. Go to **console.cloud.google.com** and sign in / create an account. Accept the free-trial prompt if shown (you won't need the trial credit for this).
2. Top bar → **Select a project → New Project**. Name it `ed-lawbase`, create it, and make sure it's selected.
3. Left menu → **Compute Engine → VM instances**. First visit prompts you to "Enable" the Compute Engine API — click it and wait ~1 minute.
4. **Create Instance**, and set exactly these fields (anything not mentioned, leave default):
   - **Name:** `ed-lawbase`
   - **Region:** `us-central1` (Iowa) — must be this, `us-west1`, or `us-east1`; only these three qualify for the free e2-micro.
   - **Machine configuration → Series:** `E2` → **Machine type:** `e2-micro`
   - **Boot disk** → click **Change**: OS = **Debian**, Version = **Debian 12 (bookworm)**, Boot disk type = **Standard persistent disk** (not SSD or Balanced — those are not free), Size = **30 GB**. Click **Select**.
   - **Firewall:** tick **Allow HTTP traffic** and **Allow HTTPS traffic**.
5. Click **Create**. Wait ~30 seconds for the VM to start.
6. Back on the VM instances list, click **Reserve a static external IP address** (or: VPC network → IP addresses → Reserve External Static Address → attach it to the `ed-lawbase` VM). A static IP costs nothing while it's attached to a running VM — it only costs money if reserved but unused. Note this IP address; call it `YOUR_VM_IP` below.

## Part B — Set up the server (paste commands, one block at a time)

7. On the VM instances list, click the **SSH** button next to `ed-lawbase` — this opens a terminal in your browser, already connected. Everything from here is pasted into that window.

8. **Install what's needed** (paste as one block):
```bash
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv git curl debian-keyring debian-archive-keyring apt-transport-https
python3 -m pip install --break-system-packages --quiet python-docx
```

9. **Install Caddy** (gives you real HTTPS automatically, no domain needed — it uses your IP address itself as the hostname via the free `sslip.io` service):
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -qq && sudo apt-get install -y caddy
```

10. **Get the code**:
```bash
cd ~ && git clone https://github.com/ajay1694-max/ed-lawbase.git
cd ed-lawbase && python3 app/update.py
```
This downloads and verifies the ~230MB database (takes a minute or two — it's the same mechanism already tested against the GitHub release).

11. **Set your admin password and session secret**, and create the systemd service that keeps LawBase running (replace `PICK_A_STRONG_PASSWORD` and `PICK_A_LONG_RANDOM_STRING` — do this now, in this paste, don't leave the placeholders):
```bash
sudo tee /etc/systemd/system/ed-lawbase.service > /dev/null <<'UNIT'
[Unit]
Description=ED LawBase
After=network.target

[Service]
User=YOUR_LINUX_USERNAME
WorkingDirectory=/home/YOUR_LINUX_USERNAME/ed-lawbase
Environment=PORT=8080
Environment=LAWBASE_ADMIN_PASSWORD=PICK_A_STRONG_PASSWORD
Environment=LAWBASE_SECRET=PICK_A_LONG_RANDOM_STRING
ExecStart=/usr/bin/python3 app/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
```
Replace `YOUR_LINUX_USERNAME` with the output of running `whoami` (two places in the block above) before pasting, and fill in the two secrets. Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ed-lawbase
sudo systemctl status ed-lawbase --no-pager   # should say "active (running)"
```

12. **Point Caddy at it**, using your VM's IP via sslip.io so you get a real `https://` link with no domain purchase:
```bash
echo "YOUR_VM_IP.sslip.io {
    reverse_proxy localhost:8080
}" | sudo tee /etc/caddy/Caddyfile
sudo systemctl restart caddy
```
Replace `YOUR_VM_IP` with the static IP from step 6, e.g. if it's `34.123.45.67`, the line reads `34.123.45.67.sslip.io { ... }`.

13. **Open it**: `https://YOUR_VM_IP.sslip.io/` — the first load may take ~20-30 seconds while Caddy fetches its certificate. You should land on the sign-in page. Log in as `admin` with the password you set in step 11, and add officer accounts from the **Admin** link, exactly as described in `HOSTING.md`.

---

## Day-to-day

- **Adding/removing officers, resetting passwords:** same Admin page as the Render setup — nothing here differs.
- **Updating the case-law data** after a new release: SSH in again and run:
  ```bash
  cd ~/ed-lawbase && rm data/lawbase.sqlite && python3 app/update.py && sudo systemctl restart ed-lawbase
  ```
- **If the VM ever reboots** (rare, e.g. a Google maintenance event): the systemd service and Caddy both restart automatically — no action needed.
- **Staying in the free tier:** don't change the machine type away from `e2-micro`, don't add a second VM in your project, don't switch the disk to SSD/Balanced, and keep the disk at or under 30GB. One static IP attached to one running VM is free.

## What stays off this VM

The internal pack (`ed-lawbase-internal`) is never deployed here — same rule as the Render path. This VM only ever serves the public repository's data.
