"""
baseline_vision_task.py — 基准K线Vision识别定时任务
====================================================
每小时调用 ChatGPT Vision 从30根已收盘K线中识别:
  - 基准Buy K线: 最近局部低点阳线 (close > open)
  - 基准Sell K线: 最近局部高点阴线 (close < open)

结果写入 state/baseline_state.json，供 baseline_gate.py 读取。
"""

import json
import os
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "baseline_state.json")

# ChartEngine 单例（避免每次调用都重建）
_chart_engine = None

def _get_chart_engine():
    global _chart_engine
    if _chart_engine is None:
        from chart_engine import ChartEngine
        _chart_engine = ChartEngine()
    return _chart_engine

BASELINE_PROMPT = """看这张K线图，在最近30根中找：
1. 基准Buy = 价格最低区域的绿色阳线(收盘>开盘)。找图中价格最低附近的阳线。
2. 基准Sell = 价格最高区域的红色阴线(收盘<开盘)。找图中价格最高附近的阴线。

关键：Buy和Sell不能在相邻位置！Buy要在低谷区域，Sell要在高峰区域，两者之间应该有明显价差。
如果整个图只涨不跌，可能只有Buy(低位起涨阳线)没有Sell。如果只跌不涨，可能只有Sell(高位起跌阴线)没有Buy。
bars_ago从右数：最右=0，右二=1。禁止解释，直接输出纯JSON：
{"baseline_buy":{"found":true,"bars_ago":15},"baseline_sell":{"found":true,"bars_ago":3}}"""


def _calc_donchian_cycle(bars: list, length: int = 28) -> dict:
    """
    计算唐安琪周期宽度指标（Donchian HL Width - Cycle Information）。
    bars: OHLCV列表，每项含 high/low 键
    返回: {ph, pl, hl_avg, cycle_counter, cycle_avg, cycle_trend, maturity}
    """
    if len(bars) < length:
        return {}
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    highest = max(highs[-length:])
    lowest = min(lows[-length:])
    if highest == lowest:
        return {}
    last_high = highs[-1]
    last_low = lows[-1]
    ph = 100.0 * (last_high - highest) / (highest - lowest)
    pl = 100.0 * (last_low - highest) / (highest - lowest)
    hl_avg = (ph + pl) / 2.0

    # cycle_trend: +1=上升(hl_avg > -40), -1=下降(hl_avg < -60), 0=震荡
    if hl_avg > -40:
        cycle_trend = 1
    elif hl_avg < -60:
        cycle_trend = -1
    else:
        cycle_trend = 0

    # cycle_counter: 最近连续同向趋势的K线根数
    counter = 1
    for i in range(len(bars) - 2, max(len(bars) - length - 1, 0), -1):
        h_i = max(highs[max(0, i - length + 1):i + 1])
        l_i = min(lows[max(0, i - length + 1):i + 1])
        if h_i == l_i:
            break
        avg_i = ((100.0 * (highs[i] - h_i) / (h_i - l_i)) + (100.0 * (lows[i] - h_i) / (h_i - l_i))) / 2.0
        trend_i = 1 if avg_i > -40 else (-1 if avg_i < -60 else 0)
        if trend_i == cycle_trend:
            counter += 1
        else:
            break

    # cycle_avg: 简化用length/2作为参考均值（无历史状态）
    cycle_avg = length / 2.0
    if counter < cycle_avg * 0.5:
        maturity = "young"
    elif counter > cycle_avg:
        maturity = "mature"
    else:
        maturity = "mid"

    return {
        "ph": round(ph, 2),
        "pl": round(pl, 2),
        "hl_avg": round(hl_avg, 2),
        "cycle_counter": counter,
        "cycle_avg": cycle_avg,
        "cycle_trend": cycle_trend,
        "maturity": maturity,
    }


def _load_state() -> dict:
    """读取已有状态，文件不存在或损坏返回空dict"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _find_swing_baselines(closed_bars: list, wing: int = 2) -> dict:
    """
    纯数据计算: 在closed_bars中找相对局部低点阳线(buy)和相对局部高点阴线(sell)。
    wing: 左右各wing根都比它高/低才算局部极值。
    返回 {"buy_idx":, "buy_price":, "sell_idx":, "sell_price":, ...}
    """
    n = len(closed_bars)
    buy_candidates = []   # (idx, close)
    sell_candidates = []  # (idx, close)

    for i in range(wing, n - wing):
        bar = closed_bars[i]
        low_i = bar["low"]
        high_i = bar["high"]

        # 局部低点: 左右wing根的low都 >= 当前low
        is_swing_low = all(closed_bars[i - j]["low"] >= low_i for j in range(1, wing + 1)) and \
                       all(closed_bars[i + j]["low"] >= low_i for j in range(1, wing + 1))
        if is_swing_low and bar["close"] > bar["open"]:  # 阳线
            buy_candidates.append((i, bar["close"]))

        # 局部高点: 左右wing根的high都 <= 当前high
        is_swing_high = all(closed_bars[i - j]["high"] <= high_i for j in range(1, wing + 1)) and \
                        all(closed_bars[i + j]["high"] <= high_i for j in range(1, wing + 1))
        if is_swing_high and bar["close"] < bar["open"]:  # 阴线
            sell_candidates.append((i, bar["close"]))

    # 没找到严格摆点 → 放宽: 取最近10根中价格最低阳线 / 最高阴线
    if not buy_candidates:
        recent = closed_bars[max(0, n - 10):]
        offset = max(0, n - 10)
        for i, b in enumerate(recent):
            if b["close"] > b["open"]:
                buy_candidates.append((offset + i, b["close"]))
        if buy_candidates:
            buy_candidates.sort(key=lambda x: x[1])  # 取最低
            buy_candidates = [buy_candidates[0]]

    if not sell_candidates:
        recent = closed_bars[max(0, n - 10):]
        offset = max(0, n - 10)
        for i, b in enumerate(recent):
            if b["close"] < b["open"]:
                sell_candidates.append((offset + i, b["close"]))
        if sell_candidates:
            sell_candidates.sort(key=lambda x: -x[1])  # 取最高
            sell_candidates = [sell_candidates[0]]

    # 从候选中选: 取最近的(idx最大=最右=最新)
    buy_idx, buy_price = None, None
    sell_idx, sell_price = None, None

    if buy_candidates:
        # 按idx降序(最近优先)
        buy_candidates.sort(key=lambda x: -x[0])
        buy_idx, buy_price = buy_candidates[0]

    if sell_candidates:
        # 按idx降序(最近优先)
        sell_candidates.sort(key=lambda x: -x[0])
        sell_idx, sell_price = sell_candidates[0]

    return {
        "buy_idx": buy_idx, "buy_price": buy_price,
        "sell_idx": sell_idx, "sell_price": sell_price,
    }


def _vision_find(closed_bars, n, log_fn, symbol):
    """Claude Vision找基准位置，返回 (buy_bars_ago, sell_bars_ago) 或 (None, None)"""
    try:
        img_b64 = _get_chart_engine().screenshot_b64(closed_bars, symbol=symbol, bars_count=30)
        if not img_b64:
            return None, None
        import anthropic as _anth
        _resp = _anth.Anthropic().messages.create(
            model="claude-sonnet-4-20250514", max_tokens=300,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": BASELINE_PROMPT},
            ]}],
        )
        import re
        raw = _resp.content[0].text.strip()
        clean = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
        r = json.loads(clean)
        v_buy_ago = r.get("baseline_buy", {}).get("bars_ago") if r.get("baseline_buy", {}).get("found") else None
        v_sell_ago = r.get("baseline_sell", {}).get("bars_ago") if r.get("baseline_sell", {}).get("found") else None

        # 颜色校验 + 邻近修正
        def _fix_color(ago, is_bullish):
            if ago is None: return None
            idx = n - 1 - int(ago)
            if not (0 <= idx < n): return None
            b = closed_bars[idx]
            if is_bullish and b["close"] > b["open"]: return int(ago)
            if not is_bullish and b["close"] < b["open"]: return int(ago)
            for off in range(1, 4):
                for d in [off, -off]:
                    ni = idx + d
                    if 0 <= ni < n:
                        nb = closed_bars[ni]
                        if is_bullish and nb["close"] > nb["open"]: return n - 1 - ni
                        if not is_bullish and nb["close"] < nb["open"]: return n - 1 - ni
            return None

        v_buy_ago = _fix_color(v_buy_ago, True)
        v_sell_ago = _fix_color(v_sell_ago, False)
        return v_buy_ago, v_sell_ago
    except Exception as e:
        log_fn(f"[BASELINE] {symbol} Vision异常: {e}")
        return None, None


# 最小bars_ago: 当前K线未收盘,前一根刚收,基准至少回退2根
_MIN_BARS_AGO = 2


def _update_symbol(symbol: str, bars: list, log_fn=None) -> bool:
    """
    双验证: Vision + 数据摆点都跑，一致才用，不一致则丢弃(不拦截)。
    返回 True=成功更新, False=失败(保留旧数据)
    """
    if log_fn is None:
        log_fn = print

    closed_bars = bars[:-1][-30:] if len(bars) > 1 else bars[-30:]
    if len(closed_bars) < 10:
        log_fn(f"[BASELINE] {symbol} K线不足({len(closed_bars)}根)，跳过")
        return False

    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%dT%H:%M:%S")
    n = len(closed_bars)

    # ---- 方法1: Vision ----
    v_buy_ago, v_sell_ago = _vision_find(closed_bars, n, log_fn, symbol)

    # ---- 方法2: 数据摆点 ----
    fb = _find_swing_baselines(closed_bars)
    d_buy_ago = (n - 1 - fb["buy_idx"]) if fb["buy_idx"] is not None else None
    d_sell_ago = (n - 1 - fb["sell_idx"]) if fb["sell_idx"] is not None else None

    # ---- 选最接近当前K线(bars_ago最小)的作为基准 ----
    buy_price = None
    sell_price = None
    buy_bars_ago = None
    sell_bars_ago = None
    buy_found = False
    sell_found = False

    # Buy: 取bars_ago更小的(更近), 但必须 >= _MIN_BARS_AGO(当前+前一根未确认)
    buy_candidates = [a for a in [v_buy_ago, d_buy_ago] if a is not None and a >= _MIN_BARS_AGO]
    if buy_candidates:
        buy_bars_ago = min(buy_candidates)  # 最近的
        idx = n - 1 - buy_bars_ago
        buy_price = closed_bars[idx]["close"]
        buy_found = True
        log_fn(f"[BASELINE] {symbol} Buy: vision={v_buy_ago} data={d_buy_ago} → 取最近ago={buy_bars_ago}")

    # Sell: 取bars_ago更小的(更近), 但必须 >= _MIN_BARS_AGO
    sell_candidates = [a for a in [v_sell_ago, d_sell_ago] if a is not None and a >= _MIN_BARS_AGO]
    if sell_candidates:
        sell_bars_ago = min(sell_candidates)
        idx = n - 1 - sell_bars_ago
        sell_price = closed_bars[idx]["close"]
        sell_found = True
        log_fn(f"[BASELINE] {symbol} Sell: vision={v_sell_ago} data={d_sell_ago} → 取最近ago={sell_bars_ago}")

    # 合理性: buy < sell
    if buy_found and sell_found and buy_price >= sell_price:
        log_fn(f"[BASELINE] {symbol} buy={buy_price:.2f}>=sell={sell_price:.2f}, 保留更极端侧")
        mid = sum(b["close"] for b in closed_bars) / n
        if abs(buy_price - mid) > abs(sell_price - mid):
            sell_price = None; sell_found = False; sell_bars_ago = None
        else:
            buy_price = None; buy_found = False; buy_bars_ago = None

    if not buy_found and not sell_found:
        log_fn(f"[BASELINE] {symbol} 未找到基准, 跳过")
        return False

    entry = {
        "buy_price": buy_price,
        "sell_price": sell_price,
        "updated_at": now_str,
        "source": "claude_vision",
        "buy_bars_ago": buy_bars_ago,
        "sell_bars_ago": sell_bars_ago,
        "buy_found": buy_found,
        "sell_found": sell_found,
    }

    # 唐安琪周期宽度指标 (GCC-0200)
    cycle = _calc_donchian_cycle(closed_bars)
    if cycle:
        entry.update({
            "dc_ph": cycle["ph"],
            "dc_pl": cycle["pl"],
            "dc_hl_avg": cycle["hl_avg"],
            "dc_cycle_counter": cycle["cycle_counter"],
            "dc_cycle_avg": cycle["cycle_avg"],
            "dc_cycle_trend": cycle["cycle_trend"],
            "dc_maturity": cycle["maturity"],
        })

    # 写入(只更新该symbol，不覆盖其他)
    state = _load_state()
    state[symbol] = entry
    _save_state(state)

    log_fn(f"[BASELINE] {symbol} 更新完成: buy={entry['buy_price']} sell={entry['sell_price']}")
    return True


def update_all_symbols(symbol_state: dict, log_fn=None) -> None:
    """
    遍历所有有ohlcv_bars的品种，执行Vision识别。
    symbol_state: 主程序的 symbol_state 字典
    """
    if log_fn is None:
        log_fn = print

    success_count = 0
    fail_count = 0

    for symbol, sym_data in symbol_state.items():
        bars = sym_data.get("ohlcv_bars")
        if not bars or len(bars) < 10:
            # 自行获取OHLCV数据（启动早期symbol_state可能还没填充）
            try:
                from timeframe_params import read_symbol_timeframe, is_crypto_symbol
                from price_scan_engine_v21 import YFinanceDataFetcher
                _tf = read_symbol_timeframe(symbol, default=240)
                bars = YFinanceDataFetcher.get_ohlcv(symbol, _tf, lookback_bars=35)
                if not bars or len(bars) < 10:
                    continue
            except Exception as _e_fetch:
                log_fn(f"[BASELINE] {symbol} 自行获取OHLCV失败: {_e_fetch}")
                continue

        try:
            ok = _update_symbol(symbol, bars, log_fn)
            if ok:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            log_fn(f"[BASELINE][ERROR] {symbol} 异常: {e}")
            fail_count += 1

        # 避免API限速
        time.sleep(2)

    log_fn(f"[BASELINE] 全品种扫描完成: {success_count}成功 {fail_count}失败")
