# Proxy Availability Monitor

[中文](README.md) · English

Check whether your proxy nodes can reach sites such as ChatGPT and Google, and see which connection step failed.

**Requirements:** your own nodes or subscriptions, Python 3.12+, and sing-box. Run locally or deploy on Linux; no ready-made installer is published.

[Run locally](#running-locally) · [Deploy on Linux](#linux-server-deployment) · [Features](#what-it-does) · [Usage and maintenance](docs/部署与运维.md)

## What it does

- **Check real requests:** each node gets a separate short-lived sing-box route to the target, with DNS, TCP, TLS, redirects, timing, and page characteristics evaluated separately.
- **Manage subscriptions:** add, edit, delete, enable/disable, and auto-refresh with redacted display; check a subscription, all nodes, a selected batch, or one node.
- **Read common formats and protocols:** Base64 URI, Clash YAML, and sing-box JSON; SS, VMess, VLESS, Trojan, Hysteria2, TUIC, SOCKS, HTTP, and AnyTLS.
- **Choose target sites:** Google, ChatGPT, and Grok by default; X, Claude, Wikipedia, GitHub, Node.js, Python, Perplexity, YouTube, Nexus Mods, Hugging Face, Cloudflare, and Linux.do are opt-in. Upgrades preserve existing selections.
- **Review results:** health scores, uptime, response timing, and layered diagnostics distinguish connection failures from destination challenge pages.
- **Limit probe load:** timeouts, retries, random jitter, dynamic concurrency, a bounded queue, and offline-node backoff; Clash YAML parsing limits event count, depth, and expansion.

## Interface

![Interface generated from synthetic node data](docs/images/dashboard.png)

The preview uses node, subscription, and status data generated from scratch — no real subscription, exit address, account, server, or device identity.

## Running locally

Local mode binds `localhost` only, keeps data, logs, and runtime keys in a git-ignored `.local-run/`, and touches no system services.

Install Python 3.12+ and sing-box, choose **Code → Download ZIP** on the repository page, extract it, and open PowerShell in the source root. The [v2.4.1 release](https://github.com/ferretgeek/proxy-uptime-monitor/releases/tag/v2.4.1) also provides a versioned source archive, but has no installer attachment.

Install Python dependencies and start the app:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\run-local.py --sing-box "C:\path\to\sing-box.exe"
```

On Linux / macOS use `.venv/bin/python scripts/run-local.py --sing-box /path/to/sing-box`.

First launch creates a local admin password of at least 14 characters in the terminal. To migrate data, copy the whole `.local-run/` directory — **never commit or share it.**

## Linux server deployment

Production targets a Linux host with `systemd`. The installer creates a dedicated system user, a restricted unit, health checks, and capacity guards.

Build the release archive and admin password file from the source root:

```bash
tar -czf /tmp/airport-monitor-release.tar.gz \
  --exclude='*/__pycache__' --exclude='*.pyc' \
  .env.example app deploy docs scripts README.md README_EN.md LICENSE \
  SECURITY.md THIRD_PARTY_NOTICES.md requirements.txt requirements-dev.txt
umask 077
openssl rand -base64 24 > /tmp/airport-monitor-admin-password
```

Then install:

```bash
sudo bash scripts/install.sh \
  --archive /tmp/airport-monitor-release.tar.gz \
  --bind-host <server-lan-ip> \
  --admin-password-file /tmp/airport-monitor-admin-password \
  --port 18080
```

Log in **immediately** using that password file, move the password into a password manager, confirm you can sign in, and only then delete the temporary file from the server. On Windows, `scripts/New-DeploymentCredential.ps1` generates a random password and a restricted credential file.

Full install, update, backup, restore, and uninstall procedures are in [operations](docs/部署与运维.md). **Read the [security policy](SECURITY.md) before a first public deployment and confirm the bind address isn't exposed to the internet.**

## Technical details

**Every check is an isolated, real route.** Checking a node spins up a dedicated short-lived sing-box tunnel that is destroyed once the request completes. Nodes never share an exit, so one node's misbehavior can't contaminate another's verdict.

**Layered diagnosis instead of a boolean.** DNS resolution, TCP connect, TLS handshake, the HTTP redirect chain, response timing, and final page characteristics are evaluated separately — so a result can be "TLS fine, destination returned a challenge wall" rather than a flat "failed."

**Subscription parsing is defensive.** Clash YAML has event-count, nesting-depth, and expansion guards, because YAML anchor expansion can be crafted into a decompression bomb. These limits control resource use from untrusted subscription content.

**Probe processes have resource limits.** The main process and every temporary probe process share one restricted cgroup: 75% of a single core, 768 MiB memory cap, low CPU/IO weight, reduced process priority, and at most three concurrent node checks by default. These defaults reduce the impact of long-running monitoring on other services.

**Deployment scope.** A standalone `systemd` service and its runtime directories. No Docker, no transparent proxy, no changes to routing, DNS, firewall rules, or any existing service.

**Login and session protection.** Server-side sessions with a fixed 30-day lifetime, CSRF protection, client binding, origin and Host validation, login rate limiting, immediate invalidation on sign-out, and encrypted sensitive configuration.

### File locations

| Contents | Location |
|---|---|
| Current build | `/opt/airport-monitor/current` |
| Release directory | `/opt/airport-monitor/releases` |
| SQLite data | `/var/lib/airport-monitor` |
| Encrypted config | `/etc/airport-monitor/env` |
| Application logs | `/var/log/airport-monitor` |
| Backups | `/var/backups/airport-monitor` |

Probe methodology and security boundaries are documented in [technical and security design](docs/技术与安全设计.md).

## What it doesn't do

- It isn't a proxy client — it never carries your browsing traffic, only temporary probe routes.
- It doesn't supply nodes, subscriptions, or proxy service of any kind.
- It isn't a throughput leaderboard (that's a different tool).
- It doesn't modify system routing, DNS, or firewall rules.

## Local verification

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Linux / macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Environment variables are listed in `.env.example`. `AIRPORT_HARDWARE_CPU`, `AIRPORT_HARDWARE_MEMORY`, and `AIRPORT_HARDWARE_DISK` only label the device model; live utilization and temperature still come from system sampling. **Never put real keys, subscription URLs, or admin passwords in source.**

## Contributing

Run the full test suite before submitting, and keep real subscriptions, node configs, databases, logs, screenshots, and env files out of the repository. See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately per [SECURITY.md](SECURITY.md) — never disclose exploitable details or real credentials in a public issue.

## License

[MIT License](LICENSE) — free to use, modify, and distribute.

Third-party icons are from Lucide (license text at `app/static/vendor/LUCIDE-LICENSE.txt`); regional flags come from the MIT-licensed flag-icons (license text at `app/static/flags/LICENSE-flag-icons.txt`). Other notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

> This repository contains only source, migrations, tests, deployment scripts, and redacted documentation — no real subscriptions, node credentials, admin passwords, databases, runtime logs, or server connection details.
