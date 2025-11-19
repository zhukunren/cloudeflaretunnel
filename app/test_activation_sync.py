#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试激活状态一致性
"""

import cloudflared_cli as cf
from pathlib import Path
import time
import subprocess

def check_tunnel_state(tunnel_name):
    """检查隧道状态"""
    running = cf.find_running_tunnel(tunnel_name)
    if running:
        print(f"✅ 隧道激活 - 运行中 (PID: {running['pid']})")
        return True
    else:
        print(f"⭕ 隧道未激活 - 已停止")
        return False

def test_activation_sync():
    """测试激活状态同步"""
    print("=" * 60)
    print("测试激活与启动状态同步")
    print("=" * 60)

    cloudflared_path = "/home/zhukunren/桌面/项目/内网穿透/cloudflared"
    tunnel_name = "test"
    config_path = Path.cwd() / "tunnels" / tunnel_name / "config.yml"

    # 1. 初始状态检查
    print("\n1. 初始状态:")
    initial_state = check_tunnel_state(tunnel_name)

    # 2. 如果隧道在运行，先停止它
    if initial_state:
        print("\n2. 停止隧道以测试启动流程:")
        ok, msg = cf.kill_tunnel_by_name(tunnel_name)
        print(f"   {msg}")
        time.sleep(2)
        print("   停止后状态:")
        check_tunnel_state(tunnel_name)

    # 3. 启动隧道
    print("\n3. 启动隧道:")
    proc = cf.run_tunnel(cloudflared_path, tunnel_name, config_path)
    print(f"   ✅ 隧道已启动 (PID: {proc.pid})")
    time.sleep(2)  # 等待隧道完全启动

    print("\n   启动后立即检查:")
    activated = check_tunnel_state(tunnel_name)

    if activated:
        print("   ✅ 激活状态正确同步")
    else:
        print("   ❌ 激活状态未同步")

    # 4. 验证隧道功能
    print("\n4. 验证隧道功能:")
    try:
        result = subprocess.run(
            ["curl", "-sI", "https://test.dwzq.top"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "HTTP" in result.stdout:
            status_line = result.stdout.split('\n')[0]
            print(f"   ✅ 隧道工作正常: {status_line}")
        else:
            print("   ❌ 隧道无响应")
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")

    # 5. 停止隧道
    print("\n5. 停止隧道:")
    ok, msg = cf.kill_tunnel_by_name(tunnel_name)
    print(f"   {msg}")
    time.sleep(2)  # 等待隧道完全停止

    print("\n   停止后立即检查:")
    deactivated = not check_tunnel_state(tunnel_name)

    if deactivated:
        print("   ✅ 取消激活状态正确同步")
    else:
        print("   ❌ 取消激活状态未同步")

    # 6. 总结
    print("\n" + "=" * 60)
    print("测试结果总结:")
    print("=" * 60)

    if activated and deactivated:
        print("✅ 激活与启动状态完全同步")
        print("   - 启动隧道 = 激活隧道")
        print("   - 停止隧道 = 取消激活隧道")
    else:
        print("❌ 激活状态同步存在问题")
        if not activated:
            print("   - 启动后未正确激活")
        if not deactivated:
            print("   - 停止后未正确取消激活")

def test_gui_state_indicators():
    """测试GUI状态指示器"""
    print("\n" + "=" * 60)
    print("GUI状态指示器预期行为")
    print("=" * 60)

    print("\n隧道激活时（运行中）:")
    print("   🔴 按钮: ⏹ 停止（红色）")
    print("   📊 状态: 运行中 (PID: xxxxx)")
    print("   ●  图标: 实心圆（绿色）")

    print("\n隧道未激活时（已停止）:")
    print("   🟢 按钮: ▶ 启动（绿色）")
    print("   📊 状态: 已停止")
    print("   ○  图标: 空心圆（灰色）")

    print("\n操作响应时间:")
    print("   ⚡ 启动后: < 0.5秒内更新所有状态")
    print("   ⚡ 停止后: < 0.5秒内清除所有状态")
    print("   🔄 自动刷新: 每5秒检查一次状态")

def main():
    """主测试函数"""
    try:
        # 测试激活状态同步
        test_activation_sync()

        # 显示GUI预期行为
        test_gui_state_indicators()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()