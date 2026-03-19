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
python -m app.diagnose
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
cd /path/to/项目/内网穿透
python -m app.diagnose
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
- 查看文档: README.md, docs/TROUBLESHOOTING.md

---

## Windows 自启动问题

### 问题: 开机后隧道没有自动启动

**排查步骤**:

1. **检查注册表自启动项是否存在**
```powershell
# PowerShell
Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' | Select-Object CloudflareTunnelSupervisor
```

2. **检查自启动命令是否正确**
```bat
scripts\windows\setup_autostart.bat status supervisor
```
正确的命令应包含 `watch --interval 30` 参数。

3. **重新安装自启动**
```bat
scripts\windows\setup_autostart.bat uninstall supervisor
scripts\windows\setup_autostart.bat install supervisor
```

4. **检查 Windows 是否禁用了启动项**
- 任务管理器 → 启动应用 / 设置 → 应用 → 启动：确认未禁用 `CloudflareTunnelSupervisor`

### 问题: 终端窗口频繁闪现/闪退

**现象**: 运行/监控时黑色终端窗口一闪而过，或感觉“闪退”。

**原因**:
- 旧版本在 Windows 下执行 `cloudflared` / `wmic` / `taskkill` 等命令时，会短暂创建控制台窗口
- 使用 `pythonw.exe` 后台运行时，异常不会在屏幕上显示（看起来像“闪退”）

**解决方案**:

1. **更新到最新版代码**
已对相关子进程启用无窗口运行，避免频繁弹窗/闪退。

2. **使用调试模式前台运行（显示错误）**
```bat
run.bat --console
```
`--console` 必须放在第一个参数（例如：`run.bat --console --classic`）。

3. **查看日志文件**
```bat
type logs\tunnel_supervisor.log
```

4. **常见错误原因**:
   - `config/tunnels.json` 中的 `cloudflared_path` 路径错误
   - `tunnels/` 下存在未创建/无凭据的隧道目录（可删除无用目录）
   - `.venv` 未安装依赖 / 虚拟环境损坏

### 问题: 中文路径导致脚本错误

**症状**: 运行 `scripts\\windows\\setup_autostart.bat` 提示 `: was unexpected at this time.` 或安装失败。

**解决**:
- 推荐：使用最新版脚本（已增强中文/空格路径兼容）
- 兜底：手动添加注册表项（HKCU，无需管理员）
```powershell
# PowerShell
$cmd = '"E:\项目\内网穿透\.venv\Scripts\pythonw.exe" "E:\项目\内网穿透\app\tunnel_supervisor.py" watch --interval 30'
New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Force | Out-Null
Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'CloudflareTunnelSupervisor' -Value $cmd
```

### 问题: tunnels.json 配置错误

**症状**: 日志中出现 `cloudflared_path 无效` 或 `隧道配置文件不存在`

**解决**:
1. 编辑 `config/tunnels.json`
2. 确保 `cloudflared_path` 指向正确的 Windows 路径（如 `E:\\项目\\内网穿透\\cloudflared.exe`）
3. 移除不存在的隧道配置

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

**更新日期**: 2026-01-18
