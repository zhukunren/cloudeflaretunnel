# Cloudflare 内网穿透管理系统

## 项目简介
基于 Cloudflare Tunnel 的内网穿透管理系统，提供现代化图形界面、自动监控和故障恢复功能。

## 功能特性
- 🎨 现代化图形界面管理
- 🔄 自动重连机制（监控服务）
- 📊 实时状态监控
- 🚀 开机自启动（Windows 注册表 / Linux Systemd）
- 📝 详细日志记录
- 🌐 DNS 路由管理
- 🔧 隧道诊断工具

## 环境要求
- **Windows 10/11** 或 **Linux/Unix 系统**（推荐 Ubuntu 20.04+）
- Python 3.8+（Windows 需包含 Tkinter）
- Cloudflared CLI 工具
- Linux: Systemd（用于服务管理）

## 安装 cloudflared
1) 访问 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 下载对应平台版本
2) 将可执行文件放到 PATH 中，或在 GUI 中手动指定路径

## 快速开始

### 1. 启动 GUI 管理界面
```bash
# 从项目根目录运行（推荐）
python -m app.main

# 经典 UI
python -m app.main --classic

# Windows: 双击 run.bat 或
run.bat

# Windows 调试模式（显示控制台输出；`--console` 必须放在第一个参数）
run.bat --console
```

### 2. Windows 开机自启动配置

```bat
:: 推荐：后台守护多隧道（按 config/tunnels.json 的 auto_start 启动）
scripts\windows\setup_autostart.bat install supervisor

:: 或：登录后自动打开 GUI（配合 GUI 内"自动启动"设置自动拉起隧道）
scripts\windows\setup_autostart.bat install gui

:: 查看状态
scripts\windows\setup_autostart.bat status supervisor

:: 卸载自启动
scripts\windows\setup_autostart.bat uninstall supervisor
```

**配置说明**：
- 自启动使用 Windows 注册表 (HKCU\Run)，兼容性最好
- 守护进程会根据 `config/tunnels.json` 中 `auto_start: true` 的隧道自动启动
- 使用 `pythonw.exe` 运行，无控制台窗口；已对 cloudflared 等子进程启用无窗口运行，避免频繁弹窗/闪退
- 排错：查看 `logs/tunnel_supervisor.log`，或用 `run.bat --console` 前台运行观察报错

### 3. Linux 自动监控服务
```bash
# 需要 root 权限
sudo ./scripts/deploy_improved_monitor.sh
```

### 4. 检查服务状态
```bash
# Linux
scripts/utils/check_status.sh

# Windows (PowerShell)
scripts\windows\setup_autostart.bat status supervisor
```

## 目录结构
```
.
├── app/                      # 应用程序核心代码
│   ├── cloudflared_cli.py   # Cloudflared CLI 封装
│   ├── diagnose.py          # 诊断工具
│   ├── modern_gui.py        # 现代化 GUI 界面
│   ├── tunnel_monitor_improved.py # 改进版单隧道监控脚本
│   ├── tunnel_supervisor.py # 多隧道守护进程
│   └── main.py              # 主程序入口
├── scripts/                  # 脚本工具
│   ├── systemd/             # Systemd 服务相关
│   │   └── tunnel-supervisor.service     # Supervisor Service
│   ├── deploy_improved_monitor.sh # 一键部署改单隧道监控服务
│   ├── deploy_supervisor.sh   # 一键部署 Supervisor
│   └── check_tunnel_status.sh # Supervisor 版状态巡检脚本
├── tunnels/                 # 隧道配置目录
│   └── [tunnel_name]/       # 各隧道配置文件夹
├── config/                  # 配置文件
├── docs/                    # 说明文档（排错/总结/指南）
└── logs/                    # 日志目录
    ├── tunnel_*.log         # 隧道日志
    ├── tunnel_supervisor.log # Supervisor 日志
    └── persistent/          # 持久化日志

## GUI 使用说明
- 普通用户建议路径：
  1. 在“首次使用”区域完成 `下载/更新` 或 `选择文件`
  2. 点击 `登录授权`
  3. 刷新列表或新建隧道
  4. 选择隧道后直接点击 `启动`
  5. 只有在需要排障或自定义域名时，再进入“高级工具”
- 刷新：列出当前账户下的隧道
- 下载：自动下载 cloudflared（Windows/架构自动匹配）
- 新建隧道：输入名称后创建
- 编辑配置：为选中隧道生成/打开 `tunnels/<name>/config.yml`
- 启动/停止：基于该配置启动或停止隧道进程
- DNS 路由：一键为选中隧道绑定域名（创建 Cloudflare DNS 记录）
- 删除选中：删除远端隧道（不可恢复）
- 守护进程配合：如果系统已启用 `tunnel_supervisor.service`，GUI 会自动把“启动/停止”请求交给守护进程执行，普通用户无需打开终端即可管理所有隧道。

## 隧道 Supervisor 管理

### 部署 / 更新
```bash
cd /home/zhukunren/桌面/项目/内网穿透
sudo ./scripts/deploy_supervisor.sh
```

### 手动运行（调试）
```bash
python -m app.tunnel_supervisor watch --interval 30
```

### 常用命令
```bash
# 查看状态
sudo systemctl status tunnel-supervisor.service

# 查看日志
sudo journalctl -u tunnel-supervisor.service -f

# 批量巡检
./scripts/check_tunnel_status.sh
# 仅查看异常
./scripts/check_tunnel_status.sh --only-issues
# 指定隧道
./scripts/check_tunnel_status.sh --tunnel kline

# 单条隧道状态
python -m app.tunnel_supervisor status <name>
```

### 特性
- **单点调度**：所有云隧道由 tunnel_supervisor 统一管理
- **多隧道支持**：基于 `config/tunnels.json` 自动拉起多个隧道
- **健康检查**：调用 `cloudflared tunnel info` 判断连接数量，异常自动重启
- **锁/PID 文件**：防止 GUI/脚本与守护进程同时操作

## 故障排查

### 查看日志
```bash
# Supervisor 日志
tail -f logs/tunnel_supervisor.log

# 隧道持久化日志
tail -f logs/persistent/[tunnel_name].log

# 应用日志
tail -f logs/tunnel_*.log
```

### 运行诊断
```bash
python -m app.diagnose
```

## 开发说明
- 入口程序：`app/main.py`
- GUI 界面：`app/modern_gui.py`
- 守护进程：`app/tunnel_supervisor.py`
- CLI 封装：`app/cloudflared_cli.py`

## 命令速查
- 登录：`cloudflared login`
- 列表：`cloudflared tunnel list --output json`
- 创建：`cloudflared tunnel create <name>`
- 路由：`cloudflared tunnel route dns <name> <hostname>`
- 运行：`cloudflared --config <config> tunnel run <name>`
- 删除：`cloudflared tunnel delete <name>`
