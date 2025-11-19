#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试隧道启动功能
"""

import cloudflared_cli as cf
from pathlib import Path

def test_tunnel_start():
    """测试隧道启动"""
    print("测试隧道启动功能")
    print("=" * 60)

    # 1. 检查cloudflared路径
    cloudflared_path = "/usr/local/bin/cloudflared"
    print(f"Cloudflared路径: {cloudflared_path}")

    # 验证文件存在
    if Path(cloudflared_path).exists():
        print("✅ 文件存在")
    else:
        print("❌ 文件不存在")
        return

    # 2. 获取隧道列表
    print("\n获取隧道列表...")
    try:
        tunnels = cf.list_tunnels(cloudflared_path)
        print(f"✅ 找到 {len(tunnels)} 个隧道")

        if tunnels:
            tunnel = tunnels[0]
            name = tunnel.get("name")
            tid = cf.extract_tunnel_id(tunnel)
            print(f"  隧道名称: {name}")
            print(f"  隧道UUID: {tid}")
        else:
            print("❌ 没有找到隧道")
            return
    except Exception as e:
        print(f"❌ 获取隧道列表失败: {e}")
        return

    # 3. 检查配置文件
    print("\n检查配置文件...")
    config_path = Path.cwd() / "tunnels" / name / "config.yml"

    if config_path.exists():
        print(f"✅ 配置文件存在: {config_path}")

        # 验证UUID
        config_tid = cf.extract_tunnel_id_from_config(config_path)
        if config_tid == tid:
            print("✅ UUID匹配")
        else:
            print(f"⚠️ UUID不匹配")
            print(f"  配置文件: {config_tid}")
            print(f"  实际UUID: {tid}")
    else:
        print(f"❌ 配置文件不存在: {config_path}")
        print("  生成默认配置...")
        cf.write_basic_config(config_path, name, tid, "http://localhost:8501", "test.dwzq.top")
        print("✅ 配置文件已生成")

    # 4. 尝试启动隧道
    print("\n尝试启动隧道...")
    try:
        proc = cf.run_tunnel(cloudflared_path, name, config_path)
        print(f"✅ 隧道启动成功，进程ID: {proc.pid}")

        # 读取几行输出
        print("\n隧道输出:")
        for i in range(5):
            line = proc.stdout.readline()
            if line:
                print(f"  {line.strip()}")
            else:
                break

        # 停止隧道
        print("\n停止隧道...")
        cf.stop_process(proc)
        print("✅ 隧道已停止")

    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_tunnel_start()