#!/usr/bin/env python3
"""
隧道网络诊断工具
提供：
1. 实时连接状态监控
2. 网络延迟测量
3. 错误分类诊断
4. 边缘节点诊断
5. 连接质量评分
"""

import subprocess
import json
import time
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


class ConnectionQualityMetrics:
    """连接质量指标"""
    def __init__(self):
        self.latencies = []
        self.max_history = 50

    def add_latency(self, latency: float):
        """添加延迟测量"""
        self.latencies.append(latency)
        if len(self.latencies) > self.max_history:
            self.latencies.pop(0)

    def get_avg_latency(self) -> Optional[float]:
        """获取平均延迟"""
        return sum(self.latencies) / len(self.latencies) if self.latencies else None

    def get_p95_latency(self) -> Optional[float]:
        """获取 P95 延迟"""
        if not self.latencies or len(self.latencies) < 2:
            return None
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[idx]

    def get_max_latency(self) -> Optional[float]:
        """获取最大延迟"""
        return max(self.latencies) if self.latencies else None

    def get_stability_score(self) -> int:
        """
        获取连接稳定性评分 (0-100)
        基于延迟抖动和失败率
        """
        if not self.latencies:
            return 0

        if len(self.latencies) < 3:
            return 50

        # 计算变异系数（衡量抖动）
        avg = self.get_avg_latency()
        variance = sum((x - avg) ** 2 for x in self.latencies) / len(self.latencies)
        std_dev = variance ** 0.5
        cv = std_dev / avg if avg > 0 else 0

        # 将 CV 转换为稳定性评分
        # CV 越小越稳定
        stability = max(0, 100 - int(cv * 100))
        return stability


class TunnelDiagnostics:
    """隧道诊断工具"""

    def __init__(self, cloudflared_path: str, tunnel_name: str):
        self.cloudflared_path = cloudflared_path
        self.tunnel_name = tunnel_name
        self.metrics = ConnectionQualityMetrics()
        self.error_counts = {}

    def get_tunnel_info(self) -> Optional[Dict[str, Any]]:
        """获取隧道信息"""
        try:
            result = subprocess.run(
                [self.cloudflared_path, "tunnel", "info", "--output", "json", self.tunnel_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return None

    def diagnose_connectors(self) -> Dict[str, Any]:
        """诊断连接器状态"""
        info = self.get_tunnel_info()
        if not info:
            return {"status": "error", "message": "无法获取隧道信息"}

        conns = info.get("conns", [])
        if not conns:
            return {
                "status": "no_connector",
                "message": "未检测到活跃连接器",
                "connectors": [],
            }

        connectors_data = []
        total_edges = 0

        for conn in conns:
            if not isinstance(conn, dict):
                continue

            conn_id = conn.get("id", "unknown")
            version = conn.get("version", "unknown")
            arch = conn.get("arch", "unknown")
            run_at = conn.get("run_at", conn.get("created_at", "unknown"))

            edges = conn.get("conns", [])
            if isinstance(edges, list):
                edge_count = len(edges)
                total_edges += edge_count
            else:
                edge_count = 0

            edge_details = []
            if isinstance(edges, list):
                for edge in edges:
                    if isinstance(edge, dict):
                        edge_details.append({
                            "colo": edge.get("colo_name", "unknown"),
                            "origin_ip": edge.get("origin_ip", "unknown"),
                            "opened_at": edge.get("opened_at", "unknown"),
                        })

            connectors_data.append({
                "id": conn_id,
                "version": version,
                "arch": arch,
                "run_at": run_at,
                "edge_count": edge_count,
                "edges": edge_details,
            })

        return {
            "status": "ok" if total_edges > 0 else "degraded",
            "total_connectors": len(connectors_data),
            "total_edges": total_edges,
            "connectors": connectors_data,
        }

    def diagnose_edge_nodes(self) -> Dict[str, Any]:
        """诊断边缘节点分布"""
        info = self.get_tunnel_info()
        if not info:
            return {"status": "error", "colos": []}

        colos = {}
        conns = info.get("conns", [])

        for conn in conns:
            if not isinstance(conn, dict):
                continue
            edges = conn.get("conns", [])
            if isinstance(edges, list):
                for edge in edges:
                    if isinstance(edge, dict):
                        colo = edge.get("colo_name", "unknown")
                        if colo not in colos:
                            colos[colo] = {"count": 0, "details": []}
                        colos[colo]["count"] += 1
                        colos[colo]["details"].append({
                            "origin_ip": edge.get("origin_ip"),
                            "opened_at": edge.get("opened_at"),
                        })

        return {
            "status": "ok" if colos else "no_edges",
            "total_colos": len(colos),
            "colos": colos,
        }

    def diagnose_connection_age(self) -> Dict[str, Any]:
        """诊断连接年龄"""
        from datetime import datetime, timezone

        info = self.get_tunnel_info()
        if not info:
            return {"status": "error", "connections": []}

        connections = []
        conns = info.get("conns", [])
        now = datetime.now(timezone.utc)

        for conn in conns:
            if not isinstance(conn, dict):
                continue

            run_at_str = conn.get("run_at", conn.get("created_at", ""))
            if not run_at_str:
                continue

            try:
                # 解析时间戳
                run_at = datetime.fromisoformat(run_at_str.replace("Z", "+00:00"))
                age = (now - run_at).total_seconds()

                # 健康度判断
                if age < 3600:  # 小于1小时
                    health = "excellent"
                elif age < 86400:  # 小于1天
                    health = "good"
                elif age < 604800:  # 小于1周
                    health = "fair"
                else:
                    health = "stale"  # 可能是僵尸连接

                connections.append({
                    "connector_id": conn.get("id", "unknown"),
                    "run_at": run_at_str,
                    "age_seconds": int(age),
                    "age_human": self._format_duration(age),
                    "health": health,
                })
            except Exception:
                continue

        return {
            "status": "ok" if connections else "no_connections",
            "connections": connections,
        }

    def full_diagnostic_report(self) -> str:
        """生成完整诊断报告"""
        report_lines = [
            f"\n{'=' * 70}",
            f"隧道诊断报告 - {self.tunnel_name}",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"{'=' * 70}\n",
        ]

        # 连接器诊断
        report_lines.append("【连接器状态】")
        conn_diag = self.diagnose_connectors()
        if conn_diag["status"] == "error":
            report_lines.append(f"  ✗ {conn_diag['message']}")
        else:
            report_lines.append(f"  活跃连接器: {conn_diag['total_connectors']}")
            report_lines.append(f"  活跃边缘节点: {conn_diag['total_edges']}")
            for i, conn in enumerate(conn_diag["connectors"], 1):
                report_lines.append(f"\n  连接器 {i}:")
                report_lines.append(f"    ID: {conn['id']}")
                report_lines.append(f"    版本: {conn['version']} ({conn['arch']})")
                report_lines.append(f"    启动于: {conn['run_at']}")
                report_lines.append(f"    边缘节点数: {conn['edge_count']}")
                for j, edge in enumerate(conn["edges"], 1):
                    report_lines.append(f"      节点 {j}: {edge['colo']} ({edge['origin_ip']})")

        # 边缘节点诊断
        report_lines.append("\n【边缘节点分布】")
        edge_diag = self.diagnose_edge_nodes()
        if edge_diag["status"] == "error":
            report_lines.append("  无可用的边缘节点")
        else:
            report_lines.append(f"  地域数量: {edge_diag['total_colos']}")
            for colo, data in sorted(edge_diag["colos"].items()):
                report_lines.append(f"    {colo}: {data['count']} 连接")

        # 连接年龄诊断
        report_lines.append("\n【连接新鲜度】")
        age_diag = self.diagnose_connection_age()
        if age_diag["status"] == "error":
            report_lines.append("  无活跃连接")
        else:
            for conn in age_diag["connections"]:
                health_symbol = "✓" if conn["health"] != "stale" else "⚠"
                report_lines.append(
                    f"  {health_symbol} {conn['connector_id']}: {conn['age_human']} ({conn['health']})"
                )

        # 稳定性评分
        report_lines.append("\n【稳定性评分】")
        stability = self.metrics.get_stability_score()
        avg_latency = self.metrics.get_avg_latency()
        p95_latency = self.metrics.get_p95_latency()

        report_lines.append(f"  稳定性评分: {stability}/100")
        if avg_latency:
            report_lines.append(f"  平均延迟: {avg_latency:.0f}ms")
        if p95_latency:
            report_lines.append(f"  P95 延迟: {p95_latency:.0f}ms")

        report_lines.append(f"\n{'=' * 70}\n")
        return "\n".join(report_lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            return f"{int(seconds / 60)}分钟"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}小时"
        else:
            return f"{int(seconds / 86400)}天"


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python diagnose.py <cloudflared_path> [tunnel_name]")
        sys.exit(1)

    cloudflared_path = sys.argv[1]
    tunnel_name = sys.argv[2] if len(sys.argv) > 2 else "homepage"

    diag = TunnelDiagnostics(cloudflared_path, tunnel_name)
    print(diag.full_diagnostic_report())

    # 交互式诊断
    while True:
        print("\n选择诊断项目:")
        print("1. 连接器状态")
        print("2. 边缘节点分布")
        print("3. 连接新鲜度")
        print("4. 完整报告")
        print("5. 退出")

        choice = input("\n请输入 (1-5): ").strip()

        if choice == "1":
            print(json.dumps(diag.diagnose_connectors(), indent=2, ensure_ascii=False))
        elif choice == "2":
            print(json.dumps(diag.diagnose_edge_nodes(), indent=2, ensure_ascii=False))
        elif choice == "3":
            print(json.dumps(diag.diagnose_connection_age(), indent=2, ensure_ascii=False))
        elif choice == "4":
            print(diag.full_diagnostic_report())
        elif choice == "5":
            break


if __name__ == "__main__":
    main()
