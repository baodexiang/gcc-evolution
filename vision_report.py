#!/usr/bin/env python3
"""
Vision覆盖监控报告 v1.0
快速查看Vision vs L1对比数据

用法:
    python vision_report.py           # 综合报告
    python vision_report.py --today   # 今日覆盖
    python vision_report.py --week    # 本周统计
    python vision_report.py --log     # 最近日志
"""

import os
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# 路径配置
BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "logs" / "server.log"
VISION_DIR = BASE_DIR / "state" / "vision"
VISION_HISTORY = VISION_DIR / "vision_history.json"
VISION_VS_L1 = VISION_DIR / "vision_vs_l1.json"
VERIFICATION_LOG = VISION_DIR / "verification_log.txt"


def parse_override_from_log(line: str) -> dict:
    """解析日志中的Vision覆盖记录"""
    # [v3.580] Vision覆盖当前周期: L1=DOWN(TRENDING) -> Vision=SIDE(RANGING) conf=0.85
    pattern = r'\[v3\.580\].*?Vision覆盖当前周期.*?L1=(\w+)\((\w+)\).*?Vision=(\w+)\((\w+)\).*?conf=([\d.]+)'
    match = re.search(pattern, line)
    if match:
        return {
            "l1_direction": match.group(1),
            "l1_regime": match.group(2),
            "vision_direction": match.group(3),
            "vision_regime": match.group(4),
            "confidence": float(match.group(5)),
        }
    return None


def get_recent_overrides(lines: int = 50) -> list:
    """获取最近的覆盖记录"""
    if not LOG_FILE.exists():
        return []

    overrides = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.readlines()

        for line in content[-5000:]:  # 只看最近5000行
            if "[v3.580]" in line and "Vision覆盖当前周期" in line:
                # 提取时间戳（如果有）
                time_match = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', line)
                timestamp = time_match.group(1) if time_match else "Unknown"

                # 提取品种
                symbol_match = re.search(r'(BTC|ETH|SOL|ZEC|TSLA|COIN|AMD|RDDT|RKLB|NBIS|CRWV|HIMS|OPEN|ONDS)', line)
                symbol = symbol_match.group(1) if symbol_match else "Unknown"

                parsed = parse_override_from_log(line)
                if parsed:
                    parsed["timestamp"] = timestamp
                    parsed["symbol"] = symbol
                    overrides.append(parsed)
    except Exception as e:
        print(f"读取日志失败: {e}")

    return overrides[-lines:]


def get_vision_history() -> list:
    """获取Vision分析历史"""
    if not VISION_HISTORY.exists():
        return []
    try:
        with open(VISION_HISTORY, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("records", [])
    except:
        return []


def get_vision_vs_l1() -> dict:
    """获取Vision vs L1对比数据"""
    if not VISION_VS_L1.exists():
        return {"comparisons": [], "stats": {}}
    try:
        with open(VISION_VS_L1, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"comparisons": [], "stats": {}}


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_today_report():
    """打印今日覆盖报告"""
    print_header("今日Vision覆盖报告")

    today = datetime.now().strftime("%Y-%m-%d")
    overrides = get_recent_overrides(100)

    # 筛选今日记录
    today_overrides = [o for o in overrides if today in o.get("timestamp", "")]

    if not today_overrides:
        print("\n  今日暂无Vision覆盖记录")
        print("\n  可能原因:")
        print("  1. Vision与L1判断一致，无需覆盖")
        print("  2. Vision置信度未达到0.80阈值")
        print("  3. 主程序刚启动，尚未收到TV K线推送")
        return

    # 按品种统计
    by_symbol = defaultdict(list)
    for o in today_overrides:
        by_symbol[o["symbol"]].append(o)

    print(f"\n  今日覆盖次数: {len(today_overrides)}")
    print("\n  按品种统计:")
    print("  " + "-" * 50)
    print(f"  {'品种':<10} {'次数':<6} {'方向变化':<20} {'平均置信度':<10}")
    print("  " + "-" * 50)

    for symbol, records in by_symbol.items():
        direction_changes = [f"{r['l1_direction']}->{r['vision_direction']}" for r in records]
        most_common = max(set(direction_changes), key=direction_changes.count)
        avg_conf = sum(r["confidence"] for r in records) / len(records)
        print(f"  {symbol:<10} {len(records):<6} {most_common:<20} {avg_conf:.2f}")

    print("\n  详细记录:")
    print("  " + "-" * 50)
    for o in today_overrides[-10:]:  # 最近10条
        print(f"  [{o['timestamp'][-8:]}] {o['symbol']}: {o['l1_direction']}({o['l1_regime']}) -> {o['vision_direction']}({o['vision_regime']}) conf={o['confidence']:.2f}")


def print_week_report():
    """打印本周统计报告"""
    print_header("本周Vision覆盖统计")

    # 获取本周开始日期
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_start_str = week_start.strftime("%Y-%m-%d")

    overrides = get_recent_overrides(500)

    # 筛选本周记录
    week_overrides = []
    for o in overrides:
        ts = o.get("timestamp", "")
        if ts >= week_start_str:
            week_overrides.append(o)

    if not week_overrides:
        print("\n  本周暂无Vision覆盖记录")
        return

    # 统计
    total = len(week_overrides)
    by_direction = defaultdict(int)
    by_regime_change = defaultdict(int)
    confidence_sum = 0

    for o in week_overrides:
        by_direction[f"{o['l1_direction']}->{o['vision_direction']}"] += 1
        by_regime_change[f"{o['l1_regime']}->{o['vision_regime']}"] += 1
        confidence_sum += o["confidence"]

    print(f"\n  统计周期: {week_start_str} ~ {today.strftime('%Y-%m-%d')}")
    print(f"  总覆盖次数: {total}")
    print(f"  平均置信度: {confidence_sum/total:.2f}")

    print("\n  方向变化分布:")
    for change, count in sorted(by_direction.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"    {change:<15} {count:>3}次 ({pct:.1f}%)")

    print("\n  Regime变化分布:")
    for change, count in sorted(by_regime_change.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"    {change:<25} {count:>3}次 ({pct:.1f}%)")


def print_log_report():
    """打印最近日志"""
    print_header("最近Vision相关日志")

    if not LOG_FILE.exists():
        print("\n  日志文件不存在")
        return

    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.readlines()

        vision_lines = []
        for line in content[-2000:]:
            if "[v3.580]" in line or "[v3.570]" in line and "Vision" in line:
                vision_lines.append(line.strip())

        if not vision_lines:
            print("\n  最近无Vision相关日志")
            return

        print(f"\n  最近 {min(30, len(vision_lines))} 条Vision日志:\n")
        for line in vision_lines[-30:]:
            # 截断过长的行
            if len(line) > 100:
                line = line[:97] + "..."
            print(f"  {line}")

    except Exception as e:
        print(f"\n  读取日志失败: {e}")


def print_full_report():
    """打印综合报告"""
    print_header("Vision覆盖监控综合报告")
    print(f"  报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 检查文件状态
    print("\n  数据文件状态:")
    files = [
        ("主程序日志", LOG_FILE),
        ("Vision历史", VISION_HISTORY),
        ("对比记录", VISION_VS_L1),
        ("验证日志", VERIFICATION_LOG),
    ]
    for name, path in files:
        status = "Y" if path.exists() else "N"
        print(f"    {name:<12} [{status}] {path}")

    # 今日简报
    print_today_report()

    # 本周统计
    print_week_report()

    # Vision analyzer状态
    print_header("Vision Analyzer状态")
    vs_l1 = get_vision_vs_l1()
    stats = vs_l1.get("stats", {})
    if stats:
        print(f"\n  总对比次数: {stats.get('total', 0)}")
        print(f"  匹配率: {stats.get('match_rate', 0)*100:.1f}%")
        print(f"  Vision准确率: {stats.get('vision_accuracy', 'N/A')}")
        print(f"  L1准确率: {stats.get('l1_accuracy', 'N/A')}")
    else:
        print("\n  暂无统计数据")
        print("  运行 'python vision_analyzer.py' 开始收集数据")


def main():
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--today", "-t"]:
            print_today_report()
        elif arg in ["--week", "-w"]:
            print_week_report()
        elif arg in ["--log", "-l"]:
            print_log_report()
        elif arg in ["--help", "-h"]:
            print(__doc__)
        else:
            print(f"未知参数: {arg}")
            print("使用 --help 查看帮助")
    else:
        print_full_report()


if __name__ == "__main__":
    main()
