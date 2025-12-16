# Cloudflare 内网穿透管理系统

## 项目简介
基于 Cloudflare Tunnel 的内网穿透管理系统，提供现代化图形界面、自动监控和故障恢复功能。

## 功能特性
- 🎨 现代化图形界面管理
- 🔄 自动重连机制（监控服务）
- 📊 实时状态监控
- 🚀 开机自启动（Systemd）
- 📝 详细日志记录
- 🌐 DNS 路由管理
- 🔧 隧道诊断工具

## 环境要求
- Linux/Unix 系统（推荐 Ubuntu 20.04+）
- Python 3.8+（包含 Tkinter）
- Cloudflared CLI 工具
- Systemd（用于服务管理）

## 安装 cloudflared
1) 访问 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 下载对应平台版本
2) 将可执行文件放到 PATH 中，或在 GUI 中手动指定路径

## 快速开始

### 1. 启动 GUI 管理界面
```bash
cd app
python3 main.py
# 或
python3 app/main.py
```

### 2. 安装自动监控服务（推荐）
```bash
# 需要 root 权限
sudo scripts/systemd/setup_service.sh install
```

### 3. 检查服务状态
```bash
scripts/utils/check_status.sh
```

## 目录结构
```
.
├── app/                      # 应用程序核心代码
│   ├── cloudflared_cli.py   # Cloudflared CLI 封装
│   ├── diagnose.py          # 诊断工具
│   ├── modern_gui.py        # 现代化 GUI 界面
│   ├── tunnel_monitor.py    # 旧版监控脚本（兼容保留）
│   ├── tunnel_supervisor.py # 多隧道守护进程
│   └── main.py              # 主程序入口
├── scripts/                  # 脚本工具
│   ├── systemd/             # Systemd 服务相关
│   │   ├── cloudflared-monitor.service   # 旧版监控 Service（已弃用）
│   │   ├── tunnel-supervisor.service     # 新 Supervisor Service
│   │   └── setup_service.sh              # 旧版安装脚本
│   ├── deploy_supervisor.sh   # 一键部署 Supervisor
│   └── check_tunnel_status.sh # Supervisor 版状态巡检脚本
├── tunnels/                 # 隧道配置目录
│   └── [tunnel_name]/       # 各隧道配置文件夹
├── config/                  # 配置文件
└── logs/                    # 日志目录
    ├── tunnel_*.log         # 隧道日志
    ├── tunnel_supervisor.log # Supervisor 日志
    └── persistent/          # 持久化日志

## GUI 使用说明
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
python3 app/diagnose.py [tunnel_name]
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
