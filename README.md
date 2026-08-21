![代理节点体检 — 真的走一遍代理再判断](docs/images/social-preview.png)

# 代理节点体检

中文 · [English](README_EN.md)

[![CI](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/codeql.yml/badge.svg)](https://github.com/ferretgeek/proxy-uptime-monitor/actions/workflows/codeql.yml)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-2f855a.svg)](LICENSE)

> 不是 ping 一下就说"通"。它真的建一条代理通道走过去，看目标页面到底能不能打开。

## 为什么会需要它

订阅里几十个节点，面板上全是绿的，但 ChatGPT 就是打不开。

原因通常不在"节点死了"，而在中间某一层：DNS 被污染了、TLS 握不上手、能连上但被目标站点拒了、或者页面回来了但是一张验证墙。常见的测速工具只看 TCP 能不能连、延迟多少——**那一层通了，不代表你要用的服务能用。**

这个工具的做法是：**每检测一个节点，就为它单起一条短生命周期、相互隔离的 sing-box 代理通道，通过那条通道去访问你启用的目标站点**，然后综合 DNS、TCP、TLS、跳转、响应耗时和页面特征来判断"到底哪一层坏了"。

## 界面

![合成节点数据生成的界面](docs/images/dashboard.png)

预览使用从零生成的节点、订阅和状态数据，不含真实订阅、出口地址、账号、服务器或设备身份。

## 它能做什么

- **订阅管理** — 添加、编辑、删除、启停、自动刷新，展示时自动脱敏。
- **认得懂各种格式** — Base64 URI、Clash YAML（带事件数 / 深度 / 展开量保护）、sing-box JSON；节点协议覆盖 SS、VMess、VLESS、Trojan、Hysteria2、TUIC、SOCKS、HTTP 和 AnyTLS。
- **检测粒度自选** — 整份订阅、全部节点、批量勾选，或者只测某一个节点。
- **目标站点可配** — 默认检测 Google、ChatGPT 和 Grok；X、Claude、Wikipedia、GitHub、Node.js、Python、Perplexity、YouTube、Nexus Mods、Hugging Face、Cloudflare、Linux.do 可以自己勾。升级不会替你改动已有选择。
- **不会打爆机器** — 超时、重试、随机抖动、动态并发和有界队列；离线节点会退避而不是反复重试。
- **看得清结论** — 健康评分和在线率用明确数值、图标、中文标签和横向进度条表达，**不用含糊的彩色小圆点糊过去**。

## 本机运行

本机模式只监听 `localhost`，数据、日志和运行密钥都放在被 Git 忽略的 `.local-run/` 里，不修改任何系统服务。

先装好 Python 依赖和 sing-box，然后：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\run-local.py --sing-box "C:\path\to\sing-box.exe"
```

Linux / macOS 用 `.venv/bin/python scripts/run-local.py --sing-box /path/to/sing-box`。

首次启动会在终端里创建一个至少 14 位的本地管理员密码。需要迁移数据就整个复制 `.local-run/`——**不要提交或分享这个目录。**

## Linux 服务器部署

生产部署面向带 `systemd` 的 Linux 主机。安装脚本会创建独立系统用户、受限服务、健康检查和容量保护。

先在源码根目录生成发布包和管理员密码文件：

```bash
tar -czf /tmp/airport-monitor-release.tar.gz \
  --exclude='*/__pycache__' --exclude='*.pyc' \
  .env.example app deploy docs scripts README.md README_EN.md LICENSE \
  SECURITY.md THIRD_PARTY_NOTICES.md requirements.txt requirements-dev.txt
umask 077
openssl rand -base64 24 > /tmp/airport-monitor-admin-password
```

然后安装：

```bash
sudo bash scripts/install.sh \
  --archive /tmp/airport-monitor-release.tar.gz \
  --bind-host <服务器局域网IP> \
  --admin-password-file /tmp/airport-monitor-admin-password \
  --port 18080
```

装完**立刻**用那个密码文件登录一次，把密码转移到密码管理器，确认能登录之后再删掉服务器上的临时密码文件。Windows 管理端也可以用 `scripts/New-DeploymentCredential.ps1` 生成随机密码和受限凭据文件。

完整安装、更新、备份、恢复与卸载流程见[部署与运维](docs/部署与运维.md)。**首次公开部署前请先读[安全策略](SECURITY.md)，并确认监听地址没有直接暴露到公网。**

## 技术上值得一提的地方

**每次检测都是一条隔离的真实链路。** 检测某个节点时，程序为它单独拉起一条短生命周期的 sing-box 通道，请求走完就销毁。节点之间不共享出口，所以一个节点的异常不会污染另一个节点的结论。

**分层诊断，而不是一个布尔值。** DNS 解析、TCP 连接、TLS 握手、HTTP 跳转链、响应耗时和最终页面特征分别判定——所以结论可以是"TLS 正常但目标站点返回了验证墙"，而不是笼统的"失败"。

**订阅解析是防御性的。** Clash YAML 有事件数、嵌套深度和展开量三重保护——YAML 的锚点展开是可以被构造成解压炸弹的，一个从公开订阅链接拿到的文件不该有能力打爆你的进程。

**整机资源被 cgroup 框住。** 主进程和所有临时检测进程在同一个受限 cgroup 里：CPU 单核配额上限 75%、内存上限 768 MiB、低 CPU/IO 权重、较低进程优先级，默认最多同时检测 3 个节点。它是长期挂着的服务，不该跟你的其他服务抢资源。

**不动系统。** 只装一个独立 `systemd` 服务：不装 Docker、不建透明代理、不改服务器路由、DNS、防火墙或任何已有服务。

**会话与登录是收紧的。** 30 天固定有效期的服务端会话、CSRF、客户端绑定、来源与 Host 校验、登录限速、主动退出即失效，敏感配置加密存储。

### 文件位置

| 内容 | 位置 |
|---|---|
| 当前程序 | `/opt/airport-monitor/current` |
| 版本目录 | `/opt/airport-monitor/releases` |
| SQLite 数据 | `/var/lib/airport-monitor` |
| 加密配置 | `/etc/airport-monitor/env` |
| 应用日志 | `/var/log/airport-monitor` |
| 备份 | `/var/backups/airport-monitor` |

检测原理与安全边界见[技术与安全设计](docs/技术与安全设计.md)。

## 它不做什么

- 不是代理客户端——它不接管你的上网流量，只在检测时临时建通道。
- 不提供节点、订阅或任何形式的代理服务。
- 不做速度跑分排行（那是另一类工具）。
- 不修改系统路由、DNS 或防火墙。

## 本地验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Linux / macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

环境变量见 `.env.example`。`AIRPORT_HARDWARE_CPU`、`AIRPORT_HARDWARE_MEMORY` 和 `AIRPORT_HARDWARE_DISK` 只用于展示设备型号，实时占用和温度仍来自系统采样。**真实密钥、订阅链接和管理员密码不得写入源码。**

## 参与贡献

提交前请跑完整测试，并且不要把真实订阅、节点配置、数据库、日志、截图或环境文件加进仓库。约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 里披露可利用细节或真实凭据。

## 许可

[MIT License](LICENSE)，可自由使用、修改与分发。

第三方图标使用 Lucide（授权文本 `app/static/vendor/LUCIDE-LICENSE.txt`），地区国旗来自 MIT 授权的 flag-icons（授权文本 `app/static/flags/LICENSE-flag-icons.txt`），其余第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

> 本仓库只包含程序源码、迁移、测试、部署脚本和脱敏文档，不含任何真实订阅、节点凭据、管理员密码、数据库、运行日志或服务器连接信息。
