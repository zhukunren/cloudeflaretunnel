#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试隧道UUID同步功能的改进
"""

import cloudflared_cli as cf
from pathlib import Path
import json

def test_uuid_validation():
    """测试UUID验证和更新功能"""
    print("=" * 60)
    print("测试UUID验证和更新功能")
    print("=" * 60)

    # 获取实际的隧道信息
    tunnels = cf.list_tunnels("/usr/bin/cloudflared")

    for tunnel in tunnels:
        name = tunnel.get("name", "")
        actual_tid = cf.extract_tunnel_id(tunnel)
        print(f"\n隧道: {name}")
        print(f"实际UUID: {actual_tid}")

        # 检查配置文件
        config_path = Path.cwd() / "tunnels" / name / "config.yml"
        if config_path.exists():
            # 从配置文件提取UUID
            config_tid = cf.extract_tunnel_id_from_config(config_path)
            print(f"配置文件UUID: {config_tid}")

            # 验证是否匹配
            if cf.validate_tunnel_config(config_path, actual_tid):
                print("✅ UUID匹配")
            else:
                print("❌ UUID不匹配")

                # 尝试更新配置文件
                print("正在更新配置文件...")
                if cf.update_config_tunnel_id(config_path, actual_tid):
                    print("✅ 配置文件已更新")

                    # 再次验证
                    new_config_tid = cf.extract_tunnel_id_from_config(config_path)
                    print(f"更新后的UUID: {new_config_tid}")

                    if cf.validate_tunnel_config(config_path, actual_tid):
                        print("✅ 验证成功")
                    else:
                        print("❌ 验证失败")
                else:
                    print("❌ 更新失败")
        else:
            print("⚠️ 配置文件不存在")

def test_config_cleanup():
    """测试删除隧道时清理配置文件"""
    print("\n" + "=" * 60)
    print("测试配置目录清理")
    print("=" * 60)

    tunnels_dir = Path.cwd() / "tunnels"
    if tunnels_dir.exists():
        config_dirs = [d for d in tunnels_dir.iterdir() if d.is_dir()]
        print(f"发现 {len(config_dirs)} 个配置目录:")
        for d in config_dirs:
            print(f"  - {d.name}")
            config_file = d / "config.yml"
            if config_file.exists():
                tid = cf.extract_tunnel_id_from_config(config_file)
                print(f"    UUID: {tid}")
    else:
        print("没有发现配置目录")

def main():
    """主测试函数"""
    try:
        # 测试UUID验证和更新
        test_uuid_validation()

        # 测试配置清理
        test_config_cleanup()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()