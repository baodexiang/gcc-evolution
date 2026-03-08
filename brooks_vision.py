#!/usr/bin/env python3
"""
Brooks Vision v2.6 — Al Brooks 形态识别 + 视觉雷达 (形态驱动架构)

GPT-5.2 看4H蜡烛图，识别经典技术形态+Brooks形态 → 形态自带方向驱动信号 → Brooks框架验证。
支持21种形态: 14种方向型(头肩/双顶底/三角/楔形/旗形/MTR等) + 5种环境型 + NONE。

管线: Vision看图+Brooks形态 → EMA10+RSI过滤 → L2对比 → 每日限1买1卖(8AM NY重置)

运行方式:
    python brooks_vision.py --once          # 单次扫描
    python brooks_vision.py --report        # 生成日报

KEY-006: Brooks Vision vs L2 信号 A/B 对比
"""

import json
import logging
import os
import smtplib
import ssl
import time
import traceback
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [BROOKS_VISION] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("brooks_vision")

def _gcc_log(msg: str):
    """GCC审计日志 — 同时写logger和log_to_server(server.log可查)"""
    logger.info(msg)
    try:
        from llm_server_v3640 import log_to_server
        log_to_server(msg)
    except Exception:
        pass

NY_TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Paths (保持不变，兼容历史数据)
# ---------------------------------------------------------------------------
STATE_DIR = Path("state")
LOG_FILE = STATE_DIR / "vision_radar_log.jsonl"
DAILY_STATE_FILE = STATE_DIR / "vision_radar_daily_limit.json"

# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
CRYPTO_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "ZEC-USD"]
STOCK_SYMBOLS = ["TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS",
                 "OPEN", "AMD", "ONDS", "PLTR"]
ALL_SYMBOLS = CRYPTO_SYMBOLS + STOCK_SYMBOLS

INTERNAL_TO_YF = {
    "BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD",
}
YF_TO_INTERNAL = {v: k for k, v in INTERNAL_TO_YF.items()}

# ---------------------------------------------------------------------------
# Pattern Signal Map: 形态→固有方向 (None=环境型,方向由Always-In决定)
# ---------------------------------------------------------------------------
PATTERN_SIGNAL_MAP = {
    # 看涨形态 → BUY
    "DOUBLE_BOTTOM": "BUY",
    "HEAD_SHOULDERS_BOTTOM": "BUY",
    "ASC_TRIANGLE": "BUY",
    "WEDGE_FALLING": "BUY",       # 下降楔形=看涨反转
    "CUP_AND_HANDLE": "BUY",
    "ROUNDING_BOTTOM": "BUY",
    "BULL_FLAG": "BUY",
    "MTR_BUY": "BUY",             # Major Trend Reversal 看涨

    # 看跌形态 → SELL
    "DOUBLE_TOP": "SELL",
    "HEAD_SHOULDERS_TOP": "SELL",
    "DESC_TRIANGLE": "SELL",
    "WEDGE_RISING": "SELL",       # 上升楔形=看跌反转
    "BEAR_FLAG": "SELL",
    "MTR_SELL": "SELL",           # Major Trend Reversal 看跌

    # 环境型(方向由 Always-In 决定)
    "CLIMAX": None,               # 高潮反转，方向取决于之前趋势
    "TIGHT_CHANNEL": None,        # 延续，方向取决于通道方向
    "BROAD_CHANNEL": None,        # 宽通道，EMA 回调
    "BREAKOUT": None,             # 方向取决于突破方向
    "TRADING_RANGE": None,        # 区间，高抛低吸

    # 无形态
    "NONE": None,
}

# ---------------------------------------------------------------------------
# Brooks Vision Prompt (v2.6: 扩展形态识别+形态驱动方向)
# ---------------------------------------------------------------------------
RADAR_PROMPT = """You are an expert price action trader trained in Al Brooks methodology and Rose's practical rules. Study this 4H chart carefully.

TASK: Determine if there is a clear BUY or SELL opportunity RIGHT NOW.

ANALYSIS STEPS (follow in order):

1. ALWAYS-IN DIRECTION:
   If forced to hold a position right now, would it be LONG or SHORT?
   - Price above EMA = bulls in control → lean BUY
   - Price below EMA = bears in control → lean SELL
   - This is your baseline direction. Do NOT trade against it without strong reason.

2. IDENTIFY THE ENVIRONMENT (this changes everything):
   - STRONG_TREND: HH+HL sequence, pullbacks <50%, EMA aligned → trade WITH trend only. 80% of reversals FAIL.
   - WEAK_TREND: Pullbacks 50-66%, narrow channel → still with trend but be cautious. 75% channel-end reversal.
   - TRADING_RANGE: No HH/HL, overlapping bars, >20 bars sideways → buy low/sell high. 80% of breakouts FAIL.
   - EXHAUSTION: 3+ pushes done, pullback >66%, wedge shape → prepare for reversal. 60% become trading range.
   - CLIMAX: 3+ consecutive large trend bars, far from EMA → do NOT chase. Only 25% continue next bar.
   - NEWS_DAY: If major news expected → reduce size or stay out. 75% initial move reverses.

3. PATTERN RECOGNITION (with probability):
   A. CLASSIC REVERSAL/CONTINUATION PATTERNS (each has inherent direction):
   - DOUBLE_BOTTOM: Two tests of support, second holds → BUY. 80% valid in trading range.
   - DOUBLE_TOP: Two tests of resistance, second fails → SELL. 80% valid in trading range.
   - HEAD_SHOULDERS_BOTTOM: Left shoulder + head (lower low) + right shoulder → BUY. Neckline break confirms.
   - HEAD_SHOULDERS_TOP: Left shoulder + head (higher high) + right shoulder → SELL. Neckline break confirms.
   - ASC_TRIANGLE: Higher lows + flat resistance → BUY. 75% break upward.
   - DESC_TRIANGLE: Lower highs + flat support → SELL. 75% break downward.
   - WEDGE_FALLING: 3 pushes down with decreasing momentum → BUY (bullish reversal). 75% reversal rate.
   - WEDGE_RISING: 3 pushes up with decreasing momentum → SELL (bearish reversal). 75% reversal rate.
   - CUP_AND_HANDLE: U-shape recovery + small pullback → BUY. Breakout above handle confirms.
   - ROUNDING_BOTTOM: Gradual U-shape base → BUY. Slow accumulation pattern.
   - BULL_FLAG: Strong up-move + tight pullback channel → BUY. Continuation pattern.
   - BEAR_FLAG: Strong down-move + tight pullback channel → SELL. Continuation pattern.
   - MTR_BUY: Major Trend Reversal bullish — first attempt fails, second succeeds → BUY. ~40% success.
   - MTR_SELL: Major Trend Reversal bearish — first attempt fails, second succeeds → SELL. ~40% success.

   B. ENVIRONMENT PATTERNS (direction determined by Always-In analysis):
   - CLIMAX: 3+ large consecutive bars → exhaustion. Only 25% get another strong bar next day.
   - TIGHT_CHANNEL: Small bars, little overlap → strong continuation. First breakout attempt usually fails.
   - BROAD_CHANNEL: Wider swings → tradeable pullbacks to EMA.
   - BREAKOUT: Strong bar breaking key level. Only 25% start new trend directly; 80% pull back to test.
   - TRADING_RANGE: No HH/HL, overlapping bars → high/low of range are key levels.
   - NONE: No clear pattern.

   IMPORTANT: For Category A patterns, direction MUST match the pattern's inherent signal
   (e.g., DOUBLE_BOTTOM → direction must be UP, HEAD_SHOULDERS_TOP → direction must be DOWN).
   For Category B patterns, direction is determined by your Always-In analysis.

4. SIGNAL QUALITY CHECK:
   - Is this a SECOND test/entry? (First signals often fail — wait for second confirmation)
   - Is price at a KEY level? (50% retracement, EMA, range boundary, neckline)
   - Does the signal bar have follow-through? (No follow-through = likely false breakout)
   - Is the risk:reward >= 1:1? (Ideally >= 2:1 for lower probability setups)
   - 99% of spike-and-channel days retrace to the moving average before close.

5. STOP LOSS:
   Set at signal bar extreme or pattern extreme (whichever gives tighter but valid stop).
   Stop should be >= 0.5x recent bar range to avoid noise stops.

CONFIDENCE SCORING (you MUST differentiate):
- 20-35: No clear pattern, choppy, environment unclear
- 40-55: Pattern visible but environment unfavorable or no second test
- 60-75: Clear pattern + favorable environment + key level + confirmation
- 80-95: Strong trend continuation OR reversal with 2+ bar follow-through at key level

6. BASELINE IDENTIFICATION:
   Find two reference bars from the last 30 bars:
   - baseline_buy: The most recent GREEN (bullish, close > open) bar at a relative LOW position. Does not need a strict V-bottom — any relatively low bullish bar qualifies.
   - baseline_sell: The most recent RED (bearish, close < open) bar at a relative HIGH position. Does not need a strict inverted-V top — any relatively high bearish bar qualifies.
   You MUST find at least one baseline. Return bars_ago only (count from rightmost bar=0), NOT the price.

Reply in JSON ONLY:
{"direction": "UP", "confidence": 72, "reason": "double bottom at 50% retracement of prior swing, second test with bull follow-through bar, EMA support", "stoploss": 228.50, "brooks_pattern": "DOUBLE_BOTTOM", "baseline_buy": {"found": true, "bars_ago": 5}, "baseline_sell": {"found": true, "bars_ago": 12}}

direction: "UP" for buy, "DOWN" for sell, "SIDE" for no opportunity.
confidence: integer 20-95 (MUST vary based on chart quality).
brooks_pattern: one of DOUBLE_BOTTOM, DOUBLE_TOP, HEAD_SHOULDERS_BOTTOM, HEAD_SHOULDERS_TOP, ASC_TRIANGLE, DESC_TRIANGLE, WEDGE_FALLING, WEDGE_RISING, CUP_AND_HANDLE, ROUNDING_BOTTOM, BULL_FLAG, BEAR_FLAG, MTR_BUY, MTR_SELL, CLIMAX, TIGHT_CHANNEL, BROAD_CHANNEL, BREAKOUT, TRADING_RANGE, NONE.
baseline_buy/baseline_sell: found=true with bars_ago, or found=false if not identifiable.
If no clear opportunity: {"direction": "SIDE", "confidence": 15, "reason": "choppy trading range, no second test", "stoploss": 0, "brooks_pattern": "TRADING_RANGE", "baseline_buy": {"found": true, "bars_ago": 8}, "baseline_sell": {"found": true, "bars_ago": 3}}
"""

SCAN_INTERVAL_SEC = 3600  # v2.2: 1小时(从30分钟降频,节省API成本)

# ---------------------------------------------------------------------------
# Email config (same as llm_server)
# ---------------------------------------------------------------------------
EMAIL_ENABLED = True
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
EMAIL_SMTP_TIMEOUT = 30
EMAIL_FROM = "aistockllmpro@gmail.com"
EMAIL_PASSWORD = "ficw ovws zvzb qmfs"
EMAIL_TO = ["baodexiang@hotmail.com"]

# Module-level state
_mods_cache: Optional[Dict] = None
_mods_ready = False
_last_scan_ts: float = 0.0
_last_scan_results: List[Dict] = []  # v2.2: 缓存上次结果,冷却期内复用


# ===================================================================
# Public API
# ===================================================================

def init_radar():
    global _mods_cache, _mods_ready
    if _mods_ready:
        return True
    try:
        _mods_cache = _lazy_imports()
        _mods_ready = True
        logger.info("模块加载完成")
        return True
    except Exception as e:
        logger.error(f"模块加载失败: {e}")
        _mods_ready = False
        return False


def radar_tick(symbols: List[str] = None):
    global _mods_cache, _mods_ready, _last_scan_ts, _last_scan_results

    now_ts = time.time()
    if now_ts - _last_scan_ts < SCAN_INTERVAL_SEC:
        return _last_scan_results  # v2.2: 返回缓存结果而非空列表

    if not _mods_ready:
        if not init_radar():
            return []

    _last_scan_ts = now_ts
    _last_scan_results = scan_all(_mods_cache, symbols)
    return _last_scan_results


# ===================================================================
# Lazy imports
# ===================================================================

def _lazy_imports():
    mods = {}
    from vision_analyzer import generate_pattern_chart, call_chatgpt_vision
    mods["generate_chart"] = generate_pattern_chart
    mods["call_vision"] = call_chatgpt_vision

    from price_scan_engine_v21 import YFinanceDataFetcher
    mods["fetcher"] = YFinanceDataFetcher

    from timeframe_params import is_crypto_symbol
    mods["is_crypto"] = is_crypto_symbol

    return mods


# ===================================================================
# Helpers
# ===================================================================

def get_ny_now() -> datetime:
    return datetime.now(NY_TZ)


def _get_today_key() -> str:
    """返回当天的日期key (8AM NY 为分界)"""
    now = get_ny_now()
    # 8AM前算前一天
    if now.hour < 8:
        from datetime import timedelta
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


# ===================================================================
# 每日限次管理 (每品种每天1买1卖，8AM NY重置)
# ===================================================================

def _load_daily_limit() -> Dict:
    """加载每日限次状态"""
    if DAILY_STATE_FILE.exists():
        try:
            data = json.loads(DAILY_STATE_FILE.read_text(encoding="utf-8"))
            if data.get("date_key") == _get_today_key():
                return data
        except Exception:
            pass
    return {"date_key": _get_today_key(), "executed": {}}


def _save_daily_limit(state: Dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                                encoding="utf-8")


def _can_execute(symbol: str, direction: str) -> bool:
    """检查今天这个品种这个方向是否还有名额"""
    state = _load_daily_limit()
    key = f"{symbol}_{direction}"
    return key not in state.get("executed", {})


def _mark_executed(symbol: str, direction: str):
    """标记今天已执行"""
    state = _load_daily_limit()
    state.setdefault("executed", {})[f"{symbol}_{direction}"] = get_ny_now().isoformat()
    _save_daily_limit(state)


# ===================================================================
# 读取 L2 上轮信号 (从 scan_signals.json)
# ===================================================================

def _get_l2_signal(symbol: str) -> str:
    """
    读取 scan_signals.json 获取上一轮 L2 扫描的信号。
    返回 "BUY" / "SELL" / "HOLD" / "NONE"
    """
    signal_file = Path("scan_signals.json")
    if not signal_file.exists():
        return "NONE"

    try:
        data = json.loads(signal_file.read_text(encoding="utf-8"))
        tracking = data.get("tracking_state", {})

        # 尝试直接匹配和内部名映射
        internal_name = YF_TO_INTERNAL.get(symbol, symbol)
        sym_state = tracking.get(symbol) or tracking.get(internal_name)

        if not sym_state:
            return "NONE"

        # 从 _last_final_decision.three_way_signals.v3300_five_module 读取
        final_decision = sym_state.get("_last_final_decision", {})
        three_way = final_decision.get("three_way_signals", {})
        five_module = three_way.get("v3300_five_module", {})

        if five_module:
            return five_module.get("signal", "HOLD")

        # fallback: 直接读顶层 signal
        return sym_state.get("signal", "NONE")

    except Exception as e:
        logger.warning(f"[{symbol}] 读取L2信号失败: {e}")
        return "NONE"


# ===================================================================
# 邮件通知 (EXECUTE 时发送)
# ===================================================================

def _send_radar_email(symbol: str, direction: str, radar: Dict,
                      filter_result: Dict, l2_signal: str):
    """Brooks Vision信号邮件通知"""
    if not EMAIL_ENABLED:
        return

    now = get_ny_now()
    emoji = "🟢" if direction == "BUY" else "🔴"
    price = filter_result.get("price", 0)
    conf = radar.get("confidence", 0)
    pattern = radar.get("pattern", "")
    stoploss = radar.get("stoploss", 0)
    ema10 = filter_result.get("ema10_value", 0)
    rsi = filter_result.get("rsi", 0)
    brooks = radar.get("brooks_pattern", "NONE")

    subject = f"[BROOKS] {emoji} {symbol} {direction} @ {price:.2f} | {brooks}"

    body = f"""Brooks Vision v2.6 信号通知
{'='*40}
时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (纽约)
品种: {symbol}
方向: {direction}
价格: {price:.4f}
置信度: {conf}%
Brooks形态: {brooks}
分析: {pattern}
止损位: {stoploss}

EMA10过滤: {filter_result.get('ema10_trend', 'N/A')} (EMA={ema10:.4f})
RSI(14): {rsi}
L2信号: {l2_signal}

判定: Brooks Vision + L2 → EXECUTE
{'='*40}
每日限次: 每品种每天1买1卖 (8AM NY重置)
"""

    html_body = f"""
<div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
  <div style="background: {'#28a745' if direction == 'BUY' else '#dc3545'};
              color: white; padding: 15px; text-align: center; border-radius: 8px 8px 0 0;">
    <h2 style="margin: 0;">{emoji} BROOKS {direction}</h2>
    <h3 style="margin: 5px 0 0;">{symbol} @ {price:.2f}</h3>
    <p style="margin: 5px 0 0; font-size: 14px; opacity: 0.9;">Pattern: {brooks}</p>
  </div>
  <div style="background: #f8f9fa; padding: 15px; border: 1px solid #dee2e6;">
    <table style="width: 100%; border-collapse: collapse;">
      <tr><td style="padding: 5px; font-weight: bold;">置信度</td><td style="padding: 5px;">{conf}%</td></tr>
      <tr><td style="padding: 5px; font-weight: bold;">Brooks形态</td><td style="padding: 5px; color: #0066cc; font-weight: bold;">{brooks}</td></tr>
      <tr><td style="padding: 5px; font-weight: bold;">分析</td><td style="padding: 5px;">{pattern}</td></tr>
      <tr><td style="padding: 5px; font-weight: bold;">止损位</td><td style="padding: 5px;">{stoploss}</td></tr>
      <tr><td style="padding: 5px; font-weight: bold;">EMA10</td><td style="padding: 5px;">{filter_result.get('ema10_trend', 'N/A')} ({ema10:.4f})</td></tr>
      <tr><td style="padding: 5px; font-weight: bold;">RSI(14)</td><td style="padding: 5px;">{rsi}</td></tr>
      <tr><td style="padding: 5px; font-weight: bold;">L2信号</td><td style="padding: 5px;">{l2_signal}</td></tr>
    </table>
  </div>
  <div style="background: {'#d4edda' if direction == 'BUY' else '#f8d7da'};
              padding: 10px; text-align: center; border-radius: 0 0 8px 8px;
              border: 1px solid #dee2e6; border-top: none;">
    <strong>Brooks Vision + L2 → EXECUTE</strong>
  </div>
  <p style="color: #6c757d; font-size: 12px; text-align: center; margin-top: 10px;">
    {now.strftime('%Y-%m-%d %H:%M:%S')} NY | 每品种每天限1买1卖
  </p>
</div>
"""

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(EMAIL_TO)
        msg.set_content(body)
        msg.add_alternative(html_body, subtype='html')

        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT,
                          timeout=EMAIL_SMTP_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        logger.info(f"[{symbol}] 邮件发送成功: {subject}")
    except TimeoutError:
        logger.warning(f"[{symbol}] 邮件发送超时")
    except Exception as e:
        logger.warning(f"[{symbol}] 邮件发送失败: {e}")


# ===================================================================
# EMA10 + RSI 简单过滤
# ===================================================================

def _simple_filter(bars: List[Dict], direction: str) -> Dict[str, Any]:
    """
    EMA10 趋势 + RSI(14) 超买超卖过滤。
    返回 {"pass": bool, "ema10_trend": str, "rsi": float, "reason": str}
    """
    if len(bars) < 15:
        return {"pass": False, "ema10_trend": "N/A", "rsi": 50.0,
                "reason": "K线不足"}

    closes = [b["close"] for b in bars]

    # --- EMA10 ---
    ema = closes[0]
    k = 2 / (10 + 1)
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    current_price = closes[-1]
    ema10_trend = "BULL" if current_price > ema else "BEAR"

    # --- RSI(14) ---
    period = 14
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0, c) for c in changes[-period:]]
    losses = [max(0, -c) for c in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - 100 / (1 + rs)
    rsi = round(rsi, 1)

    # --- 过滤逻辑 ---
    passed = True
    reason = ""

    if direction == "BUY":
        if ema10_trend == "BEAR":
            passed = False
            reason = "价格在EMA10下方，不适合买入"
        elif rsi > 80:
            passed = False
            reason = f"RSI={rsi}超买，不适合买入"
    elif direction == "SELL":
        if ema10_trend == "BULL":
            passed = False
            reason = "价格在EMA10上方，不适合卖出"
        elif rsi < 20:
            passed = False
            reason = f"RSI={rsi}超卖，不适合卖出"

    if passed:
        reason = f"EMA10={ema10_trend} RSI={rsi} 通过"

    return {
        "pass": passed,
        "ema10_trend": ema10_trend,
        "rsi": rsi,
        "ema10_value": round(ema, 4),
        "price": round(current_price, 4),
        "reason": reason,
    }


# ===================================================================
# Step 1: Radar Scan — Vision 看图 + Brooks 形态识别
# ===================================================================

def radar_scan(symbol: str, mods: dict) -> Optional[Dict[str, Any]]:
    """GCC-0194: 读取vision_analyzer缓存的分析结果（不再独立调GPT）
    vision_analyzer已使用RADAR_PROMPT统一调用, 结果写入pattern_latest.json
    """
    import json as _json
    pattern_file = os.path.join("state", "vision", "pattern_latest.json")
    if not os.path.exists(pattern_file):
        logger.warning(f"[{symbol}] pattern_latest.json不存在, 跳过")
        return None
    try:
        with open(pattern_file, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:
        logger.warning(f"[{symbol}] pattern_latest.json读取失败: {e}")
        return None

    entry = data.get(symbol)
    if not entry:
        logger.info(f"[{symbol}] pattern_latest.json无此品种数据")
        return None

    # 转换为radar_scan原有输出格式
    direction = str(entry.get("direction", "SIDE")).upper()
    signal = "BUY" if direction == "UP" else "SELL" if direction == "DOWN" else "NONE"
    conf = entry.get("confidence", 0.5)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.5
    # confidence在pattern_latest.json中是0-1, 转为0-100
    conf_pct = int(conf * 100) if conf <= 1.0 else int(conf)
    try:
        stoploss = float(entry.get("stoploss", 0))
    except (TypeError, ValueError):
        stoploss = 0.0
    brooks_pattern = str(entry.get("brooks_pattern", "NONE")).upper()

    result = {
        "bars": [],  # GCC-0194: 不再获取bars (缓存模式)
        "signal": signal,
        "pattern": str(entry.get("reason", ""))[:100],
        "confidence": max(0, min(100, conf_pct)),
        "stoploss": stoploss,
        "brooks_pattern": brooks_pattern,
    }
    logger.info(f"[{symbol}] Brooks(缓存): {signal} | "
                f"[{brooks_pattern}] {result['pattern'][:50]} | "
                f"conf={conf_pct} | SL={stoploss}")
    return result


def _parse_vision_dict(resp) -> Dict[str, Any]:
    default = {"signal": "NONE", "pattern": "unknown", "confidence": 0,
               "stoploss": 0.0, "brooks_pattern": "NONE"}
    if not resp or not isinstance(resp, dict):
        return default

    try:
        direction = str(resp.get("direction", "SIDE")).upper()
        confidence = resp.get("confidence", 0)
        reason = str(resp.get("reason", ""))[:100]
        try:
            stoploss = float(resp.get("stoploss", 0))
        except (ValueError, TypeError):
            stoploss = 0.0
        brooks_pattern = str(resp.get("brooks_pattern", "NONE")).upper()
    except Exception as e:
        logger.warning(f"[BrooksVision] _parse_vision_dict字段解析失败: {e}, resp={resp}")
        return default

    if direction == "UP":
        signal = "BUY"
    elif direction == "DOWN":
        signal = "SELL"
    else:
        signal = "NONE"

    # confidence: 支持 0-1 和 0-100 两种格式
    try:
        conf = float(confidence)
    except (ValueError, TypeError):
        conf = 0.0
    if conf <= 1.0:
        conf_pct = int(conf * 100)
    else:
        conf_pct = int(conf)

    # 兼容旧形态名 (WEDGE→方向性版本, MTR→方向性版本)
    # 只在GPT给了明确方向时才映射，SIDE/NONE时保留为NONE(无法判断方向)
    if brooks_pattern == "WEDGE" and signal in ("BUY", "SELL"):
        brooks_pattern = "WEDGE_FALLING" if signal == "BUY" else "WEDGE_RISING"
    elif brooks_pattern == "MTR" and signal in ("BUY", "SELL"):
        brooks_pattern = "MTR_BUY" if signal == "BUY" else "MTR_SELL"
    elif brooks_pattern in ("WEDGE", "MTR"):
        brooks_pattern = "NONE"  # 方向不明时不猜

    # 规范化 brooks_pattern (从 PATTERN_SIGNAL_MAP 取合法值)
    valid_patterns = set(PATTERN_SIGNAL_MAP.keys())
    if brooks_pattern not in valid_patterns:
        brooks_pattern = "NONE"

    return {
        "signal": signal,
        "pattern": reason if reason else "unknown",
        "confidence": max(0, min(100, conf_pct)),
        "stoploss": stoploss,
        "brooks_pattern": brooks_pattern,
    }


# ===================================================================
# Step 4: Record Observation (JSONL append)
# ===================================================================

def record_observation(symbol: str, radar: Dict, filter_result: Dict,
                       l2_signal: str, final: str):
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    bars = radar.get("bars", [])
    price_at_signal = bars[-1]["close"] if bars else 0

    record = {
        "ts": get_ny_now().isoformat(),
        "symbol": symbol,
        "radar": {
            "signal": radar["signal"],
            "pattern": radar["pattern"],
            "confidence": radar["confidence"],
            "stoploss": radar["stoploss"],
            "brooks_pattern": radar.get("brooks_pattern", "NONE"),
        },
        "filter": filter_result,
        "l2_signal": l2_signal,
        "final": final,
        "price_at_signal": round(price_at_signal, 6),
        "price_4h_later": None,
        "price_12h_later": None,
        "pnl_4h": None,
        "pnl_12h": None,
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    brooks = radar.get("brooks_pattern", "NONE")
    logger.info(f"[{symbol}] Final: {final} | Radar={radar['signal']} "
                f"[{brooks}] L2={l2_signal} | price={price_at_signal:.4f}")
    return record


# ===================================================================
# Step 5: Backfill Prices
# ===================================================================

def backfill_prices(mods: dict):
    if not LOG_FILE.exists():
        return 0

    now = get_ny_now()
    lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    updated = 0
    new_lines = []

    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        ts_str = rec.get("ts", "")
        try:
            rec_time = datetime.fromisoformat(ts_str)
            if rec_time.tzinfo is None:
                rec_time = rec_time.replace(tzinfo=NY_TZ)
        except (ValueError, TypeError):
            new_lines.append(line)
            continue

        symbol = rec.get("symbol", "")
        if not symbol:
            new_lines.append(line)
            continue

        changed = False

        if rec.get("price_4h_later") is None and (now - rec_time).total_seconds() >= 4 * 3600:
            price = _get_current_price(symbol, mods)
            if price and price > 0:
                rec["price_4h_later"] = round(price, 6)
                entry = rec.get("price_at_signal", 0)
                if entry and entry > 0:
                    direction = rec.get("radar", {}).get("signal", "NONE")
                    if direction == "BUY":
                        rec["pnl_4h"] = round((price - entry) / entry, 6)
                    elif direction == "SELL":
                        rec["pnl_4h"] = round((entry - price) / entry, 6)
                changed = True

        if rec.get("price_12h_later") is None and (now - rec_time).total_seconds() >= 12 * 3600:
            price = _get_current_price(symbol, mods)
            if price and price > 0:
                rec["price_12h_later"] = round(price, 6)
                entry = rec.get("price_at_signal", 0)
                if entry and entry > 0:
                    direction = rec.get("radar", {}).get("signal", "NONE")
                    if direction == "BUY":
                        rec["pnl_12h"] = round((price - entry) / entry, 6)
                    elif direction == "SELL":
                        rec["pnl_12h"] = round((entry - price) / entry, 6)
                changed = True

        if changed:
            updated += 1
        new_lines.append(json.dumps(rec, ensure_ascii=False))

    if updated > 0:
        LOG_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info(f"[BACKFILL] 回填 {updated} 条记录")

    return updated


def _get_current_price(symbol: str, mods: dict) -> Optional[float]:
    try:
        bars = mods["fetcher"].get_4h_ohlcv(symbol, lookback_bars=2)
        if bars and len(bars) > 0:
            return float(bars[-1]["close"])
    except Exception:
        pass
    return None


# ===================================================================
# Daily Report
# ===================================================================

def generate_daily_report(date_str: str = None) -> str:
    if not LOG_FILE.exists():
        return "No radar data found."

    now = get_ny_now()
    if date_str is None:
        date_str = now.strftime("%Y-%m-%d")

    lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            ts = rec.get("ts", "")
            if ts.startswith(date_str):
                records.append(rec)
        except json.JSONDecodeError:
            continue

    if not records:
        for line in lines:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    total = len(records)
    signals = [r for r in records if r.get("radar", {}).get("signal", "NONE") != "NONE"]
    executed = [r for r in records if r.get("final", "").endswith("_EXECUTE")]
    agree = [r for r in records if "AGREE" in r.get("final", "")]
    disagree = [r for r in records if "DISAGREE" in r.get("final", "")]

    def calc_wr(recs, key="pnl_4h"):
        filled = [r for r in recs if r.get(key) is not None]
        if not filled:
            return None, 0
        wins = sum(1 for r in filled if r[key] > 0)
        return round(wins / len(filled) * 100, 1), len(filled)

    exec_wr, exec_n = calc_wr(executed)
    all_wr, all_n = calc_wr(signals)
    agree_wr, agree_n = calc_wr(agree)

    symbol_stats = {}
    for r in signals:
        sym = r.get("symbol", "?")
        if sym not in symbol_stats:
            symbol_stats[sym] = {"signals": 0, "executed": 0, "agree": 0}
        symbol_stats[sym]["signals"] += 1
        if r.get("final", "").endswith("_EXECUTE"):
            symbol_stats[sym]["executed"] += 1
        if "AGREE" in r.get("final", ""):
            symbol_stats[sym]["agree"] += 1

    # Brooks 形态分布统计
    pattern_stats = {}
    for r in records:
        bp = r.get("radar", {}).get("brooks_pattern", "NONE")
        if bp and bp != "NONE":
            pattern_stats[bp] = pattern_stats.get(bp, 0) + 1

    lines_out = [
        f"{'=' * 50}",
        f" Brooks Vision v2.6 日报 {date_str}",
        f"{'=' * 50}",
        f"",
        f"扫描总数: {total}",
        f"Vision发现机会: {len(signals)}",
        f"  Brooks+L2一致(AGREE): {len(agree)}",
        f"  Brooks+L2不一致(DISAGREE): {len(disagree)}",
        f"  已执行(EXECUTE): {len(executed)}",
        f"",
        f"--- 胜率分析 (4h后) ---",
    ]
    if exec_wr is not None:
        lines_out.append(f"  执行信号: {exec_wr}% (n={exec_n})")
    else:
        lines_out.append("  执行信号: 待回填")
    if agree_wr is not None:
        lines_out.append(f"  一致信号: {agree_wr}% (n={agree_n})")
    else:
        lines_out.append("  一致信号: 待回填")
    if all_wr is not None:
        lines_out.append(f"  全部信号: {all_wr}% (n={all_n})")
    else:
        lines_out.append("  全部信号: 待回填")

    lines_out.append("")
    lines_out.append("--- 品种分布 ---")
    for sym, st in sorted(symbol_stats.items(), key=lambda x: -x[1]["signals"]):
        lines_out.append(f"  {sym}: {st['signals']}信号, {st['agree']}一致, {st['executed']}执行")

    lines_out.append("")
    lines_out.append("--- Brooks 形态分布 ---")
    if pattern_stats:
        for pat, cnt in sorted(pattern_stats.items(), key=lambda x: -x[1]):
            lines_out.append(f"  {pat}: {cnt}次")
    else:
        lines_out.append("  (无形态数据)")

    report_text = "\n".join(lines_out)

    report_file = STATE_DIR / f"vision_radar_daily_{date_str.replace('-', '')}.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    report_data = {
        "date": date_str,
        "generated_at": now.isoformat(),
        "total_scans": total,
        "signals": len(signals),
        "executed": len(executed),
        "agree": len(agree),
        "disagree": len(disagree),
        "winrate_executed_4h": exec_wr,
        "winrate_agree_4h": agree_wr,
        "winrate_all_4h": all_wr,
        "symbol_stats": symbol_stats,
        "brooks_pattern_stats": pattern_stats,
    }
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    logger.info(f"日报已保存: {report_file}")
    return report_text


# ===================================================================
# Main: Scan One Symbol (v2.6 形态驱动架构)
# ===================================================================

def scan_symbol(symbol: str, mods: dict) -> Optional[Dict]:
    """
    v2.6 Brooks Vision 流程:
    1. Vision 看图 + 形态识别 → 形态驱动BUY/SELL方向
    2. EMA10+RSI 过滤
    3. L2信号仅记录(不拦截)
    4. 今日有名额 → EXECUTE
    """
    logger.info(f"--- Scanning {symbol} ---")

    # Step 1: GCC-0194: 读取Vision缓存 (不再独立调GPT)
    radar = radar_scan(symbol, mods)
    if radar is None:
        return None

    direction = radar["signal"]

    # Vision 没看到机会
    if direction not in ("BUY", "SELL"):
        record = record_observation(symbol, radar, {}, "N/A", "NO_SIGNAL")
        return record

    # Step 2: EMA10 + RSI 过滤 (GCC-0194: radar_scan不再返回bars, 独立获取)
    bars = mods["fetcher"].get_4h_ohlcv(symbol, lookback_bars=30)
    if not bars or len(bars) < 15:
        logger.warning(f"[{symbol}] 过滤用K线不足, 跳过")
        return None
    radar["bars"] = bars  # 回填bars供后续record_observation使用
    filter_result = _simple_filter(bars, direction)
    if not filter_result["pass"]:
        logger.info(f"[{symbol}] 过滤未通过: {filter_result['reason']}")
        record = record_observation(symbol, radar, filter_result, "N/A",
                                    f"{direction}_FILTERED")
        return record

    logger.info(f"[{symbol}] 过滤通过: {filter_result['reason']}")

    # Step 3: 读 L2 上轮信号 (仅记录，不拦截)
    l2_signal = _get_l2_signal(symbol)
    logger.info(f"[{symbol}] L2上轮信号: {l2_signal}")
    agree_type = "AGREE" if l2_signal == direction else "L2_NEUTRAL"

    # Step 4: 每日限次检查
    if not _can_execute(symbol, direction):
        final = f"{direction}_{agree_type}_DAILY_LIMIT"
        logger.info(f"[{symbol}] 今日{direction}已执行过，跳过")
        record = record_observation(symbol, radar, filter_result, l2_signal, final)
        return record

    # Step 4b: GCC-0172 形态Phase门控 (Phase1仅记录,不EXECUTE)
    bp = radar.get("brooks_pattern", "NONE")
    bp_phase = bv_acc_get_pattern_phase(bp, symbol)
    if bp_phase == 1:
        final = f"{direction}_{agree_type}_BV_PHASE1"
        _gcc_log(f"[GCC-0172][BV_GATE] {symbol} [{bp}] Phase1观察 → 不执行 "
                 f"(形态准确率低)")
        record = record_observation(symbol, radar, filter_result, l2_signal, final)
        return record

    # Step 5: 放行 + 有名额 → EXECUTE
    # v2.4: _mark_executed() 移到 scan_engine, 只在主服务器实际成交后才消耗配额
    final = f"{direction}_{agree_type}_EXECUTE"
    logger.info(f"[{symbol}] ★ Brooks={direction} [{bp}] "
                f"L2={l2_signal} → EXECUTE (BV_Phase={bp_phase})")
    record = record_observation(symbol, radar, filter_result, l2_signal, final)

    # Step 6: 邮件通知移到scan_engine, 只在主服务器实际成交后才发 (v2.2)
    # _send_radar_email(symbol, direction, radar, filter_result, l2_signal)

    return record


# ===================================================================
# Main: Scan All
# ===================================================================

def _is_us_market_open() -> bool:
    now = get_ny_now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= t <= 16 * 60


def scan_all(mods: dict, symbols: List[str] = None):
    if symbols is None:
        if _is_us_market_open():
            symbols = ALL_SYMBOLS
        else:
            symbols = CRYPTO_SYMBOLS
            logger.info("美股闭市, 仅扫描加密货币")

    logger.info(f"=== Brooks Vision v2.6 Scan: {len(symbols)} symbols ===")
    start = time.time()

    results = []
    for sym in symbols:
        try:
            r = scan_symbol(sym, mods)
            if r:
                results.append(r)
        except Exception as e:
            logger.error(f"[{sym}] 扫描异常: {e}")
            traceback.print_exc()

    # Backfill old records
    try:
        backfill_prices(mods)
    except Exception as e:
        logger.error(f"[BACKFILL] 异常: {e}")

    # GCC-0172: 回测回填BV形态准确率
    try:
        bv_acc_backfill()
    except Exception as e:
        _gcc_log(f"[GCC-0172] bv_acc_backfill异常: {e}")

    elapsed = time.time() - start
    logger.info(f"=== Brooks Vision v2.6 Complete: {len(results)}/{len(symbols)} "
                f"in {elapsed:.1f}s ===")

    # Print summary
    for r in results:
        sym = r.get("symbol", "?")
        final = r.get("final", "?")
        radar_sig = r.get("radar", {}).get("signal", "?")
        l2 = r.get("l2_signal", "?")
        conf = r.get("radar", {}).get("confidence", 0)
        brooks = r.get("radar", {}).get("brooks_pattern", "?")
        logger.info(f"  {sym}: Brooks={radar_sig}[{brooks}](conf={conf}) L2={l2} → {final}")

    return results


# ===================================================================
# GCC-0172: BrooksVision 形态信号回测 + 准确率按形态×品种追踪
# ===================================================================

_BV_ACC_FILE = Path("state/bv_signal_accuracy.json")
_BV_ACC_LAST_RUN = 0.0  # 上次回填时间戳

def bv_acc_backfill():
    """
    解析 vision_radar_log.jsonl，用 4H 后实际价格回测每条 BUY/SELL 信号。
    按 brooks_pattern × symbol 统计准确率。
    结果写入 state/bv_signal_accuracy.json。
    设计: 5分钟最多跑一次(防频繁IO)。
    """
    global _BV_ACC_LAST_RUN
    now = time.time()
    if now - _BV_ACC_LAST_RUN < 300:
        return
    _BV_ACC_LAST_RUN = now

    radar_log = Path("state/vision_radar_log.jsonl")
    if not radar_log.exists():
        return

    # 读取所有记录 (per-line error handling — 一行坏不影响其余)
    records = []
    try:
        with open(radar_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return

    # 统计结构: {pattern: {symbol: {correct, incorrect, neutral, decisive}}}
    # 准确率分母=decisive(correct+incorrect), neutral不计入
    stats = {}
    overall = {"correct": 0, "incorrect": 0, "neutral": 0, "decisive": 0}
    threshold_pct = 0.5  # ±0.5% 为neutral

    for r in records:
        sig = r.get("radar", {}).get("signal", "NONE")
        if sig not in ("BUY", "SELL"):
            continue
        p4h = r.get("price_4h_later")
        p_at = r.get("price_at_signal")
        if p4h is None or p_at is None or p_at == 0:
            continue

        bp = r.get("radar", {}).get("brooks_pattern") or "NONE"
        sym = r.get("symbol", "UNKNOWN")

        pnl_pct = (p4h - p_at) / p_at * 100
        if sig == "SELL":
            pnl_pct = -pnl_pct

        # 归类
        if pnl_pct > threshold_pct:
            result = "correct"
        elif pnl_pct < -threshold_pct:
            result = "incorrect"
        else:
            result = "neutral"

        # 汇总
        if bp not in stats:
            stats[bp] = {}
        if sym not in stats[bp]:
            stats[bp][sym] = {"correct": 0, "incorrect": 0, "neutral": 0, "decisive": 0}

        stats[bp][sym][result] += 1
        if result != "neutral":
            stats[bp][sym]["decisive"] += 1
            overall["decisive"] += 1
        overall[result] += 1

        # 日志输出供log_analyzer检测
        bv_acc_log_eval(sym, bp, sig, p_at, p4h)

    # 计算准确率 + 建议Phase (分母=decisive, neutral不稀释)
    pattern_summary = {}
    for bp, syms in stats.items():
        bp_correct = sum(s["correct"] for s in syms.values())
        bp_decisive = sum(s["decisive"] for s in syms.values())
        bp_acc = bp_correct / bp_decisive if bp_decisive > 0 else 0

        sym_detail = {}
        for sym, s in syms.items():
            decisive = s["decisive"]
            acc = s["correct"] / decisive if decisive > 0 else 0
            # Phase建议: >60%且decisive样本>=8→Phase2, <35%→Phase1, 中间→维持
            if decisive >= 8 and acc >= 0.60:
                suggested_phase = 2
            elif decisive >= 5 and acc < 0.35:
                suggested_phase = 1
            else:
                suggested_phase = 0  # 0=样本不足,不建议
            sym_detail[sym] = {
                "correct": s["correct"], "incorrect": s["incorrect"],
                "neutral": s["neutral"], "decisive": decisive,
                "accuracy": round(acc, 4),
                "suggested_phase": suggested_phase,
            }

        pattern_summary[bp] = {
            "correct": bp_correct, "decisive": bp_decisive,
            "accuracy": round(bp_acc, 4),
            "symbols": sym_detail,
        }

    ov_decisive = overall["decisive"]

    # 展平entries: pattern_symbol → {symbol, pattern, accuracy, ...}
    flat_entries = {}
    for bp, syms in stats.items():
        for sym, s in syms.items():
            key = f"{bp}_{sym}"
            decisive = s["decisive"]
            acc = s["correct"] / decisive if decisive > 0 else 0
            flat_entries[key] = {
                "symbol": sym, "pattern": bp,
                "correct": s["correct"], "incorrect": s["incorrect"],
                "neutral": s["neutral"], "decisive": decisive,
                "accuracy": round(acc, 4),
            }

    result_data = {
        "updated_at": get_ny_now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall": {
            "correct": overall["correct"],
            "incorrect": overall["incorrect"],
            "neutral": overall["neutral"],
            "decisive": ov_decisive,
            "accuracy": round(overall["correct"] / ov_decisive, 4) if ov_decisive > 0 else 0,
        },
        "patterns": pattern_summary,
        "entries": flat_entries,
    }

    try:
        _BV_ACC_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BV_ACC_FILE.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _gcc_log(f"[GCC-0172][BV_ACC] 回测完成: {ov_decisive}decisive信号, "
                 f"准确率={result_data['overall']['accuracy']:.1%}, "
                 f"{len(pattern_summary)}种形态")
    except Exception as e:
        _gcc_log(f"[GCC-0172] bv_signal_accuracy.json写入失败: {e}")


_BV_ACC_CACHE: Optional[Dict] = None
_BV_ACC_CACHE_TS: float = 0.0


def bv_acc_get_pattern_phase(pattern: str, symbol: str) -> int:
    """
    获取指定形态×品种的建议Phase。
    返回: 0=样本不足, 1=低准确率(观察), 2=高准确率(信任)
    缓存5分钟(与backfill周期一致), 避免per-symbol重复读磁盘。
    """
    global _BV_ACC_CACHE, _BV_ACC_CACHE_TS
    now = time.time()
    if _BV_ACC_CACHE is None or now - _BV_ACC_CACHE_TS > 300:
        if not _BV_ACC_FILE.exists():
            _BV_ACC_CACHE = {}
            _BV_ACC_CACHE_TS = now
            return 0
        try:
            _BV_ACC_CACHE = json.loads(_BV_ACC_FILE.read_text(encoding="utf-8"))
            _BV_ACC_CACHE_TS = now
        except Exception as e:
            _gcc_log(f"[GCC-0172] bv_signal_accuracy.json读取失败: {e}")
            _BV_ACC_CACHE = {}
            _BV_ACC_CACHE_TS = now
            return 0

    pat_data = _BV_ACC_CACHE.get("patterns", {}).get(pattern, {})
    sym_data = pat_data.get("symbols", {}).get(symbol, {})
    phase = sym_data.get("suggested_phase", 0)

    # GCC-0198: 聚合兜底 — per-symbol decisive<5时用聚合准确率兜底
    # 避免新品种因样本少而绕过低准确率形态的门控
    if phase == 0 and sym_data.get("decisive", 0) < 5:
        agg_decisive = pat_data.get("decisive", 0)
        agg_acc = pat_data.get("accuracy", 0)
        if agg_decisive >= 8 and agg_acc < 0.35:
            _gcc_log(f"[GCC-0172][AGG-GATE] {symbol} [{pattern}] 聚合兜底Phase1 "
                     f"(sym_decisive={sym_data.get('decisive', 0)}, "
                     f"agg_decisive={agg_decisive}, agg_acc={agg_acc:.1%})")
            return 1

    return phase


def bv_acc_log_eval(symbol: str, pattern: str, signal: str,
                    price_at: float, price_4h: float):
    """
    日志输出单条评估结果，供log_analyzer检测。
    """
    if price_at == 0:
        return
    pnl = (price_4h - price_at) / price_at * 100
    if signal == "SELL":
        pnl = -pnl
    result = "CORRECT" if pnl > 0.5 else ("INCORRECT" if pnl < -0.5 else "NEUTRAL")
    _gcc_log(f"[GCC-0172][BV_EVAL] {symbol} {pattern} {signal} → {result} "
             f"(pnl={pnl:+.2f}%)")


# ===================================================================
# GCC-0172: 每2周自动准确率审查 + 降级/恢复 + 邮件通知
# ===================================================================

def bv_acc_biweekly_review() -> Optional[Dict]:
    """
    每2周审查一次准确率，自动降级并返回审查报告。
    降级规则: 形态×品种 decisive>=30 且 accuracy<0.50 → phase=1 (观察不执行)
    恢复规则: 上次phase=1, 本轮 decisive>=30 且 accuracy>=0.55 → phase=2
    用0.55恢复(高于0.50降级)，避免来回震荡。
    """
    if not _BV_ACC_FILE.exists():
        _gcc_log("[GCC-0172][REVIEW] bv_signal_accuracy.json不存在，跳过审查")
        return None

    try:
        data = json.loads(_BV_ACC_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _gcc_log(f"[GCC-0172][REVIEW] 读取失败: {e}")
        return None

    patterns = data.get("patterns", {})
    demoted = []   # 本轮降级
    promoted = []  # 本轮恢复
    maintained = []  # 维持

    for bp, bp_data in patterns.items():
        for sym, sd in bp_data.get("symbols", {}).items():
            decisive = sd.get("decisive", 0)
            acc = sd.get("accuracy", 0)
            old_phase = sd.get("suggested_phase", 0)

            if decisive < 30:
                maintained.append((bp, sym, acc, decisive, old_phase, "样本不足"))
                continue

            if acc < 0.50:
                sd["suggested_phase"] = 1
                if old_phase != 1:
                    demoted.append((bp, sym, acc, decisive))
                else:
                    maintained.append((bp, sym, acc, decisive, 1, "维持降级"))
            elif acc >= 0.55 and old_phase == 1:
                sd["suggested_phase"] = 2
                promoted.append((bp, sym, acc, decisive))
            else:
                maintained.append((bp, sym, acc, decisive, old_phase, "维持"))

    # 写回文件
    data["last_review"] = get_ny_now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _BV_ACC_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        _gcc_log(f"[GCC-0172][REVIEW] 写回失败: {e}")

    # 清缓存让下次读取生效
    global _BV_ACC_CACHE, _BV_ACC_CACHE_TS
    _BV_ACC_CACHE = None
    _BV_ACC_CACHE_TS = 0.0

    overall = data.get("overall", {})
    report = {
        "review_date": get_ny_now().strftime("%Y-%m-%d"),
        "overall_accuracy": overall.get("accuracy", 0),
        "overall_decisive": overall.get("decisive", 0),
        "demoted": demoted,
        "promoted": promoted,
        "maintained": maintained,
    }
    _gcc_log(f"[GCC-0172][REVIEW] 审查完成: 降级{len(demoted)}项, 恢复{len(promoted)}项")
    return report


def bv_acc_review_email(report: Dict):
    """格式化审查报告并发邮件通知。"""
    if not EMAIL_ENABLED or not report:
        return

    now = get_ny_now()
    subject = f"[BV审查] 2周准确率报告 {report['review_date']}"

    lines = [
        f"BrooksVision 2周准确率审查",
        f"{'='*45}",
        f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (纽约)",
        f"总体: {report['overall_accuracy']:.1%} ({report['overall_decisive']} decisive)",
        "",
    ]

    if report["demoted"]:
        lines.append("降级 (phase→1, 观察不执行):")
        for bp, sym, acc, n in report["demoted"]:
            lines.append(f"  {bp} x {sym}: {acc:.1%} ({n} decisive) → 降级")
        lines.append("")

    if report["promoted"]:
        lines.append("恢复 (phase→2, 恢复执行):")
        for bp, sym, acc, n in report["promoted"]:
            lines.append(f"  {bp} x {sym}: {acc:.1%} ({n} decisive) → 恢复")
        lines.append("")

    if not report["demoted"] and not report["promoted"]:
        lines.append("本轮无变更 (全部维持)")
        lines.append("")

    lines.append(f"维持: {len(report['maintained'])}项")
    lines.append(f"{'='*45}")
    body = "\n".join(lines)

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(EMAIL_TO)
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT,
                          timeout=EMAIL_SMTP_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        _gcc_log(f"[GCC-0172][REVIEW] 邮件发送成功: {subject}")
    except Exception as e:
        _gcc_log(f"[GCC-0172][REVIEW] 邮件发送失败: {e}")


# ===================================================================
# CLI entry (独立运行)
# ===================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Brooks Vision v2.6")
    parser.add_argument("--once", action="store_true", help="单次扫描")
    parser.add_argument("--symbol", type=str, help="指定品种 (如 BTC-USD)")
    parser.add_argument("--report", action="store_true", help="生成日报")
    parser.add_argument("--date", type=str, help="日报日期 (YYYY-MM-DD)")
    parser.add_argument("--backtest", action="store_true", help="GCC-0172: 回测BV信号准确率")
    args = parser.parse_args()

    if args.backtest:
        _BV_ACC_LAST_RUN = 0.0  # 强制立即运行
        bv_acc_backfill()
        if _BV_ACC_FILE.exists():
            data = json.loads(_BV_ACC_FILE.read_text(encoding="utf-8"))
            print(f"\n=== BV Signal Backtest (GCC-0172) ===")
            ov = data["overall"]
            print(f"Overall: {ov['decisive']} decisive signals, accuracy={ov['accuracy']:.1%} "
                  f"(+{ov.get('neutral',0)} neutral)")
            print(f"\nPer-Pattern:")
            for pat, pd in sorted(data["patterns"].items(), key=lambda x: -x[1].get("decisive", 0)):
                print(f"  {pat:20s}  n={pd.get('decisive',0):3d}  acc={pd['accuracy']:.1%}")
                for sym, sd in sorted(pd["symbols"].items(), key=lambda x: -x[1].get("decisive", 0)):
                    phase_label = {0: "样本不足", 1: "观察", 2: "信任"}
                    print(f"    {sym:15s}  n={sd.get('decisive',0):3d}  acc={sd['accuracy']:.1%}  "
                          f"→ Phase{sd['suggested_phase']}({phase_label[sd['suggested_phase']]})")
        else:
            print("无数据")
    elif args.report:
        print(generate_daily_report(args.date))
    elif args.once:
        if not init_radar():
            print("模块加载失败")
            exit(1)

        if args.symbol:
            r = scan_symbol(args.symbol, _mods_cache)
            if r:
                print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        else:
            results = scan_all(_mods_cache)
            print(f"\n扫描完成: {len(results)} 条结果")
            for r in results:
                sym = r.get("symbol", "?")
                final = r.get("final", "?")
                brooks = r.get("radar", {}).get("brooks_pattern", "?")
                print(f"  {sym}: [{brooks}] {final}")
    else:
        parser.print_help()
