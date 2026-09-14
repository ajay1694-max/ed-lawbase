# deploy-gcp.ps1 - drafted by Codex (bridge fork, 14.09.2026), fixed by Claude after review:
#   C10 admin check read data/users.sqlite; the app writes data/auth.sqlite.
#   C11 PowerShell pipe to gcloud added BOM+CRLF, corrupting the admin password; stripped at source and consumers.
#   C14 file saved LF-only and remote payloads CR-stripped, so bash on Debian never sees a carriage return.
[CmdletBinding()]
param(
    [string]$InstanceName = "ed-lawbase",
    [string]$Zone = "us-central1-a",
    [string]$AddressName = "ed-lawbase-ip",
    [string]$NetworkName = "ed-lawbase-net",
    [string]$SubnetName = "ed-lawbase-subnet",
    [string]$RepoUrl = "https://github.com/ajay1694-max/ed-lawbase.git",
    [switch]$Execute,
    [switch]$AcknowledgeExternalIpv4Charge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# Piping to native commands in Windows PowerShell 5.1 adds a UTF-8 BOM + CRLF; drop the BOM at source.
$OutputEncoding = New-Object System.Text.UTF8Encoding $false

$Region = $Zone -replace '-[a-z]$', ''
$WebTags = "http-server,https-server"
$HttpRule = "$InstanceName-allow-http"
$HttpsRule = "$InstanceName-allow-https"
$TemporarySshRule = "$InstanceName-temporary-ssh"
$ServiceAccountName = "ed-lawbase-vm"
$SessionSecretName = "ed-lawbase-session"
$BudgetDisplayName = "ED LawBase guardrail"

function Find-Gcloud {
    $command = Get-Command gcloud -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $known = @(
        "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )
    foreach ($candidate in $known) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return $null
}

function Install-GcloudIfMissing {
    $gcloud = Find-Gcloud
    if ($gcloud) { return $gcloud }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Google Cloud CLI is absent and winget is unavailable. Install Google Cloud CLI, then rerun this script."
    }

    Write-Host "Google Cloud CLI is absent. Installing winget package Google.CloudSDK ..."
    & $winget.Source install --exact --id Google.CloudSDK --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Google.CloudSDK (exit $LASTEXITCODE)." }

    $gcloud = Find-Gcloud
    if (-not $gcloud) {
        throw "Google Cloud CLI was installed, but this process cannot find gcloud yet. Open a new PowerShell window, run 'gcloud auth login' and 'gcloud config set project PROJECT_ID', then rerun this script."
    }
    return $gcloud
}

$script:Gcloud = Install-GcloudIfMissing

function Invoke-Gcloud {
    param(
        [Parameter(Mandatory)][string[]]$GcloudArguments,
        [switch]$Capture
    )
    if ($Capture) {
        $output = & $script:Gcloud @GcloudArguments
        if ($LASTEXITCODE -ne 0) { throw "gcloud failed: gcloud $($GcloudArguments -join ' ')" }
        return ($output | Out-String).Trim()
    }
    & $script:Gcloud @GcloudArguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed: gcloud $($GcloudArguments -join ' ')" }
}

function Test-GcloudResource {
    param([Parameter(Mandatory)][string[]]$DescribeArguments)
    & $script:Gcloud @DescribeArguments --quiet 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Read-PlainTextSecret {
    param([Parameter(Mandatory)][string]$Prompt)
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Invoke-GcloudWithSecretStdin {
    param(
        [Parameter(Mandatory)][string]$Secret,
        [Parameter(Mandatory)][string[]]$GcloudArguments
    )
    $Secret | & $script:Gcloud @GcloudArguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed while receiving a secret through standard input." }
}

$account = Invoke-Gcloud -Capture -GcloudArguments @("auth", "list", "--filter=status:ACTIVE", "--format=value(account)")
$project = Invoke-Gcloud -Capture -GcloudArguments @("config", "get-value", "project")
if (-not $account) {
    throw "No active Google Cloud login. Ajay must run: gcloud auth login"
}
if (-not $project -or $project -eq "(unset)") {
    throw "No Google Cloud project is selected. Ajay must run: gcloud config set project PROJECT_ID"
}

Write-Host "Active account: $account"
Write-Host "Selected project: $project"
Write-Host "Plan: e2-micro in $Zone; 30GB pd-standard Debian 12; static external IPv4; public TCP 80/443 only."
Write-Warning "Google currently charges an in-use external IPv4 address at USD 0.005/hour (about USD 3.60-3.72/month). The VM, disk and first 1GB outbound transfer can fit the Free Tier; the public IPv4 does not."

if (-not $Execute) {
    Write-Host "No cloud resources were created. Review the plan, then rerun with -Execute -AcknowledgeExternalIpv4Charge."
    exit 0
}
if (-not $AcknowledgeExternalIpv4Charge) {
    throw "Deployment stopped before creating resources. Rerun with -AcknowledgeExternalIpv4Charge after accepting the external IPv4 charge."
}

$sessionSecret = Read-PlainTextSecret "Enter a long random session-signing secret"
if ($sessionSecret.Length -lt 32) { throw "The session-signing secret must be at least 32 characters." }
$adminPassword = Read-PlainTextSecret "Enter the initial admin password"
if ($adminPassword.Length -lt 12) { throw "The initial admin password must be at least 12 characters." }

try {
    Invoke-Gcloud -GcloudArguments @("services", "enable", "compute.googleapis.com", "secretmanager.googleapis.com", "billingbudgets.googleapis.com", "--project=$project")

    $billingName = Invoke-Gcloud -Capture -GcloudArguments @("billing", "projects", "describe", $project, "--format=value(billingAccountName)")
    if (-not $billingName) { throw "Billing is not attached to project $project. Ajay must attach billing before deployment." }
    $billingAccountId = $billingName -replace '^billingAccounts/', ''
    $existingBudget = Invoke-Gcloud -Capture -GcloudArguments @("billing", "budgets", "list", "--billing-account=$billingAccountId", "--filter=displayName='$BudgetDisplayName'", "--format=value(name)")
    if (-not $existingBudget) {
        Invoke-Gcloud -GcloudArguments @(
            "billing", "budgets", "create",
            "--billing-account=$billingAccountId",
            "--display-name=$BudgetDisplayName",
            "--budget-amount=1",
            "--calendar-period=month",
            "--filter-projects=projects/$project",
            "--threshold-rule=percent=0.01",
            "--threshold-rule=percent=0.50",
            "--threshold-rule=percent=1.00"
        )
    }

    $serviceAccountEmail = "$ServiceAccountName@$project.iam.gserviceaccount.com"
    if (-not (Test-GcloudResource -DescribeArguments @("iam", "service-accounts", "describe", $serviceAccountEmail, "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("iam", "service-accounts", "create", $ServiceAccountName, "--display-name=ED LawBase VM", "--project=$project")
    }

    if (-not (Test-GcloudResource -DescribeArguments @("secrets", "describe", $SessionSecretName, "--project=$project"))) {
        Invoke-GcloudWithSecretStdin -Secret $sessionSecret -GcloudArguments @("secrets", "create", $SessionSecretName, "--replication-policy=automatic", "--data-file=-", "--project=$project")
    }
    else {
        Invoke-GcloudWithSecretStdin -Secret $sessionSecret -GcloudArguments @("secrets", "versions", "add", $SessionSecretName, "--data-file=-", "--project=$project")
    }
    Invoke-Gcloud -GcloudArguments @("secrets", "add-iam-policy-binding", $SessionSecretName, "--member=serviceAccount:$serviceAccountEmail", "--role=roles/secretmanager.secretAccessor", "--project=$project", "--quiet")

    if (-not (Test-GcloudResource -DescribeArguments @("compute", "networks", "describe", $NetworkName, "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("compute", "networks", "create", $NetworkName, "--subnet-mode=custom", "--project=$project")
    }
    if (-not (Test-GcloudResource -DescribeArguments @("compute", "networks", "subnets", "describe", $SubnetName, "--region=$Region", "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("compute", "networks", "subnets", "create", $SubnetName, "--network=$NetworkName", "--region=$Region", "--range=10.20.0.0/28", "--project=$project")
    }

    if (-not (Test-GcloudResource -DescribeArguments @("compute", "firewall-rules", "describe", $HttpRule, "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("compute", "firewall-rules", "create", $HttpRule, "--network=$NetworkName", "--direction=INGRESS", "--priority=1000", "--action=ALLOW", "--rules=tcp:80", "--source-ranges=0.0.0.0/0", "--target-tags=http-server", "--project=$project")
    }
    if (-not (Test-GcloudResource -DescribeArguments @("compute", "firewall-rules", "describe", $HttpsRule, "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("compute", "firewall-rules", "create", $HttpsRule, "--network=$NetworkName", "--direction=INGRESS", "--priority=1000", "--action=ALLOW", "--rules=tcp:443", "--source-ranges=0.0.0.0/0", "--target-tags=https-server", "--project=$project")
    }

    if (-not (Test-GcloudResource -DescribeArguments @("compute", "addresses", "describe", $AddressName, "--region=$Region", "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("compute", "addresses", "create", $AddressName, "--region=$Region", "--network-tier=PREMIUM", "--project=$project")
    }
    $staticIp = Invoke-Gcloud -Capture -GcloudArguments @("compute", "addresses", "describe", $AddressName, "--region=$Region", "--format=value(address)", "--project=$project")

    if (-not (Test-GcloudResource -DescribeArguments @("compute", "instances", "describe", $InstanceName, "--zone=$Zone", "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @(
            "compute", "instances", "create", $InstanceName,
            "--zone=$Zone",
            "--machine-type=e2-micro",
            "--image-family=debian-12",
            "--image-project=debian-cloud",
            "--boot-disk-type=pd-standard",
            "--boot-disk-size=30GB",
            "--network-interface=subnet=$SubnetName,address=$staticIp,network-tier=PREMIUM",
            "--tags=$WebTags",
            "--service-account=$serviceAccountEmail",
            "--scopes=https://www.googleapis.com/auth/cloud-platform",
            "--metadata=enable-oslogin=TRUE",
            "--project=$project"
        )
    }

    # Open SSH only from this Windows machine while provisioning; remove the rule in finally.
    $publicIp = (Invoke-RestMethod -UseBasicParsing -Uri "https://api.ipify.org").Trim()
    if ($publicIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "Could not determine this machine's public IPv4 address for temporary SSH access." }
    if (-not (Test-GcloudResource -DescribeArguments @("compute", "firewall-rules", "describe", $TemporarySshRule, "--project=$project"))) {
        Invoke-Gcloud -GcloudArguments @("compute", "firewall-rules", "create", $TemporarySshRule, "--network=$NetworkName", "--direction=INGRESS", "--priority=900", "--action=ALLOW", "--rules=tcp:22", "--source-ranges=$publicIp/32", "--target-tags=http-server", "--project=$project")
    }

    $remoteSetup = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv git curl gpg debian-keyring debian-archive-keyring apt-transport-https openssl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y caddy

if ! sudo swapon --show=NAME | grep -qx '/swapfile'; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null

if [ ! -d "$HOME/ed-lawbase/.git" ]; then
  git clone '__REPO_URL__' "$HOME/ed-lawbase"
else
  git -C "$HOME/ed-lawbase" pull --ff-only
fi
cd "$HOME/ed-lawbase"
python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python app/update.py

REMOTE_USER="$(id -un)"
REMOTE_HOME="$HOME"
sudo tee /usr/local/sbin/ed-lawbase-start >/dev/null <<LAUNCHER
#!/bin/bash
set -euo pipefail
TOKEN=\$(curl -fsS -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
PAYLOAD=\$(curl -fsS -H "Authorization: Bearer \$TOKEN" 'https://secretmanager.googleapis.com/v1/projects/__PROJECT__/secrets/__SECRET_NAME__/versions/latest:access')
export LAWBASE_SECRET=\$(printf '%s' "\$PAYLOAD" | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode("utf-8-sig").rstrip("\r\n"), end="")')
export PORT=8080
exec "$REMOTE_HOME/ed-lawbase/.venv/bin/python" "$REMOTE_HOME/ed-lawbase/app/server.py"
LAUNCHER
sudo chmod 0755 /usr/local/sbin/ed-lawbase-start

sudo tee /etc/systemd/system/ed-lawbase.service >/dev/null <<UNIT
[Unit]
Description=ED LawBase
After=network-online.target
Wants=network-online.target

[Service]
User=$REMOTE_USER
WorkingDirectory=$REMOTE_HOME/ed-lawbase
ExecStart=/usr/local/sbin/ed-lawbase-start
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$REMOTE_HOME/ed-lawbase/data

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
__STATIC_IP__.sslip.io {
    reverse_proxy 127.0.0.1:8080 {
        header_down Set-Cookie "(.*)" "\$1; Secure"
    }
}
CADDY
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable ed-lawbase caddy
'@
    $remoteSetup = $remoteSetup.Replace('__REPO_URL__', $RepoUrl).Replace('__PROJECT__', $project).Replace('__SECRET_NAME__', $SessionSecretName).Replace('__STATIC_IP__', $staticIp)
    $remoteSetup = $remoteSetup -replace "`r", ""
    $encodedSetup = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteSetup))
    $setupCommand = "echo '$encodedSetup' | base64 -d | bash"

    $sshBase = @("compute", "ssh", $InstanceName, "--zone=$Zone", "--project=$project", "--quiet")
    $sshReady = $false
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        & $script:Gcloud @sshBase "--command=true" 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) { $sshReady = $true; break }
        Start-Sleep -Seconds 5
    }
    if (-not $sshReady) { throw "The VM did not become reachable over SSH within one minute." }
    Invoke-Gcloud -GcloudArguments ($sshBase + @("--command=$setupCommand"))

    # The plaintext admin password exists only in memory and on encrypted SSH stdin.
    $bootstrapCommand = @'
set -euo pipefail
IFS= read -r LAWBASE_ADMIN_PASSWORD
LAWBASE_ADMIN_PASSWORD="${LAWBASE_ADMIN_PASSWORD%$'\r'}"
LAWBASE_ADMIN_PASSWORD="${LAWBASE_ADMIN_PASSWORD#$'\xEF\xBB\xBF'}"
export LAWBASE_ADMIN_PASSWORD
cd "$HOME/ed-lawbase"
SESSION_SECRET="$(curl -fsS -H 'Metadata-Flavor: Google' 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
PAYLOAD="$(curl -fsS -H "Authorization: Bearer $SESSION_SECRET" 'https://secretmanager.googleapis.com/v1/projects/__PROJECT__/secrets/__SECRET_NAME__/versions/latest:access')"
export LAWBASE_SECRET="$(printf '%s' "$PAYLOAD" | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode("utf-8-sig").rstrip("\r\n"), end="")')"
export PORT=8080
timeout 5s .venv/bin/python app/server.py >/tmp/ed-lawbase-bootstrap.log 2>&1 || test "$?" -eq 124
unset LAWBASE_ADMIN_PASSWORD LAWBASE_SECRET SESSION_SECRET PAYLOAD
python3 - <<'PY'
import os, sqlite3
p=os.path.expanduser('~/ed-lawbase/data/auth.sqlite')
with sqlite3.connect(p) as c:
    assert c.execute("select count(*) from users where username='admin' and is_admin=1").fetchone()[0] == 1
print('Initial admin account verified.')
PY
sudo systemctl restart ed-lawbase caddy
sudo systemctl is-active --quiet ed-lawbase
sudo systemctl is-active --quiet caddy
curl -fsS -o /dev/null http://127.0.0.1:8080/login.html
'@
    $bootstrapCommand = $bootstrapCommand.Replace('__PROJECT__', $project).Replace('__SECRET_NAME__', $SessionSecretName)
    $bootstrapCommand = $bootstrapCommand -replace "`r", ""
    $encodedBootstrap = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrapCommand))
    $adminPassword | & $script:Gcloud @sshBase "--command=echo '$encodedBootstrap' | base64 -d | bash"
    if ($LASTEXITCODE -ne 0) { throw "Remote admin bootstrap failed." }

    Write-Host "Deployment complete: https://$staticIp.sslip.io/"
    Write-Host "The first certificate request can take 20-30 seconds. Sign in as admin with the password entered above."
}
finally {
    $sessionSecret = $null
    $adminPassword = $null
    if (Test-GcloudResource -DescribeArguments @("compute", "firewall-rules", "describe", $TemporarySshRule, "--project=$project")) {
        Invoke-Gcloud -GcloudArguments @("compute", "firewall-rules", "delete", $TemporarySshRule, "--project=$project", "--quiet")
    }
}
