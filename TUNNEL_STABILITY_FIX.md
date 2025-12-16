# Cloudflared 隧道稳定性问题解决方案

## 问题根源分析

### 主要问题
1. **"your tunnel does not have any active connection" 错误**
   - 隧道进程虽然在运行，但连接器(connector)已经断开
   - 监控脚本只检查进程存在，没有检查实际连接状态

2. **UDP缓冲区不足**
   - 日志显示: "failed to sufficiently increase receive buffer size"
   - 导致QUIC协议连接不稳定，容易断开

3. **重连机制缺陷**
   - 原监控脚本使用`cloudflared tunnel info`命令检测状态不准确
   - 重启后等待时间不足，连接未完全建立就判断失败
   - 缺少健康检查和退避重试机制

## 已实施的解决方案

### ✨ 新增：Tunnel Supervisor (推荐)
- ✅ 使用 `python -m app.tunnel_supervisor watch --interval 30` 单点调度所有隧道（GUI 会自动转发启动/停止请求给守护进程）
- ✅ `config/tunnels.json` 描述要托管的隧道（例如 homepage、agenttrading、kline）
- ✅ supervisor 写入 PID/锁文件，GUI 与脚本可检测冲突
- ✅ 提供 `scripts/deploy_supervisor.sh` 一键安装 systemd 服务
- ✅ `scripts/check_tunnel_status.sh` 可阅读配置并批量输出健康状态

### 1. 改进的监控脚本 (`tunnel_monitor_improved.py`)
- ✅ 综合健康检查：进程、metrics端点、实际连接三重检查
- ✅ 使用JSON格式获取准确的连接状态
- ✅ 实现指数退避重试机制（最多5次）
- ✅ 增加重启冷却时间防止频繁重启
- ✅ 优化启动等待时间（最多30秒）

### 2. 优化的隧道配置 (`config_optimized.yml`)
- ✅ 添加连接超时和保活设置
- ✅ 启用HTTP/2源连接提高稳定性
- ✅ 增加重试次数和优雅关闭时间
- ✅ 配置详细日志记录

### 3. 系统级优化 (`optimize_udp_buffer.sh`)
- ✅ 增加UDP缓冲区大小到7MB
- ✅ 优化TCP保活参数
- ✅ 调整连接跟踪设置

### 4. Systemd服务配置
- ✅ 自动重启配置
- ✅ 资源限制优化
- ✅ 环境变量设置

## 快速部署步骤

1. **运行 Supervisor 部署脚本**
   ```bash
   cd /home/zhukunren/桌面/项目/内网穿透
   sudo ./scripts/deploy_supervisor.sh
   ```

2. **手动部署步骤**（如需）
   ```bash
   # 停止旧服务
   sudo systemctl stop tunnel-monitor.service tunnel-monitor-improved.service 2>/dev/null || true
   pkill -f tunnel_monitor.py 2>/dev/null || true

   # 部署 Supervisor
   sudo cp scripts/systemd/tunnel-supervisor.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable tunnel-supervisor.service
   sudo systemctl start tunnel-supervisor.service
   ```

## 监控和维护

### 查看服务状态
```bash
systemctl status tunnel-supervisor.service
```

### 查看实时日志
```bash
sudo journalctl -u tunnel-supervisor.service -f
```

### 批量巡检
```bash
./scripts/check_tunnel_status.sh
# 仅输出异常
./scripts/check_tunnel_status.sh --only-issues
# 指定某条隧道
./scripts/check_tunnel_status.sh --tunnel homepage
```

### 检查隧道连接
```bash
./cloudflared tunnel info --output json homepage
```

### 常见命令
```bash
# 重启服务
sudo systemctl restart tunnel-supervisor.service

# 停止服务
sudo systemctl stop tunnel-supervisor.service

# 查看系统日志
sudo journalctl -u tunnel-supervisor.service -n 100
```

## 预期改进效果

1. **连接稳定性提升**
   - 准确检测连接状态，及时发现断线
   - 智能重连机制，避免无效重启

2. **减少错误频率**
   - UDP缓冲区优化减少"no active connection"错误
   - TCP保活设置维持长连接稳定

3. **自动恢复能力**
   - 服务级自动重启
   - 指数退避避免重启风暴
   - 多重健康检查确保服务可用

## 故障排查

如果仍然出现问题：

1. **检查网络连接**
   ```bash
   ping 1.1.1.1
   nslookup _tunnel.dwzq.top
   ```

2. **检查防火墙**
   ```bash
   sudo firewall-cmd --list-all
   # 如需开放UDP
   sudo firewall-cmd --permanent --add-port=7844/udp
   sudo firewall-cmd --reload
   ```

3. **查看详细错误**
   ```bash
   grep ERROR logs/tunnel_monitor_improved.log | tail -20
   ```

4. **手动测试隧道**
   ```bash
   ./cloudflared --config tunnels/homepage/config.yml tunnel run homepage
   ```

## 注意事项

- 确保只有一个监控服务在运行
- 系统重启后服务会自动启动
- 如果修改配置，需要重启服务生效
- 建议定期查看日志了解运行状况

## 后续优化建议

1. 考虑使用多个隧道实现高可用
2. 配置监控告警（邮件/短信）
3. 定期备份隧道配置和凭证
4. 监控本地服务(localhost:8080)的可用性
