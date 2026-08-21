# 参与贡献

感谢参与代理节点体检。修改应保持现有安全边界：不创建透明代理、不修改宿主机路由、
DNS 或防火墙，不把订阅与节点秘密写入日志、接口或测试夹具。

## 开发流程

1. 从最新源码创建分支并建立独立虚拟环境。
2. 只修改与目标有关的文件，数据库变更使用新的顺序迁移文件。
3. 为行为变化补充自动化测试；界面变化同时检查桌面与移动端。
4. 提交前执行：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q app
```

如果安装了 Node.js，还应执行：

```bash
node --check app/static/app.js
node --check app/static/theme.js
```

## 提交要求

- 不提交真实订阅、节点 URI、密码、Cookie、Webhook、数据库、日志或生产截图；
- 测试数据使用 `example.com`、保留地址和明确的虚构凭据；
- 不静默吞掉错误，不用伪成功或缺测重加权美化监测结果；
- 保持 SQLite 迁移向前兼容，并在运维文档说明回滚边界；
- 新依赖必须有明确用途、固定版本和兼容的开源许可证；
- 用户界面保持简体中文、键盘可操作、移动端无页面横向溢出。

安全问题请按 `SECURITY.md` 私下报告。
