#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
设置加密货币每日偏向 (当前周期趋势)

用法:
  python set_bias.py                          # 使用默认配置
  python set_bias.py BTC=DOWN ETH=DOWN SOL=SIDE ZEC=UP  # 命令行指定
  python set_bias.py --show                   # 只显示当前设置
"""
import sys
import requests

URL = "http://localhost:6001/scalp_bias"

# ========== 默认偏向设置 (可被命令行覆盖) ==========
# 最后更新: 2026-01-23 17:25 截图分析
DEFAULT_BIAS = {
    # === 加密货币 ===
    "BTCUSDC": "DOWN",   # 红SuperTrend+EMA下方+MACD红柱，下跌趋势
    "ETHUSDC": "DOWN",   # 红SuperTrend+EMA下方+MACD红柱，下跌持续
    "SOLUSDC": "DOWN",   # 红SuperTrend+EMA下方，虽MACD微转绿但整体下跌
    "ZECUSDC": "SIDE",   # 通道中间震荡，SuperTrend绿但MACD弱，双向
    # === 美股 ===
    "TSLA": "SIDE",      # 红SuperTrend但EMA纠缠，MACD红柱弱，方向不明
    "AMD": "UP",         # 绿SuperTrend+EMA上方+MACD绿柱，上涨趋势
    "COIN": "DOWN",      # 红SuperTrend+EMA下方+MACD红柱，明显下跌
    "RKLB": "UP",        # 绿SuperTrend+EMA上方强势+MACD绿柱，强势上涨
    "RDDT": "DOWN",      # 红SuperTrend+EMA纠缠偏下+MACD红柱，偏空
    "HIMS": "DOWN",      # 红SuperTrend+EMA下方+MACD红柱，下跌趋势
    "CRWV": "SIDE",      # 绿SuperTrend但低位震荡，MACD弱，观望
    "NBIS": "UP",        # 绿SuperTrend+EMA上方+MACD绿柱弱，上涨中
    "ONDS": "UP",        # 绿SuperTrend+EMA上方强势+MACD绿柱，强势上涨
    "OPEN": "DOWN",      # 红SuperTrend+EMA下方+MACD红柱，持续下跌
}
# ==================================================

# 简写映射
SYMBOL_MAP = {
    # 加密货币
    "BTC": "BTCUSDC",
    "ETH": "ETHUSDC",
    "SOL": "SOLUSDC",
    "ZEC": "ZECUSDC",
    # 美股 (直接用股票代码，无需映射)
}

def show_current():
    """显示当前偏向设置"""
    try:
        resp = requests.get(URL, timeout=5)
        if resp.status_code == 200:
            print("当前偏向设置:")
            print(resp.json())
        else:
            print(f"获取失败: {resp.status_code}")
    except Exception as e:
        print(f"连接失败: {e}")

def set_bias(config):
    """设置偏向"""
    print("=" * 50)
    print("加密货币每日偏向设置")
    print("=" * 50)

    print("\n即将设置:")
    for symbol, bias in config.items():
        direction = {"UP": "只做多", "DOWN": "只做空", "SIDE": "双向"}.get(bias, bias)
        print(f"  {symbol}: {bias} ({direction})")

    try:
        resp = requests.post(URL, json={
            "batch": config,
            "save_file": True
        }, timeout=5)

        if resp.status_code == 200:
            print("\n✅ 设置成功!")
            print(resp.json())
        else:
            print(f"\n❌ 设置失败: {resp.status_code}")
            print(resp.text)
    except requests.exceptions.ConnectionError:
        print("\n❌ 连接失败 - 请确认服务器已启动")
    except Exception as e:
        print(f"\n❌ 错误: {e}")

def parse_args():
    """解析命令行参数"""
    if len(sys.argv) == 1:
        return DEFAULT_BIAS

    if "--show" in sys.argv:
        show_current()
        sys.exit(0)

    # 解析 BTC=DOWN ETH=UP 格式
    config = DEFAULT_BIAS.copy()
    for arg in sys.argv[1:]:
        if "=" in arg:
            symbol, bias = arg.upper().split("=", 1)
            # 支持简写
            full_symbol = SYMBOL_MAP.get(symbol, symbol)
            if bias in ("UP", "DOWN", "SIDE"):
                config[full_symbol] = bias
            else:
                print(f"⚠️ 无效偏向值: {bias} (应为 UP/DOWN/SIDE)")

    return config

def main():
    config = parse_args()
    set_bias(config)

if __name__ == "__main__":
    main()
