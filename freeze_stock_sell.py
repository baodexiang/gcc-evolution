#!/usr/bin/env python3
"""
美股冻结脚本 v1.2
冻结美股外挂+P0-Tracking的买入或卖出功能到次日纽约时间8AM

用法:
    python freeze_stock_sell.py           # 冻结美股卖出(默认)
    python freeze_stock_sell.py buy       # 冻结美股买入
    python freeze_stock_sell.py --status  # 查看状态
"""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 美股品种列表 (与扫描引擎配置一致)
US_STOCK_SYMBOLS = ["TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "AMD", "ONDS"]

# 外挂状态文件 (扫描引擎)
STATE_FILES = {
    "supertrend": "scan_supertrend_state.json",
    "rob_hoffman": "scan_rob_hoffman_state.json",
    "double_pattern": "scan_double_pattern_state.json",
    "feiyun": "scan_feiyun_state.json",
    "macd_divergence": "scan_macd_divergence_state.json",
    "supertrend_av2": "scan_supertrend_av2_state.json",
}

# P0-Tracking状态文件
P0_TRACKING_FILE = "scan_tracking_state.json"


def get_ny_now():
    return datetime.now(ZoneInfo("America/New_York"))


def get_next_8am_ny():
    ny_now = get_ny_now()
    today_8am = ny_now.replace(hour=8, minute=0, second=0, microsecond=0)
    if ny_now < today_8am:
        return today_8am
    else:
        return today_8am + timedelta(days=1)


def safe_json_read(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"读取失败: {e}")
    return None


def safe_json_write(filepath, data):
    try:
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        print(f"写入失败: {e}")
        return False


def freeze_stock(mode="sell"):
    """
    冻结美股买入或卖出, 包括P0-Tracking
    mode="sell": 冻结卖出(默认), 允许买入
    mode="buy":  冻结买入, 允许卖出
    """
    freeze_until = get_next_8am_ny()
    freeze_str = freeze_until.isoformat()

    action_cn = "买入" if mode == "buy" else "卖出"
    print(f"\n冻结美股{action_cn}到: {freeze_until.strftime('%Y-%m-%d %H:%M:%S')} NY")
    print("=" * 60)

    count = 0

    # 1. 冻结普通外挂
    for plugin_name, state_file in STATE_FILES.items():
        if not os.path.exists(state_file):
            continue

        data = safe_json_read(state_file)
        if not data:
            continue

        symbols = data.get("symbols", {})
        modified = False

        for symbol in US_STOCK_SYMBOLS:
            if symbol not in symbols:
                symbols[symbol] = {
                    "freeze_until": None,
                    "last_signal": None,
                    "last_trigger_time": None,
                    "buy_used": False,
                    "sell_used": False,
                    "reset_date": None,
                }

            if mode == "buy":
                symbols[symbol]["buy_used"] = True
                symbols[symbol]["sell_used"] = False
            else:
                symbols[symbol]["buy_used"] = False
                symbols[symbol]["sell_used"] = True
            symbols[symbol]["freeze_until"] = freeze_str
            modified = True
            count += 1

            buy_status = "FROZEN" if symbols[symbol]["buy_used"] else "OK"
            sell_status = "FROZEN" if symbols[symbol]["sell_used"] else "OK"
            print(f"  [{plugin_name}] {symbol} BUY={buy_status} | SELL={sell_status}")

        if modified:
            data["symbols"] = symbols
            data["updated_at"] = get_ny_now().isoformat()
            safe_json_write(state_file, data)

    # 2. 冻结P0-Tracking (重要!)
    if os.path.exists(P0_TRACKING_FILE):
        data = safe_json_read(P0_TRACKING_FILE)
        if data:
            symbols = data.get("symbols", {})
            modified = False

            print(f"\n  【P0-Tracking】")
            for symbol in US_STOCK_SYMBOLS:
                if symbol in symbols:
                    if mode == "buy":
                        # 冻结买入和移动止盈
                        symbols[symbol]["buy_used"] = True
                        symbols[symbol]["trailing_buy_used"] = True
                        symbols[symbol]["freeze_until"] = freeze_str
                        # 允许卖出和移动止损
                        symbols[symbol]["sell_used"] = False
                        symbols[symbol]["trailing_stop_used"] = False
                    else:
                        # 冻结卖出和移动止损
                        symbols[symbol]["sell_used"] = True
                        symbols[symbol]["trailing_stop_used"] = True
                        symbols[symbol]["freeze_until"] = freeze_str
                        # 允许买入和移动止盈
                        symbols[symbol]["buy_used"] = False
                        symbols[symbol]["trailing_buy_used"] = False
                    modified = True
                    count += 1

                    buy_status = "FROZEN" if symbols[symbol]["buy_used"] else "OK"
                    sell_status = "FROZEN" if symbols[symbol]["sell_used"] else "OK"
                    trailing_label = "TRAILING_BUY" if mode == "buy" else "TRAILING_STOP"
                    trailing_frozen = symbols[symbol].get("trailing_buy_used" if mode == "buy" else "trailing_stop_used", False)
                    trailing_status = "FROZEN" if trailing_frozen else "OK"
                    print(f"  [P0-Tracking] {symbol} BUY={buy_status} | SELL={sell_status} | {trailing_label}={trailing_status}")

            if modified:
                data["symbols"] = symbols
                data["updated_at"] = get_ny_now().isoformat()
                safe_json_write(P0_TRACKING_FILE, data)

    print("=" * 60)
    print(f"完成！{count}个美股外挂+P0 {action_cn}已冻结")
    other_action = "卖出" if mode == "buy" else "买入"
    print(f"{other_action}仍可用，{action_cn}冻结到次日8AM NY")


def show_status():
    ny_now = get_ny_now()
    print(f"\n当前纽约时间: {ny_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 普通外挂状态
    for plugin_name, state_file in STATE_FILES.items():
        if not os.path.exists(state_file):
            continue

        data = safe_json_read(state_file)
        if not data:
            continue

        symbols = data.get("symbols", {})
        has_stock = False

        for symbol in US_STOCK_SYMBOLS:
            if symbol in symbols:
                if not has_stock:
                    print(f"\n【{plugin_name}】")
                    has_stock = True

                state = symbols[symbol]
                buy = "BUY=OK" if not state.get("buy_used") else "BUY=USED"
                sell = "SELL=OK" if not state.get("sell_used") else "SELL=FROZEN"
                print(f"  {symbol}: {buy} | {sell}")

    # 2. P0-Tracking状态
    if os.path.exists(P0_TRACKING_FILE):
        data = safe_json_read(P0_TRACKING_FILE)
        if data:
            symbols = data.get("symbols", {})
            has_stock = False

            for symbol in US_STOCK_SYMBOLS:
                if symbol in symbols:
                    if not has_stock:
                        print(f"\n【P0-Tracking】")
                        has_stock = True

                    state = symbols[symbol]
                    buy = "BUY=OK" if not state.get("buy_used") else "BUY=USED"
                    sell = "SELL=OK" if not state.get("sell_used") else "SELL=FROZEN"
                    trailing = "TRAILING=OK" if not state.get("trailing_stop_used") else "TRAILING=FROZEN"
                    print(f"  {symbol}: {buy} | {sell} | {trailing}")

    print("\n" + "=" * 60)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--status", "-s"):
        show_status()
    elif len(sys.argv) > 1 and sys.argv[1].lower() == "buy":
        freeze_stock(mode="buy")
        print("\n当前状态:")
        show_status()
    else:
        freeze_stock(mode="sell")
        print("\n当前状态:")
        show_status()


if __name__ == "__main__":
    main()
