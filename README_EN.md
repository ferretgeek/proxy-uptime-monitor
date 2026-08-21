![Proxy uptime monitor — probe through the real route before calling it healthy](docs/images/social-preview.png)

# Proxy uptime monitor

[中文](README.md) · English

[![CI](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/codeql.yml/badge.svg)](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/codeql.yml)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-2f855a.svg)](LICENSE)

> Not a ping panel. It builds a real proxy route and checks whether the destination actually loads.

## Why this exists

You have dozens of nodes in a subscription. The panel shows all green. ChatGPT still won't open.

The failure is rarely "the node is dead" — it's one specific layer: DNS is poisoned, the TLS handshake fails, the connection works but the destination refuses it, or a page comes back and it's a challenge wall. Typical speed-test tools check whether TCP connects and how much latency there is. **That layer working says nothing about whether the service you want is usable.**

So this tool works differently: **for every node it checks, it spins up a short-lived, isolated sing-box route, sends the request through it**, and judges the result from DNS, TCP, TLS, redirects, response timing, and page content — so you learn *which layer* broke.

## Interface

![Interface generated from synthetic node data](docs/images/dashboard.png)

The preview uses node, subscription, and status data generated from scratch — no real subscription, exit address, account, server, or device identity.

## What it does

- **Subscription management** — add, edit, delete, enable/disable, auto-refresh, with automatic redaction on display.
- **Understands the formats** — Base64 URI, Clash YAML (with event-count, depth, and expansion guards), and sing-box JSON; node protocols cover SS, VMess, VLESS, Trojan, Hysteria2, TUIC, SOCKS, HTTP, and AnyTLS.
- **Check at any granularity** — a whole subscription, all nodes, a selected batch, or one specific node.
- **Configurable destinations** — Google, ChatGPT, and Grok by default; X, Claude, Wikipedia, GitHub, Node.js, Python, Perplexity, YouTube, Nexus Mods, Hugging Face, Cloudflare, and Linux.do are opt-in. Upgrades never change your existing selection.
- **Won't melt the machine** — timeouts, retries, random jitter, dynamic concurrency, and a bounded queue; offline nodes back off instead of retrying forever.
- **Legible conclusions** — health scores and uptime are expressed as explicit numbers, icons, labels, and horizontal progress, **not vague colored dots.**

## Running locally

Local mode binds `localhost` only, keeps data, logs, and runtime keys in a git-ignored `.local-run/`, and touches no system services.

Install the Python dependencies and sing-box, then:

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

## Worth noting technically

**Every check is an isolated, real route.** Checking a node spins up a dedicated short-lived sing-box tunnel that is destroyed once the request completes. Nodes never share an exit, so one node's misbehavior can't contaminate another's verdict.

**Layered diagnosis instead of a boolean.** DNS resolution, TCP connect, TLS handshake, the HTTP redirect chain, response timing, and final page characteristics are evaluated separately — so a result can be "TLS fine, destination returned a challenge wall" rather than a flat "failed."

**Subscription parsing is defensive.** Clash YAML has event-count, nesting-depth, and expansion guards, because YAML anchor expansion can be crafted into a decompression bomb. A file fetched from a public subscription URL should not be able to take down your process.

**Resources are fenced by cgroup.** The main process and every temporary probe process share one restricted cgroup: 75% of a single core, 768 MiB memory cap, low CPU/IO weight, reduced process priority, and at most three concurrent node checks by default. It's a long-running service and shouldn't compete with the rest of your box.

**It doesn't touch the system.** One standalone `systemd` unit. No Docker, no transparent proxy, no changes to routing, DNS, firewall rules, or any existing service.

**Sessions and sign-in are tightened.** Server-side sessions with a fixed 30-day lifetime, CSRF protection, client binding, origin and Host validation, login rate limiting, immediate invalidation on sign-out, and encrypted sensitive configuration.

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
