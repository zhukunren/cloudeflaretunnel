#!/bin/bash
# 系统级别的UDP缓冲区优化脚本
# 解决 "failed to sufficiently increase receive buffer size" 问题

echo "正在优化系统UDP缓冲区设置..."

# 检查是否有root权限
if [ "$EUID" -ne 0 ]; then
   echo "请使用sudo运行此脚本"
   exit 1
fi

# 备份当前设置
cp /etc/sysctl.conf /etc/sysctl.conf.backup.$(date +%Y%m%d)

# 添加或更新UDP缓冲区设置
cat >> /etc/sysctl.conf << EOF

# Cloudflared UDP缓冲区优化
# 增加UDP缓冲区大小以支持QUIC协议
net.core.rmem_default = 7340032
net.core.rmem_max = 7340032
net.core.wmem_default = 7340032
net.core.wmem_max = 7340032
net.core.netdev_max_backlog = 30000
net.ipv4.udp_mem = 102400 873800 16777216
net.ipv4.udp_rmem_min = 8192
net.ipv4.udp_wmem_min = 8192

# TCP优化（提高连接稳定性）
net.ipv4.tcp_keepalive_time = 120
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5
net.ipv4.tcp_fin_timeout = 30

# 连接跟踪优化
net.netfilter.nf_conntrack_max = 131072
net.netfilter.nf_conntrack_tcp_timeout_established = 86400
EOF

# 应用设置
sysctl -p

echo "UDP缓冲区优化完成！"
echo "当前设置："
sysctl net.core.rmem_max
sysctl net.core.wmem_max

echo ""
echo "注意：如果使用firewalld，可能还需要执行："
echo "sudo firewall-cmd --permanent --direct --add-rule ipv4 filter INPUT 0 -p udp -j ACCEPT"
echo "sudo firewall-cmd --reload"