#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试GUI状态检测和显示
"""

import cloudflared_cli as cf
from pathlib import Path
import subprocess
import time

def test_gui_state_detection():
    """测试GUI状态检测功能"""
    print("=" * 60)
    print("测试GUI状态检测")
    print("=" * 60)

    # 1. 检查配置文件中的cloudflared路径
    config_path = Path.cwd() / "config" / "app_config.json"
    if config_path.exists():
        import json
        config = json.loads(config_path.read_text())
        cloudflared_path = config.get("cloudflared", {}).get("path", "")
        print(f"\n配置文件中的cloudflared路径: {cloudflared_path}")

        # 验证路径存在
        if Path(cloudflared_path).exists():
            print("✅ 路径存在")
        else:
            print("❌ 路径不存在")
    else:
        print("❌ 配置文件不存在")

    # 2. 查找cloudflared
    found_path = cf.find_cloudflared()
    print(f"\n自动查找的cloudflared路径: {found_path}")

    # 3. 检测运行中的隧道
    print("\n检测运行中的隧道:")
    running = cf.get_running_tunnels()

    if running:
        print(f"✅ 发现 {len(running)} 个运行中的隧道:")
        for t in running:
            print(f"   - {t['name']} (PID: {t['pid']})")

        # 检测具体隧道
        for t in running:
            tunnel_name = t['name']
            info = cf.find_running_tunnel(tunnel_name)
            print(f"\n隧道 '{tunnel_name}' 检测结果:")
            if info:
                print(f"   ✅ 运行中 (PID: {info['pid']})")
            else:
                print(f"   ❌ 未检测到")
    else:
        print("⚠️ 没有运行中的隧道")

    # 4. 测试进程检测
    print("\n\n直接进程检测:")
    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, check=False)
    cloudflared_processes = []

    for line in result.stdout.split('\n'):
        if 'cloudflared' in line and 'tunnel run' in line:
            parts = line.split()
            if len(parts) > 1:
                pid = parts[1]
                # 提取隧道名称
                for i, part in enumerate(parts):
                    if part == "run" and i + 1 < len(parts):
                        tunnel_name = parts[i + 1]
                        cloudflared_processes.append({"pid": pid, "name": tunnel_name})
                        print(f"   发现进程: PID={pid}, 隧道={tunnel_name}")
                        break

    if not cloudflared_processes:
        print("   没有发现cloudflared进程")

def test_gui_startup_sequence():
    """模拟GUI启动序列"""
    print("\n" + "=" * 60)
    print("模拟GUI启动序列")
    print("=" * 60)

    print("\n1. 初始化步骤:")
    print("   - 加载配置文件")
    print("   - 查找cloudflared路径")
    print("   - 检测运行中的隧道")
    print("   - 更新UI状态")

    # 模拟_refresh_proc_state
    print("\n2. _refresh_proc_state():")
    running_tunnels = cf.get_running_tunnels()
    if running_tunnels:
        print(f"   检测到 {len(running_tunnels)} 个运行的隧道")
        for t in running_tunnels:
            print(f"   - {t['name']} (PID: {t['pid']})")
    else:
        print("   没有检测到运行的隧道")

    # 模拟_is_tunnel_running
    print("\n3. _is_tunnel_running('test'):")
    test_running = cf.find_running_tunnel('test')
    if test_running:
        print(f"   ✅ 隧道 'test' 运行中 (PID: {test_running['pid']})")
        print("   → 按钮应显示: ⏹ 停止")
        print("   → 状态应显示: 运行中")
    else:
        print("   ❌ 隧道 'test' 未运行")
        print("   → 按钮应显示: ▶ 启动")
        print("   → 状态应显示: 已停止")

def main():
    """主测试函数"""
    try:
        # 测试GUI状态检测
        test_gui_state_detection()

        # 模拟GUI启动序列
        test_gui_startup_sequence()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        print("\n建议:")
        print("1. 确保配置文件中的cloudflared路径正确")
        print("2. 重启GUI应用以加载新配置")
        print("3. 选中隧道后查看按钮和状态显示")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()