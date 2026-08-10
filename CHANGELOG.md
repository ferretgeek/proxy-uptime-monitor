# 更新记录 / Changelog

本项目遵循语义化版本。只记录公开版本中对使用者有影响的变化。

## Unreleased

- 安全强化：维护脚本不再以 shell 载入环境文件，恢复包改为允许清单解包，并以
  低权限账户执行数据库备份与升级验证。
- 为状态变更请求增加解析前正文上限，为 YAML 别名图增加事件、深度与展开预算，
  并在 CSV 导出边界中和电子表格公式前缀。
- Security hardening: maintenance scripts now parse environment files as data,
  restore archives use allowlisted extraction, and database operations run as the
  service account. Request bodies, YAML expansion, and CSV formula prefixes are
  now bounded at their respective trust boundaries.

## 2.4.1 - 2026-08-09

- 将中英文 README 标题统一为“项目名 — 核心功能”，直接说明这是代理节点可用性监控工具。
- Clarified both README titles as “project name — core function” so the proxy-availability purpose is immediately visible.
- 完整重写全部可达历史：第三方扫描器命中的只是测试函数名与专门验证拒绝逻辑的虚构 URL，不是真实秘密。
- 永久退役不可变的 `v2.4.0` 标签，以 `v2.4.1` 重新发布；两个独立引擎对完整历史与全部标签均为零结果。
- 纳入浏览器错误安全渲染、异常脱敏、安全审查修复、界面精修与最终双语文档。

## 2.4.0 - 2026-08-08

- 首次公开发布“航迹 / Trailmark”完整节点观测与服务诊断能力。
- 新增 Windows、macOS 与 Linux 本地运行入口，并修复 Windows 子进程生命周期
  兼容性。
- 新增天际蓝、青岚绿、霞光橙与深灰夜色四套全局主题，以及持久化主题选择。
- 补齐 SVG/ICO 浏览器图标、中英文文档、CI、真实界面预览与社交封面。
- 升级 `cryptography`，完成依赖漏洞、静态安全、秘密与隐私复扫。

---

- First public release of the complete Trailmark node-observability dashboard.
- Added a local runner for Windows, macOS, and Linux, including Windows subprocess
  lifecycle compatibility.
- Added four persistent global themes: Sky, Jade, Sunset, and Deep Gray.
- Added SVG/ICO favicons, bilingual documentation, CI, an authentic UI preview,
  and a social card.
- Upgraded `cryptography` and completed dependency, static-security, secret, and
  privacy audits.
