# 隧道稳定性问题速查表

## 🔴 立即需要修复的问题

| # | 文件 | 行号 | 问题描述 | 影响范围 | 预计修复时间 |
|---|------|------|---------|---------|-----------|
| 1 | tunnel_monitor_improved.py | 55, 101, 428 | 隧道名称混淆，可能杀死错误的隧道 | CRITICAL | 1h |
| 2 | tunnel_supervisor.py | 178-181 | 启动验证时间不足，虚假启动成功 | CRITICAL | 1h |
| 3 | tunnel_supervisor.py / tunnel_monitor_improved.py | 66-71 / 86-94 | 日志文件写入无锁保护，导致日志损坏 | CRITICAL | 1.5h |
| 4 | tunnel_monitor_improved.py / cloudflared_cli.py | 295-323 / 673-693 | 进程组死亡竞争，可能误杀系统进程 | CRITICAL | 1.5h |
| 5 | utils/process_tracker.py | 226-241 | 锁文件写入非原子，导致多个守护进程冲突 | CRITICAL | 1h |

## 🟠 应该修复的问题

| # | 文件 | 行号 | 问题描述 | 影响范围 | 预计修复时间 |
|---|------|------|---------|---------|-----------|
| 6 | tunnel_monitor_improved.py | 333-359 | 重启冷却时间计算错误，导致重启风暴 | HIGH | 30m |
| 7 | tunnel_monitor_improved.py | 24 | Metrics 端口硬编码，多隧道冲突 | HIGH | 30m |
| 8 | tunnel_monitor_improved.py | 194-214 | 健康检查策略不合理，漏洞过多 | HIGH | 1h |

---

## 🚀 快速修复步骤

### 第一天（优先顺序）

#### Step 1: 修复 BUG #1 (15分钟)
```bash
# 编辑 tunnel_monitor_improved.py
# 将第55行改为：current_tunnel_name = TUNNEL_NAME
# 将第428行提前到 main() 最开始
```

**验证：** 重启监控脚本，检查正确隧道被管理

---

#### Step 2: 修复 BUG #2 (20分钟)
```bash
# 编辑 tunnel_supervisor.py
# 将 start_tunnel() 中的 time.sleep(2) 改为循环等待10秒
# 每2秒检查一次连接状态
```

**验证：** 启动隧道，确认有连接后才返回成功

---

#### Step 3: 修复 BUG #3 (30分钟)
```bash
# 在 tunnel_supervisor.py 中添加日志锁
# 在 __init__() 中添加：self._log_lock = FileLock(...)
# 在 _log() 中添加：with self._log_lock.locked():
```

**验证：** 多进程同时写日志，确保没有交错

---

#### Step 4: 修复 BUG #4 (40分钟)
```bash
# 编辑 tunnel_monitor_improved.py 和 cloudflared_cli.py
# 在所有 os.getpgid() 和 os.killpg() 调用周围添加 try-except
# 在进程操作前检查 poll() != None
```

**验证：** 强制杀死进程，确认不会误杀其他进程

---

#### Step 5: 修复 BUG #5 (20分钟)
```bash
# 编辑 utils/process_tracker.py
# 将 SupervisorLock.acquire() 改为必须获得锁，否则抛异常
# 添加 _write_json_atomic() 方法
```

**验证：** 同时启动多个守护进程，确认只有一个成功

---

### 第二天（次要顺序）

#### Step 6: 修复 BUG #6 (15分钟)
```bash
# 编辑 tunnel_monitor_improved.py
# 将 last_restart_time = time.time() 移到启动成功后
```

#### Step 7: 修复 BUG #7 (20分钟)
```bash
# 编辑 tunnel_monitor_improved.py
# 添加 get_metrics_port() 函数
# 在 main() 中计算动态端口
```

#### Step 8: 修复 BUG #8 (45分钟)
```bash
# 编辑 tunnel_monitor_improved.py
# 添加 _check_connection_freshness() 函数
# 更新 comprehensive_health_check() 逻辑
```

---

## 📊 修复前后对比

### 修复前的问题现象
```
❌ 隧道频繁重启（重启风暴）
❌ 隧道突然断连，无日志可查
❌ 多个隧道互相干扰
❌ GUI 和守护进程冲突，无法同时运行
❌ 日志文件损坏，无法调试
```

### 修复后的预期效果
```
✓ 隧道稳定运行（>99% uptime）
✓ 详细的日志便于故障排查
✓ 隧道完全隔离，互不影响
✓ 可同时运行多个管理工具
✓ 日志文件完整，便于分析
```

---

## ✅ 修复验证清单

在每个修复完成后，检查以下项目：

- [ ] 代码能够编译/运行
- [ ] 日志显示预期的信息
- [ ] 隧道连接保持稳定 ≥5分钟
- [ ] 重启场景能正确处理
- [ ] 没有资源泄漏
- [ ] 与其他工具无冲突

---

## 🔧 常见问题排查

### 隧道仍然经常重启
**可能原因：**
- 网络不稳定（检查 Cloudflare 连接）
- 本地服务不可用（检查目标地址）
- 修复 #2 未正确应用（启动验证时间）
- 修复 #6 未正确应用（重启冷却时间）

**检查方法：**
```bash
# 查看最后几条日志
tail -50 logs/tunnel_supervisor.log | grep -E "重启|失败|异常"

# 测试本地服务
curl http://localhost:8080 -I

# 测试隧道连接
cloudflared tunnel info tunnelname
```

---

### 隧道启动后立即断连
**可能原因：**
- 修复 #2 未应用（2秒太短）
- 本地服务不健康
- Cloudflare 网络问题

**检查方法：**
```bash
# 查看详细日志
tail -100 logs/persistent/tunnel_name.log

# 检查隧道配置
cat tunnels/tunnel_name/config.yml

# 测试隧道连接
cloudflared tunnel info tunnel_name --output json | jq '.conns'
```

---

### 多个工具无法同时运行
**可能原因：**
- 修复 #5 未应用（锁文件问题）
- 修复 #3 未应用（日志锁问题）

**检查方法：**
```bash
# 查看是否有活跃的守护进程
ps aux | grep -E "tunnel_supervisor|tunnel_monitor"

# 检查锁文件状态
cat logs/pids/tunnel_supervisor.lock

# 检查 PID 文件
ls -la logs/pids/
```

---

## 📝 修复后的最佳实践

1. **只用一个管理工具**
   ```bash
   # 推荐：使用 tunnel_supervisor（更稳定）
   python tunnel_supervisor.py watch --interval 30

   # 不推荐：同时运行多个 tunnel_monitor_improved.py
   ```

2. **定期检查日志**
   ```bash
   # 每周检查一次
   grep "ERROR\|WARNING" logs/tunnel_supervisor.log | tail -20
   ```

3. **监控系统资源**
   ```bash
   # 确保没有内存泄漏
   watch -n 1 'ps aux | grep cloudflared'
   ```

4. **定期重启服务**
   ```bash
   # 每月重启一次（可选）
   python tunnel_supervisor.py restart tunnelname
   ```

---

## 联系支持

如果修复后仍有问题，请提供：

1. 完整日志文件（最后100行）
2. 隧道配置文件
3. 系统信息（OS, Python版本, Cloudflare cloudflared版本）
4. 问题重现步骤

