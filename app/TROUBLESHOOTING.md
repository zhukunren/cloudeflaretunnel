# 常见错误处理指南

## Cloudflare 500 Internal Server Error

### 错误信息
```
Internal server error Error code 500
Visit cloudflare.com for more information.
2025-11-18 13:44:57 UTC
```

### 原因分析

这个500错误通常在以下情况出现:

1. **应用启动时自动检查版本/更新**
   - 应用尝试连接Cloudflare API获取最新版本信息
   - Cloudflare API暂时不可用或网络问题

2. **首次登录认证**
   - 尝试访问Cloudflare认证服务
   - 区域网络限制或API限流

3. **刷新隧道列表**
   - cloudflared命令尝试连接Cloudflare API
   - 认证凭证过期或无效

### ✅ 解决方案

#### 方案1: 忽略错误(推荐)
500错误通常是临时性的,**不影响应用正常使用**:

- ✅ 应用UI仍然可以打开
- ✅ 本地配置管理功能正常
- ✅ 已有的隧道可以启动和管理
- ⚠️ 仅影响: 在线功能(登录、刷新列表、DNS配置)

**操作**: 直接忽略错误,继续使用应用的本地功能

#### 方案2: 等待重试
Cloudflare API通常会在几分钟内恢复:

```bash
# 等待1-5分钟后重试
python -m app.main
```

#### 方案3: 检查网络连接

```bash
# 测试网络
ping api.cloudflare.com
curl -I https://api.cloudflare.com

# 或使用诊断脚本
python diagnose.py
```

#### 方案4: 使用离线模式
如果已经配置好隧道,可以直接使用:

1. 打开应用
2. 忽略网络错误提示
3. 从隧道列表选择已配置的隧道
4. 点击"启动"即可运行

#### 方案5: 手动配置cloudflared
跳过API直接使用:

```bash
# 1. 手动下载cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
mv cloudflared-linux-amd64 cloudflared

# 2. 启动应用
python -m app.main

# 3. 在应用中点击"📁"选择cloudflared文件
```

---

## 其他常见错误

### 错误: ModuleNotFoundError: No module named 'app'

**原因**: 运行路径不正确

**解决**:
```bash
# 错误方式
cd /path/to/app
python main.py

# 正确方式
cd /path/to/项目/内网穿透
python -m app.main
```

### 错误: ModuleNotFoundError: No module named 'yaml'

**原因**: 缺少依赖

**解决**:
```bash
pip install pyyaml
```

### 错误: Permission denied: cloudflared

**原因**: 文件没有执行权限

**解决**:
```bash
chmod +x cloudflared
```

### 错误: 无法找到 cloudflared

**原因**: cloudflared未安装或路径不正确

**解决**:
1. Linux/macOS: 在应用中点击"⬇"自动下载
2. Windows: 手动下载cloudflared.exe
3. 或点击"📁"选择已有的cloudflared文件

### 错误: 未找到认证证书 cert.pem

**原因**: 未完成Cloudflare登录认证

**解决**:
1. 点击应用右上角"🔑"按钮
2. 在浏览器中完成授权
3. 刷新隧道列表

---

## 诊断工具

使用内置诊断脚本检查问题:

```bash
cd /path/to/app
python diagnose.py
```

诊断脚本会检查:
- ✓ Python版本
- ✓ 依赖模块
- ✓ 应用模块
- ✓ 目录结构
- ✓ Cloudflared状态
- ✓ 网络连接

---

## 获取帮助

### 查看日志
应用日志保存在 `logs/` 目录:

```bash
# 查看最新日志
tail -f logs/tunnel_$(date +%Y%m%d).log

# 搜索错误
grep -i error logs/*.log
```

### 启用调试模式
修改配置文件 `config/app_config.json`:

```json
{
  "log": {
    "level": "debug",
    "max_lines": 1000
  }
}
```

### 联系支持
- GitHub Issues: https://github.com/yourusername/cloudflare-tunnel-manager/issues
- 查看文档: README.md, USAGE.md

---

## 常见问题FAQ

### Q: 500错误会影响已运行的隧道吗?
**A**: 不会。已经启动的隧道会继续运行,500错误只影响新的API请求。

### Q: 如何在离线环境使用?
**A**:
1. 预先下载cloudflared
2. 预先完成登录认证(获取cert.pem)
3. 配置好隧道后,可以完全离线使用

### Q: 每次启动都出现500错误?
**A**: 可能是网络环境限制,建议:
1. 检查防火墙设置
2. 尝试使用VPN
3. 或使用已配置好的隧道(离线模式)

### Q: 如何跳过版本检查?
**A**: 修改代码,注释掉版本检查相关代码,或在无网络时使用应用。

---

**更新日期**: 2025-11-18
