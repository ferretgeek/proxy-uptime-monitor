# 代理节点可用性监测

中文 · [English](README_EN.md)

批量检查你的代理节点能否访问 ChatGPT、Google 等网站，并查看连接失败发生在哪一步。

**使用条件：** 自备节点或订阅，需要 Python 3.12+ 和 sing-box；可本机运行或部署到 Linux 服务器，没有现成安装包。

[本机运行](#本机运行) · [服务器部署](#linux-服务器部署) · [支持的功能](#它能做什么) · [使用与维护](docs/部署与运维.md)

## 它能做什么

- **检测实际访问结果**：每个节点使用独立的短时 sing-box 代理通道访问目标网站，分别检查 DNS、TCP、TLS、跳转、耗时和页面特征。
- **管理订阅**：添加、编辑、删除、启停和自动刷新，展示时自动脱敏；可检测整份订阅、全部节点、选中批次或单个节点。
- **支持多种格式与协议**：Base64 URI、Clash YAML、sing-box JSON；支持 SS、VMess、VLESS、Trojan、Hysteria2、TUIC、SOCKS、HTTP 和 AnyTLS。
- **选择目标网站**：默认检测 Google、ChatGPT 和 Grok；可勾选 X、Claude、Wikipedia、GitHub、Node.js、Python、Perplexity、YouTube、Nexus Mods、Hugging Face、Cloudflare 和 Linux.do。升级保留已有选择。
- **查看检测结论**：显示健康评分、在线率、响应耗时和分层诊断，区分连接问题与目标网站验证页面。
- **控制检测负载**：超时、重试、随机抖动、动态并发、有界队列和离线节点退避；Clash YAML 解析限制事件数、深度和展开量。

## 界面

![合成节点数据生成的界面](docs/images/dashboard.png)

预览使用从零生成的节点、订阅和状态数据，不含真实订阅、出口地址、账号、服务器或设备身份。

## 本机运行

本机模式只监听 `localhost`，数据、日志和运行密钥都放在被 Git 忽略的 `.local-run/` 里，不修改任何系统服务。

先安装 Python 3.12+ 和 sing-box，从仓库页面选择 **Code → Download ZIP** 并解压，在源码根目录打开 PowerShell。也可从 [v2.4.1 发布页](https://github.com/ferretgeek/proxy-uptime-monitor/releases/tag/v2.4.1) 获取对应版本源码；该发布没有安装包附件。

安装 Python 依赖并启动：

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

## 技术说明

**每次检测都是一条隔离的真实链路。** 检测某个节点时，程序为它单独拉起一条短生命周期的 sing-box 通道，请求走完就销毁。节点之间不共享出口，所以一个节点的异常不会污染另一个节点的结论。

**分层诊断，而不是一个布尔值。** DNS 解析、TCP 连接、TLS 握手、HTTP 跳转链、响应耗时和最终页面特征分别判定——所以结论可以是"TLS 正常但目标站点返回了验证墙"，而不是笼统的"失败"。

**订阅解析是防御性的。** Clash YAML 有事件数、嵌套深度和展开量三重保护——YAML 的锚点展开是可以被构造成解压炸弹的，解析限制用于控制不可信订阅内容的资源消耗。

**检测进程有资源上限。** 主进程和所有临时检测进程在同一个受限 cgroup 里：CPU 单核配额上限 75%、内存上限 768 MiB、低 CPU/IO 权重、较低进程优先级，默认最多同时检测 3 个节点。这些默认限制用于降低长期监测对其他服务的影响。

**部署范围。** 安装独立的 `systemd` 服务及其运行目录：不装 Docker、不建透明代理、不改服务器路由、DNS、防火墙或任何已有服务。

**登录与会话保护。** 30 天固定有效期的服务端会话、CSRF、客户端绑定、来源与 Host 校验、登录限速、主动退出即失效，敏感配置加密存储。

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
