# 自动进程清理功能说明

## 功能概述

为了确保隧道稳定运行，应用在每次启动时会自动执行进程清理流程。这个功能会：

1. **清理重复的监控脚本进程** - 确保只有一个监控脚本实例在运行
2. **清理僵尸进程** - 检测并报告已退出但未被父进程回收的进程
3. **验证systemd服务状态** - 确保systemd隧道服务处于运行状态

## 工作原理

### 模块位置
- **模块文件**: `app/utils/process_cleaner.py`
- **启动触发点**: `app/main.py`

### 工作流程

```
应用启动
    ↓
调用 cleanup_on_startup()
    ↓
创建 ProcessCleaner 实例
    ↓
执行 cleanup_all()
    ├─ 清理重复的监控脚本进程
    ├─ 清理僵尸进程
    └─ 验证 systemd 服务状态
        ├─ 服务正常运行 → 继续
        └─ 服务未运行 → 自动启动
    ↓
记录清理结果到日志
    ↓
应用GUI启动
```

## 清理逻辑详解

### 1. 重复监控脚本清理

**目的**: 防止多个监控脚本同时运行导致隧道冲突

**逻辑**:
- 扫描所有运行中的进程
- 识别包含 `tunnel_monitor` 或 `tunnel_supervisor` 的进程
- 保留systemd管理的监控脚本进程（通过比对PID）
- 其他重复进程被发送 SIGTERM 信号优雅关闭
- 如果进程在0.5秒内未退出，发送 SIGKILL 强制杀死

**安全性**:
- 仅清理已知的隧道监控脚本，不会误杀其他进程
- 保留systemd管理的主要进程，避免systemd监控失效
- 记录所有清理操作以便审计

### 2. 僵尸进程检测

**目的**: 识别未被回收的进程，这通常表示有资源泄漏

**逻辑**:
- 扫描进程列表查找包含 `<defunct>` 的僵尸进程
- 记录但不主动清理（僵尸进程由父进程回收）
- 输出统计信息帮助诊断问题

### 3. systemd服务验证

**目的**: 确保systemd服务持续监控隧道

**逻辑**:
- 检查 `cloudflared-homepage.service` 状态
- 如果服务未运行，尝试自动启动
- 启动后等待2秒允许服务完全初始化
- 如果启动失败，记录错误但不中断应用启动

## 日志位置

清理日志记录在以下位置：
```
logs/process_cleanup.log
```

### 日志格式
```
[2025-11-28 01:13:49.250] [INFO] 开始执行进程清理流程
[2025-11-28 01:13:49.354] [INFO] 没有发现重复的监控脚本进程
[2025-11-28 01:13:49.392] [INFO] 没有发现僵尸进程
[2025-11-28 01:13:49.416] [WARNING] ⚠ systemd 隧道服务未运行，尝试启动...
[2025-11-28 01:13:51.431] [INFO] ✓ systemd 隧道服务已启动
```

## 手动执行清理

如果需要手动执行清理（不启动GUI），可以在命令行运行：

```bash
cd /home/zhukunren/桌面/项目/内网穿透/app
python3 -c "from utils.process_cleaner import cleanup_on_startup; cleanup_on_startup()"
```

或者直接运行清理脚本：

```bash
python3 utils/process_cleaner.py
```

## 故障排查

### 清理不彻底
**症状**: 仍有多个监控脚本运行

**排查步骤**:
1. 检查日志: `tail -20 logs/process_cleanup.log`
2. 确认systemd服务状态: `systemctl --user status cloudflared-homepage.service`
3. 手动执行清理测试

### systemd服务无法启动
**症状**: 清理日志显示"启动 systemd 隧道服务失败"

**可能原因**:
- 隧道配置文件损坏
- cloudflared二进制文件不可执行
- Cloudflare凭证文件丢失或权限错误

**排查步骤**:
1. 检查配置: `ls -la tunnels/homepage/`
2. 手动启动服务: `systemctl --user start cloudflared-homepage.service`
3. 查看systemd日志: `journalctl --user -u cloudflared-homepage.service -n 20`

### 清理过程中出错
**症状**: 清理日志中出现ERROR级别日志

**排查步骤**:
1. 查看具体错误信息: `grep ERROR logs/process_cleanup.log`
2. 检查是否有权限问题: `whoami` 和 `id`
3. 验证ps命令是否可用: `ps aux | head -1`

## 最佳实践

### 定期监控
- **周期**: 每天检查一次清理日志
- **命令**: `tail -50 logs/process_cleanup.log | grep WARNING`
- **作用**: 尽早发现进程冲突问题

### 日志轮转
- **建议**: 配置日志轮转避免日志文件过大
- **方式**: 使用logrotate或写cron定期清理旧日志

### 自动启动
- **建议**: 通过systemd服务管理整个应用
- **优势**: 服务重启时自动执行清理流程

## 性能影响

- **启动延迟**: 清理流程通常需要1-2秒
- **CPU使用**: 清理过程中CPU使用率低于1%
- **内存使用**: 清理工具占用内存小于10MB

## 安全考虑

### 进程识别
- 使用进程命令行参数识别，避免误杀
- 仅清理包含特定关键字的进程

### 权限检查
- 使用SIGTERM信号优雅关闭，避免数据丢失
- 仅在必要时使用SIGKILL强制杀死

### 日志记录
- 记录所有清理操作供审计
- 日志包含PID、命令行、操作时间等详细信息

## 代码文档

### 主要类和方法

**ProcessCleaner 类**:
- `__init__(log_file)` - 初始化清理器
- `clean_duplicate_monitors()` - 清理重复监控脚本
- `clean_zombie_processes()` - 检测僵尸进程
- `verify_systemd_service()` - 验证systemd服务
- `cleanup_all()` - 执行全部清理

**cleanup_on_startup 函数**:
- 应用启动时调用
- 创建ProcessCleaner实例并执行清理
- 异常不中断应用启动

## 更新历史

| 版本 | 日期 | 功能 |
|------|------|------|
| 1.0 | 2025-11-28 | 初始版本，支持进程清理和systemd验证 |

## 相关文件

- `app/main.py` - 应用入口，调用清理功能
- `app/utils/process_cleaner.py` - 清理工具实现
- `logs/process_cleanup.log` - 清理操作日志
- `.config/systemd/user/cloudflared-homepage.service` - systemd服务配置
