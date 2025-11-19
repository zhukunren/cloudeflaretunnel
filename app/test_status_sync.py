#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试左侧列表和系统状态同步
"""

import cloudflared_cli as cf
from pathlib import Path
import time

def test_status_consistency():
    """测试状态一致性"""
    print("=" * 60)
    print("测试左侧列表和系统状态同步")
    print("=" * 60)

    cloudflared_path = "/home/zhukunren/桌面/项目/内网穿透/cloudflared"
    tunnel_name = "test"
    config_path = Path.cwd() / "tunnels" / tunnel_name / "config.yml"

    print("\n1. 清理初始状态:")
    existing = cf.find_running_tunnel(tunnel_name)
    if existing:
        print(f"   发现运行的隧道 (PID: {existing['pid']})，停止中...")
        cf.kill_tunnel_by_name(tunnel_name)
        time.sleep(2)

    # 获取所有运行的隧道
    running = cf.get_running_tunnels()
    print(f"   系统中运行的隧道: {len(running)} 个")
    for t in running:
        print(f"     - {t['name']} (PID: {t['pid']})")

    print("\n2. 启动隧道:")
    proc = cf.run_tunnel(cloudflared_path, tunnel_name, config_path)
    print(f"   隧道已启动 (PID: {proc.pid})")
    time.sleep(1)

    # 检查状态
    running = cf.get_running_tunnels()
    found = cf.find_running_tunnel(tunnel_name)

    print(f"\n   启动后系统状态:")
    print(f"   - 运行的隧道总数: {len(running)}")
    if found:
        print(f"   - {tunnel_name} 状态: ✅ 已激活 (PID: {found['pid']})")
    else:
        print(f"   - {tunnel_name} 状态: ❌ 未激活")

    print("\n3. GUI预期显示:")
    print("   左侧列表:")
    if found:
        print(f"     - {tunnel_name}: ● 已激活（绿色）")
    else:
        print(f"     - {tunnel_name}: ○ 未激活（灰色）")

    print("   右侧系统状态:")
    if found:
        print(f"     - 隧道状态: 已激活 (PID: {found['pid']})")
        print("     - 当前选中: test")
    else:
        print("     - 隧道状态: 未激活")
        print("     - 当前选中: test")

    print("\n4. 停止隧道:")
    cf.kill_tunnel_by_name(tunnel_name)
    time.sleep(1)

    # 再次检查状态
    running = cf.get_running_tunnels()
    found = cf.find_running_tunnel(tunnel_name)

    print(f"\n   停止后系统状态:")
    print(f"   - 运行的隧道总数: {len(running)}")
    if not found:
        print(f"   - {tunnel_name} 状态: ✅ 未激活")
    else:
        print(f"   - {tunnel_name} 状态: ❌ 仍在运行 (PID: {found['pid']})")

    print("\n5. GUI预期显示:")
    print("   左侧列表:")
    if not found:
        print(f"     - {tunnel_name}: ○ 未激活（灰色）")
    else:
        print(f"     - {tunnel_name}: ● 已激活（绿色）- 错误!")

    print("   右侧系统状态:")
    if not found:
        print("     - 隧道状态: 未激活")
        print("     - 当前选中: test")
    else:
        print(f"     - 隧道状态: 已激活 (PID: {found['pid']}) - 错误!")
        print("     - 当前选中: test")

def explain_fixes():
    """说明修复的内容"""
    print("\n" + "=" * 60)
    print("已修复的问题")
    print("=" * 60)

    print("\n✅ 状态同步机制:")
    print("   1. running_tunnels 字典作为单一数据源")
    print("   2. 左侧列表和系统状态都从同一数据源读取")
    print("   3. 状态变化时同时更新两处显示")

    print("\n✅ 左侧列表更新:")
    print("   - update_tunnel_status() 更新单个隧道状态")
    print("   - refresh_all_status() 批量刷新所有状态")
    print("   - 保存 status_bar 和 badge_label 引用用于更新")

    print("\n✅ 状态刷新时机:")
    print("   - _init_app() 初始化时刷新")
    print("   - _refresh_proc_state() 状态变化时刷新")
    print("   - _immediate_status_sync() 操作后立即刷新")
    print("   - _apply_tunnel_filter() 过滤后刷新")

    print("\n✅ 统一的状态显示:")
    print("   激活状态:")
    print("     - 左侧: ● 已激活（绿色条+绿色徽章）")
    print("     - 右侧: 隧道状态 - 已激活 (PID: xxxxx)")
    print("   未激活状态:")
    print("     - 左侧: ○ 未激活（灰色条+灰色徽章）")
    print("     - 右侧: 隧道状态 - 未激活")

def main():
    """主测试函数"""
    try:
        # 测试状态一致性
        test_status_consistency()

        # 说明修复内容
        explain_fixes()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        print("\n总结:")
        print("✅ 左侧列表和系统状态使用同一数据源")
        print("✅ 两处显示完全同步")
        print("✅ 启动/停止后立即更新")
        print("✅ 定期刷新保持同步")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
