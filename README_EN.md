# Trailmark: Real-World Availability Monitoring for Proxy Subscriptions

[简体中文](README.md) · [English](README_EN.md)

[![CI](https://github.com/ferretgeek/Trailmark/actions/workflows/ci.yml/badge.svg)](https://github.com/ferretgeek/Trailmark/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ferretgeek/Trailmark/actions/workflows/codeql.yml/badge.svg)](https://github.com/ferretgeek/Trailmark/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-2f855a.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](https://www.python.org/)

![Trailmark interface and node-monitoring overview](docs/images/social-preview.png)

Trailmark is not a ping dashboard. Every check launches a short-lived, isolated
sing-box tunnel for the selected node and reaches the configured destinations
through that tunnel. DNS, TCP, TLS, redirects, response time, and page features
are evaluated together to determine whether the destination was actually
reached.

Current open-source version: `2.4.1`. Original project code is released under
the [MIT License](LICENSE). Third-party icons, flags, and service marks retain
their own licenses or rights; see [Third-Party Notices](THIRD_PARTY_NOTICES.md).

> This repository contains source code, migrations, tests, deployment scripts,
> and sanitized documentation only. It contains no live subscription, node
> credential, administrator password, database, log, or server connection data.

## Quick start

### Run locally

Local mode binds only to `localhost` and stores its data, logs, and generated
runtime secrets in the ignored `.local-run/` directory. Install the Python
dependencies and sing-box, then run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\run-local.py --sing-box "C:\path\to\sing-box.exe"
```

On Linux or macOS, use
`.venv/bin/python scripts/run-local.py --sing-box /path/to/sing-box`. The first
launch asks you to create a local administrator with a password of at least 14
characters. Copy the entire `.local-run/` directory when migrating local data;
never commit or share it.

### Deploy to a Linux server

Production deployment targets a Linux host with `systemd`. The installer
creates a dedicated system user, hardened services, health checks, and storage
guards. Build a source archive and a protected administrator-password file:

```bash
tar -czf /tmp/airport-monitor-release.tar.gz \
  --exclude='*/__pycache__' --exclude='*.pyc' \
  .env.example app deploy docs scripts README.md README_EN.md LICENSE \
  SECURITY.md THIRD_PARTY_NOTICES.md requirements.txt requirements-dev.txt
umask 077
openssl rand -base64 24 > /tmp/airport-monitor-admin-password
```

Install it on the target host:

```bash
sudo bash scripts/install.sh \
  --archive /tmp/airport-monitor-release.tar.gz \
  --bind-host <SERVER_LAN_IP> \
  --admin-password-file /tmp/airport-monitor-admin-password \
  --port 18080
```

Transfer the generated password to a password manager after the first successful
sign-in, then remove the temporary server file. The Windows helper
`scripts/New-DeploymentCredential.ps1` can also generate a strong password and
a restricted credential file. See [Deployment and Operations](docs/部署与运维.md)
for installation, updates, backup, restore, and removal. Do not expose the
management interface directly to the public Internet.

## What it does

- Adds, edits, removes, enables, refreshes, and safely redacts subscriptions.
- Parses Base64 URI lists, Clash YAML, sing-box JSON, and SS, VMess, VLESS,
  Trojan, Hysteria2, TUIC, SOCKS, HTTP, and AnyTLS nodes.
- Checks an entire subscription, all nodes, a batch, or one selected node.
- Checks Google, ChatGPT, and Grok by default, with X, Claude, Wikipedia,
  GitHub, Node.js, Python, Perplexity, YouTube, Nexus Mods, Hugging Face,
  Cloudflare, and Linux.do available as optional destinations.
- Uses timeouts, retries, jitter, adaptive concurrency, and a bounded queue;
  offline nodes continue to receive full recovery checks every ten minutes.
- Distinguishes healthy, login-required, region-restricted, service-blocked,
  abnormal-response, uncertain, DNS/TCP/TLS/proxy-error, and unreachable states.
- Treats an anti-bot challenge as evidence that the destination responded; it
  does not create a misleading separate health state.
- Tracks continuous uptime, time-weighted 24-hour/7-day/30-day availability,
  coverage, confidence, average/P50/P95 latency, service status, ranking,
  trends, events, and host resource metrics.
- Separates full **node → website** latency from **local monitor → node**
  protocol-path latency. The latter performs three complete proxy requests to
  a lightweight `204` destination and uses the median; a raw CDN or Anycast TCP
  handshake never replaces the product metric.
- Provides dense node tables, country and flag views, search, filters,
  pagination, batch retesting, direct enable/disable controls, independent
  trend expansion, and persistent resizable desktop columns.
- Shows enabled nodes only on the dashboard and samples whole-host CPU, memory,
  system-disk use, CPU Package temperature, and SMART disk temperature every 60
  seconds. Missing sensors are reported explicitly.
- Resolves the exit location through the node and updates the stored redacted
  result only when at least two independent public sources agree.
- Supports task pausing, manual retests, safe CSV export, and generic Webhook
  notifications.
- Tracks the monitor's network-link state every 30 seconds, pauses node blame
  while the monitor is offline, and runs a full recovery check after reconnect.
- Uses SQLite WAL, query indexes, 20 days of raw data, 180 days of hourly
  aggregates, and automatic retention cleanup.
- Enforces log and total-storage soft/hard limits from both the application and
  independent system timers.
- Provides three complete light themes—Sky, Jade, and Sunset—plus a deep-gray
  dark theme from the persistent top-right global theme picker. All pages,
  dialogs, tables, charts, and states share the same design tokens, responsive
  behavior, keyboard focus, and reduced-motion support.
- Protects the server with fixed 30-day sessions, CSRF defense, client binding,
  Origin and Host validation, login throttling, explicit logout invalidation,
  and encrypted sensitive configuration.

## Interface preview

![Trailmark desktop dashboard generated with synthetic node data](docs/images/dashboard.png)

The preview is generated entirely from synthetic subscriptions, nodes, and
statuses. It contains no live subscription, exit address, account, server, or
device identity. The application ships brand-consistent SVG and ICO browser
icons, verified through both local and server routes.

## Runtime architecture

Production uses one restricted `systemd` service. It does not install Docker,
create a transparent proxy, or modify host routing, DNS, firewall rules, or
existing services. The main process and temporary check processes share one
restricted cgroup with conservative CPU, memory, I/O, and concurrency limits.

| Content | Default location |
|---|---|
| Current release | `/opt/airport-monitor/current` |
| Versioned releases | `/opt/airport-monitor/releases` |
| SQLite data | `/var/lib/airport-monitor` |
| Encrypted configuration | `/etc/airport-monitor/env` |
| Application logs | `/var/log/airport-monitor` |
| Backups | `/var/backups/airport-monitor` |

The detailed security model is documented in
[Technical and Security Design](docs/技术与安全设计.md).

## Development verification

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

On Linux or macOS, replace the interpreter path with `.venv/bin/python`.
Environment fields are documented in `.env.example`. Hardware label variables
are display-only; live utilization and temperature values always come from the
system sampler. Never store real credentials, subscriptions, or administrator
passwords in source code.

## Contributing and security

Run the full test suite before submitting changes and never attach live
subscriptions, node configurations, databases, logs, screenshots, or local
credential files. See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities
privately according to [SECURITY.md](SECURITY.md), not in a public issue.
