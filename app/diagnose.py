#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用启动检查和诊断工具
"""
import sys
import os
from pathlib import Path


def check_python_version():
    """检查Python版本"""
    version = sys.version_info
    if version < (3, 8):
        print(f"❌ Python版本过低: {version.major}.{version.minor}")
        print(f"   需要: Python 3.8+")
        return False
    print(f"✓ Python版本: {version.major}.{version.minor}.{version.micro}")
    return True


def check_dependencies():
    """检查依赖"""
    required = {
        'tkinter': 'tkinter (内置)',
        'yaml': 'pyyaml'
    }

    missing = []
    for module, package in required.items():
        try:
            if module == 'yaml':
                import yaml
            elif module == 'tkinter':
                import tkinter
            print(f"✓ {package}")
        except ImportError:
            print(f"❌ {package} - 未安装")
            missing.append(package)

    if missing:
        print(f"\n缺少依赖,请运行:")
        print(f"  pip install {' '.join(missing)}")
        return False
    return True


def check_modules():
    """检查应用模块"""
    modules = [
        'config.settings',
        'utils.theme',
        'utils.logger',
        'components.widgets',
        'cloudflared_cli',
        'modern_gui'
    ]

    sys.path.insert(0, str(Path(__file__).parent))

    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"✓ {module}")
        except Exception as e:
            print(f"❌ {module}: {e}")
            all_ok = False

    return all_ok


def check_cloudflared():
    """检查cloudflared"""
    try:
        import cloudflared_cli as cf
        path = cf.find_cloudflared()
        if path:
            version = cf.version(path)
            if version:
                print(f"✓ cloudflared: {path}")
                print(f"  版本: {version}")
                return True
            else:
                print(f"⚠ cloudflared找到但无法获取版本: {path}")
                return False
        else:
            print(f"⚠ cloudflared未找到")
            print(f"  提示: 启动应用后点击工具栏按钮下载或选择")
            return True  # 不阻止启动
    except Exception as e:
        print(f"❌ 检查cloudflared失败: {e}")
        return False


def check_directories():
    """检查必要目录"""
    dirs = ['config', 'logs', 'tunnels', 'assets', 'components', 'utils']

    for d in dirs:
        path = Path(__file__).parent / d
        if path.exists():
            print(f"✓ {d}/")
        else:
            print(f"⚠ {d}/ - 不存在,将自动创建")
            try:
                path.mkdir(parents=True, exist_ok=True)
                print(f"  已创建: {d}/")
            except Exception as e:
                print(f"  创建失败: {e}")

    return True


def check_network():
    """检查网络连接"""
    import urllib.request

    print("\n网络连接检查:")
    urls = [
        ("Cloudflare API", "https://api.cloudflare.com"),
        ("GitHub", "https://github.com")
    ]

    for name, url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            urllib.request.urlopen(req, timeout=5)
            print(f"✓ {name}: 可访问")
        except Exception as e:
            print(f"⚠ {name}: 无法访问 ({e})")
            print(f"  如果看到500错误,这是正常的,不影响应用使用")

    return True


def main():
    """主函数"""
    print("=" * 60)
    print("Cloudflare Tunnel Manager - 启动诊断")
    print("=" * 60)
    print()

    checks = [
        ("Python版本", check_python_version),
        ("依赖模块", check_dependencies),
        ("应用模块", check_modules),
        ("目录结构", check_directories),
        ("Cloudflared", check_cloudflared),
        ("网络连接", check_network)
    ]

    results = []
    for name, check_func in checks:
        print(f"\n检查 {name}:")
        print("-" * 60)
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ 检查失败: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("诊断总结:")
    print("=" * 60)

    critical_failed = []
    warnings = []

    for name, result in results:
        if result:
            print(f"✓ {name}")
        else:
            if name in ["Python版本", "依赖模块", "应用模块"]:
                print(f"❌ {name} - 关键问题")
                critical_failed.append(name)
            else:
                print(f"⚠ {name} - 警告")
                warnings.append(name)

    print()

    if critical_failed:
        print("❌ 发现关键问题,应用无法启动:")
        for issue in critical_failed:
            print(f"   - {issue}")
        print("\n请修复上述问题后重试。")
        return 1
    elif warnings:
        print("⚠ 发现警告,但不影响应用启动:")
        for warning in warnings:
            print(f"   - {warning}")
        print("\n应用可以启动,但某些功能可能受限。")
        print("\n按回车键继续启动应用...")
        input()
    else:
        print("✓ 所有检查通过!")
        print("\n启动应用...")

    # 启动应用
    try:
        print("\n" + "=" * 60)
        from modern_gui import run_modern_app
        run_modern_app()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        return 0
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(0)
