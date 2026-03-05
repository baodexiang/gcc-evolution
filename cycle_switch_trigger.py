#!/usr/bin/env python3
"""
P0-CycleSwitch 触发程序 v3.450
==============================

用途: 手动触发周期切换分析

当你在TradingView调整交易周期后，运行此程序立即获得新周期的交易建议。

用法:
  # 单个品种
  python cycle_switch_trigger.py BTCUSDC 240

  # 批量触发所有品种 (使用配置的周期)
  python cycle_switch_trigger.py --all

  # 指定服务器地址
  python cycle_switch_trigger.py BTCUSDC 240 --host http://localhost:6001

功能:
  1. 调用主程序API触发预加载
  2. 运行完整三方协商分析 (Tech+Human+DeepSeek)
  3. 输出BUY/HOLD/SELL建议
  4. 正常执行交易
  5. 发送邮件通知
"""

import argparse
import requests
import sys
import time


# 默认服务器地址
DEFAULT_HOST = "http://localhost:6001"

# 品种周期配置 (与主程序SYMBOL_TIMEFRAMES同步)
SYMBOL_TIMEFRAMES = {
    # 加密货币
    "ZECUSDC": 60,    # 1小时
    "BTCUSDC": 240,   # 4小时
    "ETHUSDC": 240,   # 4小时
    "SOLUSDC": 240,   # 4小时
    # 美股
    "TSLA": 240,
    "COIN": 240,
    "RDDT": 240,
    "HOOD": 240,
    "RKLB": 240,
    "HIMS": 240,
    "CRWV": 240,
    "NBIS": 240,
    "ONDS": 240,
    "OPEN": 240,
}


def trigger_single(host: str, symbol: str, timeframe: int) -> bool:
    """触发单个品种的周期切换分析"""
    url = f"{host}/trigger_cycle_switch"

    try:
        print(f"[触发] {symbol} → {timeframe}min ...")

        response = requests.post(url, json={
            "symbol": symbol,
            "timeframe": timeframe,
        }, timeout=10)

        if response.status_code == 200:
            result = response.json()
            print(f"[成功] {result.get('message', 'OK')}")
            return True
        else:
            print(f"[失败] HTTP {response.status_code}: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"[错误] 无法连接到服务器 {host}")
        print(f"       请确保主程序 llm_server_v3450.py 正在运行")
        return False
    except Exception as e:
        print(f"[错误] {e}")
        return False


def trigger_all(host: str) -> int:
    """批量触发所有品种"""
    url = f"{host}/trigger_cycle_switch_all"

    try:
        print(f"[批量触发] 所有品种 ...")

        response = requests.get(url, timeout=30)

        if response.status_code == 200:
            result = response.json()
            triggered = result.get("triggered", [])
            print(f"[成功] 已触发 {len(triggered)} 个品种:")
            for item in triggered:
                print(f"       - {item['symbol']} → {item['timeframe']}min")
            return len(triggered)
        else:
            print(f"[失败] HTTP {response.status_code}: {response.text}")
            return 0

    except requests.exceptions.ConnectionError:
        print(f"[错误] 无法连接到服务器 {host}")
        print(f"       请确保主程序 llm_server_v3450.py 正在运行")
        return 0
    except Exception as e:
        print(f"[错误] {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="P0-CycleSwitch 触发程序 - 手动触发周期切换分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cycle_switch_trigger.py BTCUSDC 240      # BTC切换到4小时周期
  python cycle_switch_trigger.py ZECUSDC 60       # ZEC切换到1小时周期
  python cycle_switch_trigger.py --all            # 批量触发所有品种
  python cycle_switch_trigger.py --list           # 列出所有品种配置
        """
    )

    parser.add_argument("symbol", nargs="?", help="交易品种 (如 BTCUSDC, TSLA)")
    parser.add_argument("timeframe", nargs="?", type=int, help="周期(分钟): 60=1h, 120=2h, 240=4h")
    parser.add_argument("--all", action="store_true", help="批量触发所有品种")
    parser.add_argument("--list", action="store_true", help="列出所有品种周期配置")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"服务器地址 (默认: {DEFAULT_HOST})")

    args = parser.parse_args()

    # 列出配置
    if args.list:
        print("\n品种周期配置:")
        print("-" * 30)
        for symbol, tf in SYMBOL_TIMEFRAMES.items():
            hours = tf / 60
            print(f"  {symbol:12} → {tf:4}min ({hours:.1f}h)")
        print()
        return

    # 批量触发
    if args.all:
        print("\n" + "=" * 50)
        print("P0-CycleSwitch 批量触发")
        print("=" * 50 + "\n")

        count = trigger_all(args.host)

        if count > 0:
            print(f"\n[完成] 已触发 {count} 个品种的周期切换分析")
            print(f"       分析结果将显示在主程序日志中")
            print(f"       交易执行后会发送邮件通知")
        return

    # 单个触发
    if not args.symbol:
        parser.print_help()
        print("\n[提示] 请指定品种和周期，或使用 --all 批量触发")
        return

    if not args.timeframe:
        # 使用配置的默认周期
        default_tf = SYMBOL_TIMEFRAMES.get(args.symbol.upper())
        if default_tf:
            args.timeframe = default_tf
            print(f"[提示] 使用默认周期: {args.timeframe}min")
        else:
            print(f"[错误] 请指定周期(分钟)，如: python cycle_switch_trigger.py {args.symbol} 240")
            return

    print("\n" + "=" * 50)
    print("P0-CycleSwitch 手动触发")
    print("=" * 50 + "\n")

    success = trigger_single(args.host, args.symbol.upper(), args.timeframe)

    if success:
        print(f"\n[完成] 已触发 {args.symbol} 的周期切换分析 ({args.timeframe}min)")
        print(f"       分析结果将显示在主程序日志中")
        print(f"       交易执行后会发送邮件通知")


if __name__ == "__main__":
    main()
