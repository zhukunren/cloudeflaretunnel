# 使用说明

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行应用

#### 现代UI(推荐)
```bash
python -m app.main
# 或
python -m app.main --modern
```

#### 经典UI
```bash
python -m app.main --classic
```

## 目录说明

- `assets/` - 资源文件(图标、图片)
- `components/` - UI组件库
- `config/` - 配置管理模块
- `logs/` - 运行日志(自动生成)
- `tunnels/` - 隧道配置文件(自动生成)
- `utils/` - 工具模块(主题、日志)

## 首次使用

1. **设置 cloudflared**
   - Windows: 下载 cloudflared.exe 放到项目根目录
   - Linux/macOS: 点击应用内的"⬇"图标自动下载

2. **登录认证**
   - 点击右上角"🔑"图标
   - 在浏览器中授权 Cloudflare

3. **创建和配置隧道**
   - 点击"➕"创建新隧道
   - 点击"✏"编辑配置文件
   - 设置本地服务地址和域名

4. **启动隧道**
   - 选择隧道,点击"▶ 启动"
   - 查看日志确认状态

## 配置文件示例

创建 `tunnels/my-tunnel/config.yml`:

```yaml
tunnel: <YOUR_TUNNEL_ID>
credentials-file: /home/user/.cloudflared/<TUNNEL_ID>.json

ingress:
  # Web应用
  - hostname: app.example.com
    service: http://localhost:8080

  # API服务
  - hostname: api.example.com
    service: http://localhost:3000

  # SSH隧道
  - hostname: ssh.example.com
    service: ssh://localhost:22

  # 默认规则(必需)
  - service: http_status:404
```

## 常用功能

### DNS路由配置

**方式1: 自动(推荐)**
- 在配置文件中设置 `hostname`
- 启动时自动配置DNS

**方式2: 手动**
- 选择隧道
- 点击"🌐 DNS路由"
- 输入域名

### 隧道诊断

点击"🧪 诊断测试"检查:
- 配置格式
- DNS设置
- 隧道连接
- 本地服务
- 凭证文件

### 日志操作

- **清空**: 清除当前日志
- **复制**: 复制到剪贴板
- **保存**: 保存到文件

## 故障排查

### 问题: 找不到 cloudflared

```bash
# Linux/macOS - 赋予执行权限
chmod +x cloudflared

# 或手动指定路径
# 在应用中点击"📁"选择文件
```

### 问题: 端口占用

```
Error: bind: address already in use
```

**解决**: 更改配置中的端口号,或停止占用端口的程序

### 问题: DNS记录已存在

```
Error: DNS record already exists
```

**解决**:
1. 在 Cloudflare 控制台删除现有记录
2. 或使用不同的子域名

### 问题: 凭证文件未找到

```
Error: credentials file not found
```

**解决**: 确保已运行"🔑 登录"并完成授权

## 高级用法

### 多隧道配置

可以创建多个隧道用于不同用途:

```bash
tunnels/
├── web-tunnel/
│   └── config.yml
├── api-tunnel/
│   └── config.yml
└── ssh-tunnel/
    └── config.yml
```

### 查看运行日志

应用日志保存在 `logs/` 目录:

```bash
# 查看今天的日志
cat logs/tunnel_20231118.log

# 实时跟踪日志
tail -f logs/tunnel_20231118.log
```

### 配置持久化

应用配置保存在 `config/app_config.json`:

```json
{
  "window": {
    "width": 1200,
    "height": 700,
    "x": 100,
    "y": 100
  },
  "cloudflared": {
    "path": "/path/to/cloudflared"
  }
}
```

## 获取帮助

- 查看 README.md
- 使用"🧪 诊断测试"功能
- 查看运行日志
- GitHub Issues

---

**祝使用愉快! 🚀**
