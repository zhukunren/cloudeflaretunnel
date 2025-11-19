# Cloudflare Tunnel 内网穿透管理器

一个功能强大、界面现代的 Cloudflare Tunnel GUI 管理工具,用于轻松管理内网穿透隧道。

## 特性

### 核心功能
- 隧道创建、删除、启动、停止
- DNS 路由自动配置
- 实时日志监控
- 配置文件可视化编辑
- 内置隧道诊断测试
- 搜索和过滤隧道列表

### UI/UX
- 现代化的 Material Design 风格界面
- 响应式布局,自适应窗口大小
- 流畅的交互动画和悬停效果
- 直观的状态指示器和徽章

### 技术特性
- 配置持久化(窗口位置、大小、路径等)
- 多级日志系统(DEBUG/INFO/WARNING/ERROR)
- 日志自动保存到文件
- 模块化架构,易于扩展

## 系统要求

- **Python**: 3.8+
- **操作系统**: Windows, Linux, macOS
- **Cloudflared**: 需要安装 cloudflared 工具

## 快速开始

### 安装

```bash
# 克隆项目
git clone https://github.com/yourusername/cloudflare-tunnel-manager.git
cd cloudflare-tunnel-manager/app

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# 安装依赖
pip install pyyaml
```

### 启动应用

```bash
# 现代UI(推荐)
python -m app.main

# 经典UI
python -m app.main --classic
```

### 首次使用

1. **选择 cloudflared** - 点击右上角"📁"或"⬇"图标
2. **登录 Cloudflare** - 点击"🔑"图标完成授权
3. **创建隧道** - 点击"➕"新建隧道
4. **配置隧道** - 选择隧道后点击"✏ 编辑配置"
5. **启动隧道** - 点击"▶ 启动"按钮

## 项目结构

```
app/
├── components/       # UI组件库
├── config/           # 配置管理
├── logs/             # 日志文件
├── tunnels/          # 隧道配置
├── utils/            # 工具模块
├── cloudflared_cli.py
├── modern_gui.py     # 现代UI
├── gui.py            # 经典UI
└── main.py           # 入口文件
```

## 配置示例

隧道配置文件 (`tunnels/your-tunnel/config.yml`):

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /path/to/credentials.json
ingress:
  - hostname: app.example.com
    service: http://localhost:8080
  - service: http_status:404
```

## 常见问题

### Cloudflare 500错误
如果启动时看到 "Internal server error Error code 500":
- **这是正常的!** Cloudflare API暂时不可用
- **不影响使用** - 应用的本地功能仍然可用
- **已配置的隧道** - 可以正常启动和管理
- **解决方法** - 忽略错误或等待几分钟后重试
- 详见: `TROUBLESHOOTING.md`

### 无法找到 cloudflared
- 手动选择文件路径(点击"📁")
- Linux/macOS 可使用自动下载功能

### 隧道启动失败
- 使用"🧪 诊断测试"排查问题
- 检查配置文件YAML格式
- 确保本地服务正在运行

### DNS记录已存在
- 在 Cloudflare 控制台删除现有记录
- 或使用不同的子域名

### 运行诊断
```bash
python diagnose.py
```
自动检查所有可能的问题

## 功能特性

### 隧道诊断

��击"🧪 诊断测试"检查:
- 配置文件格式
- DNS 主机名
- 隧道连接
- 本地服务可用性
- 凭证文件状态

### 日志管理

- 实时显示运行日志
- 按级别过滤
- 复制到剪贴板
- 保存到文件
- 自动清理(保留1000行)

## 开发

### 添加组件

```python
# components/widgets.py
class MyWidget(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
```

### 自定义主题

```python
# utils/theme.py
class MyTheme(Theme):
    PRIMARY = "#YOUR_COLOR"
```

## 许可证

MIT License

## 鸣谢

- [Cloudflare](https://www.cloudflare.com/)
- [cloudflared](https://github.com/cloudflare/cloudflared)
