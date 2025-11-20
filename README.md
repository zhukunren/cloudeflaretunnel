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
│   ├── tunnel_monitor.py    # 隧道监控服务
│   └── main.py              # 主程序入口
├── scripts/                  # 脚本工具
│   ├── systemd/             # Systemd 服务相关
│   │   ├── cloudflared-monitor.service  # 监控服务配置
│   │   └── setup_service.sh            # 服务安装脚本
│   └── utils/               # 工具脚本
│       └── check_status.sh  # 状态检查脚本
├── tunnels/                 # 隧道配置目录
│   └── [tunnel_name]/       # 各隧道配置文件夹
├── config/                  # 配置文件
└── logs/                    # 日志目录
    ├── tunnel_*.log         # 隧道日志
    ├── tunnel_monitor.log   # 监控服务日志
    └── persistent/          # 持久化日志

## GUI 使用说明
- 刷新：列出当前账户下的隧道
- 下载：自动下载 cloudflared（Windows/架构自动匹配）
- 新建隧道：输入名称后创建
- 编辑配置：为选中隧道生成/打开 `tunnels/<name>/config.yml`
- 启动/停止：基于该配置启动或停止隧道进程
- DNS 路由：一键为选中隧道绑定域名（创建 Cloudflare DNS 记录）
- 删除选中：删除远端隧道（不可恢复）

## 监控服务管理

### 服务安装与配置
```bash
# 安装服务（需要 root）
sudo scripts/systemd/setup_service.sh install

# 卸载服务
sudo scripts/systemd/setup_service.sh uninstall

# 重启服务
sudo scripts/systemd/setup_service.sh restart
```

### 服务管理命令
```bash
# 查看状态
sudo systemctl status cloudflared-monitor

# 启动服务
sudo systemctl start cloudflared-monitor

# 停止服务
sudo systemctl stop cloudflared-monitor

# 重启服务
sudo systemctl restart cloudflared-monitor

# 查看服务日志
journalctl -u cloudflared-monitor -f
```

### 监控特性
- **自动重连**: 隧道断开后自动重新连接
- **健康检查**: 每60秒检查隧道状态
- **开机自启**: 系统重启后自动启动
- **故障恢复**: 最多重试3次，避免无限循环

## 故障排查

### 查看日志
```bash
# 监控服务日志
tail -f logs/tunnel_monitor.log

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
- 监控服务：`app/tunnel_monitor.py`
- CLI 封装：`app/cloudflared_cli.py`

## 命令速查
- 登录：`cloudflared login`
- 列表：`cloudflared tunnel list --output json`
- 创建：`cloudflared tunnel create <name>`
- 路由：`cloudflared tunnel route dns <name> <hostname>`
- 运行：`cloudflared --config <config> tunnel run <name>`
- 删除：`cloudflared tunnel delete <name>`
