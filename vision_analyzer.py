#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vision Analyzer - 独立AI视觉趋势分析程序
=========================================

功能:
- 用yfinance获取K线数据
- 生成K线图片让ChatGPT Vision读图分析
- 判断当前周期 + x4周期的趋势/震荡
- 与L1技术分析对比，积累数据验证准确率
- 观察模式：不覆盖L1决策

核心原理: 道氏理论(x4定方向) + N字结构(当前周期找入场)

v1.0 - 2026-01-29
v2.0 - 2026-01-31: 双模型对比模式(GPT-4o + Claude)
v2.1 - 2026-02-01: 增强趋势线 - 只连最近2-3个显著高低点 + 标注斜率方向
v2.2 - 2026-02-01: 两层比较系统 (Layer1同K线+Layer2跨K线)
v2.3 - 2026-02-01: 智能模型选择 + 分开提示词 + 共识度加权
v2.4 - 2026-02-02: 当前周期优化 - K线30根(原60) + 判断状态提示词(原预测方向)
v2.5 - 2026-02-02: 先行指标验证 - Vision比L1快2根K线 + L1确认率统计
v2.6 - 2026-02-02: L1确认率对比 - 2bar vs 3bar确认率比较 + 核心覆盖逻辑不变
v2.7 - 2026-02-02: 人类视觉提示词 - 用手指划过K线判断趋势 + SIDE是常态 + 10根K线经验法则
v2.8 - 2026-02-03: 动态周期适配 - 提示词/图表/冷却均从timeframe_params动态计算
v3.0 - 2026-02-06: 极简趋势图 - 实体顶底两条线(不含影线/K线/EMA) + 左右比较提示词
v3.1 - 2026-02-07: GPT-4o形态识别 - K线实体矩形+EMA20+量能图 + 8种形态(W/M/H&S/123/2B)
"""

import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import subprocess

# ============================================================================
# 依赖检查与自动安装
# ============================================================================
REQUIRED_PACKAGES = {
    "pandas": "pandas",
    "pytz": "pytz",
    "matplotlib": "matplotlib",
    "mplfinance": "mplfinance",
    "yfinance": "yfinance",
    "openai": "openai",
    "requests": "requests",
}

def check_and_install_dependencies():
    """检查并自动安装缺失的依赖"""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"[Vision] 安装缺失依赖: {', '.join(missing)}")
        for pkg in missing:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])
                print(f"[Vision] 已安装: {pkg}")
            except subprocess.CalledProcessError as e:
                print(f"[Vision] 安装失败: {pkg} - {e}")
                sys.exit(1)
        print("[Vision] 依赖安装完成")

# 程序启动时检查依赖
check_and_install_dependencies()

# vPortability: Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[Vision] .env file loaded successfully")
except ImportError:
    print("[Vision] python-dotenv not installed, skipping .env load")

import json
import time
import base64
import io
import uuid
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional, Dict, List, Any

import pandas as pd
import pytz
from timeframe_params import get_timeframe_params, read_symbol_timeframe, is_crypto_symbol  # v2.8

# 设置非交互式后端 (必须在导入mplfinance之前)
import matplotlib
matplotlib.use('Agg')

# ============================================================================
# 配置
# ============================================================================

# ============================================================================
# Vision模型配置 - GPT-5.2 (v2.9: Claude API已移除)
# ============================================================================
VISION_MODEL = "gpt-5.2"

# OpenAI API配置 (GPT-5.2)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

# v3.3: Claude API fallback (GPT失败时自动切换)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# 品种基础配置: symbol → {yf_symbol, type}
# l1_timeframe 从主程序的 state/symbol_config.json 自动读取
SYMBOLS_BASE_CONFIG = {
    # 加密货币
    "BTCUSDC": {"yf_symbol": "BTC-USD", "type": "crypto"},
    "ETHUSDC": {"yf_symbol": "ETH-USD", "type": "crypto"},
    "SOLUSDC": {"yf_symbol": "SOL-USD", "type": "crypto"},
    "ZECUSDC": {"yf_symbol": "ZEC-USD", "type": "crypto"},
    # 美股
    "TSLA": {"yf_symbol": "TSLA", "type": "stock"},
    "COIN": {"yf_symbol": "COIN", "type": "stock"},
    "AMD": {"yf_symbol": "AMD", "type": "stock"},
    "RDDT": {"yf_symbol": "RDDT", "type": "stock"},
    "RKLB": {"yf_symbol": "RKLB", "type": "stock"},
    "NBIS": {"yf_symbol": "NBIS", "type": "stock"},
    "CRWV": {"yf_symbol": "CRWV", "type": "stock"},
    "HIMS": {"yf_symbol": "HIMS", "type": "stock"},
    "OPEN": {"yf_symbol": "OPEN", "type": "stock"},
    "ONDS": {"yf_symbol": "ONDS", "type": "stock"},
    "PLTR": {"yf_symbol": "PLTR", "type": "stock"},
    # ETF (QQQ期权用)
    "QQQ": {"yf_symbol": "QQQ", "type": "stock"},
}

# 默认L1周期 (当主程序配置不可用时)
DEFAULT_L1_TIMEFRAME = 240  # 4小时

# 主程序周期配置文件
SYMBOL_CONFIG_FILE = "state/symbol_config.json"

# 图表配置
CHART_CONFIG = {
    "width": 12,
    "height": 6,
    "dpi": 100,
    "style": "charles",
    "current_bars": 30,   # v2.4: 当前周期显示30根K线 (4H×30=5天) - 聚焦近期动量
    "x4_bars": 30,        # X4周期聚合后显示30根K线 (16H×30=20天)
    "x4_aggregate": 4,    # X4聚合因子: 4根当前周期K线 → 1根X4 K线 (与L1主程序一致)
}

# ChatGPT配置
CHATGPT_CONFIG = {
    "model": "gpt-5.2",
    "timeout": 30,
    "max_completion_tokens": 200,
}

# v3.3: 形态识别严格JSON输出约束
PATTERN_ALLOWED_TYPES = {
    "DOUBLE_BOTTOM", "DOUBLE_TOP",
    "HEAD_SHOULDERS_BOTTOM", "HEAD_SHOULDERS_TOP",
    "REVERSAL_123_BUY", "REVERSAL_123_SELL",
    "FALSE_BREAK_BUY", "FALSE_BREAK_SELL",
    # v3.5 Phase I: 固定方向形态
    "ASC_TRIANGLE", "DESC_TRIANGLE",
    "WEDGE_RISING", "WEDGE_FALLING",
    # GCC-0194: Brooks 21种形态支持
    "CUP_AND_HANDLE", "ROUNDING_BOTTOM",
    "BULL_FLAG", "BEAR_FLAG",
    "MTR_BUY", "MTR_SELL",
    "HEAD_SHOULDERS",  # Brooks通用头肩
    # 环境型形态 (方向由direction决定)
    "CLIMAX", "TIGHT_CHANNEL", "BROAD_CHANNEL",
    "BREAKOUT", "TRADING_RANGE",
    "NONE",
}
PATTERN_ALLOWED_STAGES = {"FORMING", "BREAKOUT", "NONE"}

# v3.1: 形态图表配置
PATTERN_CHART_CONFIG = {
    "bars": 50,           # 形态图需要更多历史 (比趋势的30根多)
    "width": 12,
    "height": 6,
    "dpi": 100,
    "ema_period": 20,     # EMA20参考线
}

# v3.1: 形态检测冷却 (独立于趋势冷却)
PATTERN_COOLDOWN_MINUTES = 60  # GCC-0194: 1小时冷却 (从4H降频, 对齐BrooksVision)

# v3.4: 形态识别熔断保护（连续失败）
PATTERN_CIRCUIT_FAIL_THRESHOLD = 3
PATTERN_CIRCUIT_BREAK_MINUTES = 60

# 运行配置
RUN_CONFIG = {
    "analysis_interval_minutes": 30,  # 主循环间隔
    "per_symbol_cooldown_minutes": 240,  # 默认值(v2.8: 运行时按品种周期动态调整)
    "stock_only_market_hours": True,  # 美股仅在开盘时分析
    "data_retention_days": 30,  # 数据保留天数
    "yfinance_timeout": 30,  # yfinance超时
}

# 文件路径
STATE_DIR = "state/vision"
HISTORY_FILE = os.path.join(STATE_DIR, "vision_history.json")
COMPARISON_FILE = os.path.join(STATE_DIR, "vision_vs_l1.json")
LAST_ANALYSIS_FILE = os.path.join(STATE_DIR, "last_analysis.json")
VERIFICATION_LOG = os.path.join(STATE_DIR, "verification_log.txt")
LATEST_FILE = os.path.join(STATE_DIR, "latest.json")  # v2.0: 供主程序读取的最新结果
DUAL_MODEL_LOG = os.path.join(STATE_DIR, "dual_model_comparison.log")  # v2.0: 双模型对比日志 (废弃，合并到UNIFIED_LOG)
UNIFIED_LOG = os.path.join(STATE_DIR, "vision_analysis.log")  # v2.0: 统一日志文件
PATTERN_LATEST_FILE = os.path.join(STATE_DIR, "pattern_latest.json")  # v3.1: 形态检测结果
L1_STATE_FILE = "global_trend_state.json"

# 纽约时区
NY_TZ = pytz.timezone("America/New_York")

# ============================================================================
# Vision Prompts - v2.3: 分开提示词 (当前周期 vs X4周期)
# ============================================================================

# ============================================================================
# v2.7 提示词 - GPT英文 / Claude中文
# ============================================================================

# v2.8: 动态提示词生成函数 — label由timeframe_params计算
def build_prompt_current_gpt(label: str = "4-hour") -> str:
    return f"""This {label} chart has two lines: RED = body top, BLUE = body bottom of each bar.

Focus on the MOST RECENT 15-20 bars. Identify the peaks and valleys of both lines:

UP: RED and BLUE lines form higher highs (HH) and higher lows (HL). Valleys do not drop below previous valleys. Overall slope tilts upward.
DOWN: RED and BLUE lines form lower highs (LH) and lower lows (LL). Peaks do not rise above previous peaks. Overall slope tilts downward.
SIDE: Peaks and valleys stay within a flat band. No consistent HH/HL or LH/LL sequence. Lines move sideways without clear direction.

N-pattern check (last 10-15 bars):
- UP_N: After a decline, price forms a valley (A), bounces to a peak (B), pulls back to a HIGHER valley (C > A), then rises past B. This is a bullish N-shape.
- DOWN_N: After a rally, price forms a peak (A), drops to a valley (B), bounces to a LOWER peak (C < A), then falls past B. This is a bearish N-shape.
- NONE: No clear N-pattern in recent bars.

If the trend reversed recently, report the LATEST direction based on the last 5-10 bars.

Respond ONLY JSON:
{{"direction": "UP", "confidence": 0.8, "n_pattern": "UP_N", "red_line": "up", "blue_line": "up", "reason": "higher highs and higher lows in recent bars, bullish N-shape confirmed"}}
"""

# v2.9: Claude提示词已停用 (GPT-4o only)
# def build_prompt_current_claude(label: str = "4-hour") -> str:
#     label_cn = label.replace("-hour", "小时").replace("-minute", "分钟").replace("-day", "天").replace("daily", "日线")
#     return f"""分析这张{label_cn}K线图。 ..."""

def build_prompt_x4_gpt(label: str = "16-hour") -> str:
    return f"""This {label} chart has two lines: RED = body top, BLUE = body bottom of each bar.

Compare the LEFT side (bars 1-5) with the RIGHT side (last 5 bars). Ignore small bounces.

- Right side HIGHER than left = "UP"
- Right side LOWER than left = "DOWN"
- About the same level = "SIDE"

Respond ONLY JSON:
{{"direction": "UP", "confidence": 0.8, "red_line": "up", "blue_line": "up", "reason": "right side higher"}}
"""

# v2.9: Claude X4提示词已停用 (GPT-4o only)
# def build_prompt_x4_claude(label: str = "16-hour") -> str:
#     label_cn = label.replace("-hour", "小时").replace("-minute", "分钟").replace("-day", "天").replace("daily", "日线")
#     return f"""分析这张{label_cn}K线图的大趋势。 ..."""

# 向后兼容: 默认4H提示词 (静态变量)
PROMPT_CURRENT_GPT = build_prompt_current_gpt("4-hour")
# PROMPT_CURRENT_CLAUDE = build_prompt_current_claude("4-hour")  # v2.9: 已停用
PROMPT_X4_GPT = build_prompt_x4_gpt("16-hour")
# PROMPT_X4_CLAUDE = build_prompt_x4_claude("16-hour")  # v2.9: 已停用
PROMPT_CURRENT = PROMPT_CURRENT_GPT
PROMPT_X4 = PROMPT_X4_GPT
VISION_PROMPT = PROMPT_CURRENT

# ============================================================================
# v3.1: 形态识别提示词
# ============================================================================

def build_prompt_pattern_gpt(label: str = "4-hour") -> str:
    """v3.3: GPT-5.2形态识别提示词 — 新增L1整体结构分析"""
    return f"""This {label} chart shows candle bodies with 50 bars:
- GREEN rectangles = bullish candle bodies (close > open)
- RED rectangles = bearish candle bodies (close < open)
- YELLOW dashed line = EMA20 (20-period moving average)
- GRAY bars at bottom = volume

FIRST, assess the overall market structure based on ALL 50 bars:
- "ACCUMULATION": Low volatility base building (sideways, no clear trend, price coiling)
- "MARKUP": Clear uptrend (HH/HL pattern dominant, price above EMA20)
- "DISTRIBUTION": High in range, volatility increasing, potential reversal (price near top, divergence)
- "MARKDOWN": Clear downtrend (LH/LL pattern dominant, price below EMA20)
- "UNKNOWN": Cannot clearly identify structure

THEN, assess current price POSITION within the full 50-bar range:
- "HIGH": Price is in upper 30% of the bar range
- "MID": Price is in middle 40% of the bar range
- "LOW": Price is in lower 30% of the bar range

Look for these chart patterns in the MOST RECENT bars:

1. DOUBLE_BOTTOM (W-shape): Price forms W with two similar lows, now rising above the middle peak (neckline). Green candles on right side.
2. DOUBLE_TOP (M-shape): Price forms M with two similar highs, now falling below the middle trough (neckline). Red candles on right side.
3. HEAD_SHOULDERS_BOTTOM: Three lows where middle (head) is lowest, shoulders higher and similar. Price rising above neckline.
4. HEAD_SHOULDERS_TOP: Three highs where middle (head) is highest, shoulders lower and similar. Price falling below neckline.
5. REVERSAL_123_BUY: In downtrend: point 1 (low) → point 2 (bounce high) → point 3 (higher low than 1) → price breaks above point 2.
6. REVERSAL_123_SELL: In uptrend: point 1 (high) → point 2 (drop low) → point 3 (lower high than 1) → price breaks below point 2.
7. FALSE_BREAK_BUY (2B): New low breaks previous low but immediately reverses up (false breakdown, trap sellers).
8. FALSE_BREAK_SELL (2B): New high breaks previous high but immediately reverses down (false breakout, trap buyers).
9. ASC_TRIANGLE: Flat horizontal resistance on top + rising support on bottom (higher lows). Price converging toward apex, then breaks ABOVE flat top. Bullish.
10. DESC_TRIANGLE: Falling resistance on top (lower highs) + flat horizontal support on bottom. Price converging toward apex, then breaks BELOW flat bottom. Bearish.
11. WEDGE_RISING: Both upper and lower trendlines slope UPWARD and converge. Price making higher highs and higher lows but range narrowing. Bearish reversal — breaks DOWN through lower trendline.
12. WEDGE_FALLING: Both upper and lower trendlines slope DOWNWARD and converge. Price making lower highs and lower lows but range narrowing. Bullish reversal — breaks UP through upper trendline.

NOTE: Triangle vs Wedge distinction: Triangle has ONE flat edge; Wedge has BOTH edges sloping in the SAME direction.

Volume confirmation:
- Right side volume should be LOWER than left side (weakening pressure)
- Breakout bar should have HIGHER volume (confirmation)

EMA20 reference:
- Price breaks above EMA20 with pattern = stronger BUY signal
- Price breaks below EMA20 with pattern = stronger SELL signal

Respond ONLY JSON:
{{"overall_structure": "ACCUMULATION|MARKUP|DISTRIBUTION|MARKDOWN|UNKNOWN", "position": "HIGH|MID|LOW", "pattern": "DOUBLE_BOTTOM|DOUBLE_TOP|HEAD_SHOULDERS_BOTTOM|HEAD_SHOULDERS_TOP|REVERSAL_123_BUY|REVERSAL_123_SELL|FALSE_BREAK_BUY|FALSE_BREAK_SELL|ASC_TRIANGLE|DESC_TRIANGLE|WEDGE_RISING|WEDGE_FALLING|NONE", "confidence": 0.8, "stage": "FORMING|BREAKOUT|NONE", "volume_confirmed": true, "reason": "brief explanation"}}

If no clear pattern, return pattern=NONE. Only report patterns with confidence >= 0.7.
"""


def get_chart_config(tf_minutes: int, is_crypto: bool = True) -> dict:
    """v2.8: 动态图表配置 — bars数根据周期计算"""
    params = get_timeframe_params(tf_minutes, is_crypto)
    return {
        "width": CHART_CONFIG["width"],
        "height": CHART_CONFIG["height"],
        "dpi": CHART_CONFIG["dpi"],
        "style": CHART_CONFIG["style"],
        "current_bars": min(30, max(15, int(params["bars_per_day"] * 5))),
        "x4_bars": min(30, max(15, int(params["bars_per_day"] * 5))),
        "x4_aggregate": params["x4_factor"],
    }


# ============================================================================
# v2.3 智能模型选择
# ============================================================================

def get_model_accuracy_stats() -> Dict:
    """
    获取模型历史准确率统计
    从 vision_vs_l1.json 读取
    """
    data = load_json_file(COMPARISON_FILE)
    return data.get("stats", {})


# v2.9: smart_model_select 已停用 (双模型对比已移除，仅GPT-4o)
# def smart_model_select(gpt_result, claude_result, l1_direction, period, stats=None) -> Dict:
#     """v2.3: 智能模型选择 — GPT+Claude+L1三方对比"""
#     ... (132行，已停用)

# ============================================================================
# 工具函数
# ============================================================================

def ensure_state_dir():
    """确保状态目录存在"""
    os.makedirs(STATE_DIR, exist_ok=True)


def log_verification(message: str):
    """写入验证日志文件"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(VERIFICATION_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"[Vision] 写日志失败: {e}")


def get_symbol_timeframe(symbol: str) -> int:
    """
    从主程序配置文件读取品种的L1周期
    配置文件由主程序 llm_server 在TV推送时更新
    """
    try:
        if os.path.exists(SYMBOL_CONFIG_FILE):
            with open(SYMBOL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            symbols = config.get("symbols", {})
            if symbol in symbols:
                tf = int(symbols[symbol])
                return tf
    except Exception as e:
        print(f"[Vision] 读取周期配置失败: {e}")

    # 返回默认值
    return DEFAULT_L1_TIMEFRAME


def get_symbols_config() -> Dict[str, Dict]:
    """
    获取完整的品种配置 (合并基础配置 + 动态周期)
    """
    result = {}
    for symbol, base_cfg in SYMBOLS_BASE_CONFIG.items():
        result[symbol] = {
            "yf_symbol": base_cfg["yf_symbol"],
            "type": base_cfg["type"],
            "l1_timeframe": get_symbol_timeframe(symbol),
        }
    return result


def load_json_file(filepath: str) -> dict:
    """加载JSON文件"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Vision] 加载{filepath}失败: {e}")
    return {}


def save_json_file(filepath: str, data: dict):
    """原子写JSON文件"""
    try:
        tmp_path = filepath + f".{os.getpid()}.tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, filepath)
    except Exception as e:
        print(f"[Vision] 保存{filepath}失败: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except:
            pass


def get_ny_time() -> datetime:
    """获取纽约时间"""
    return datetime.now(NY_TZ)


def is_us_market_open() -> bool:
    """判断美股是否开盘 (9:30 AM - 4:00 PM ET, 周一到周五)"""
    ny_now = get_ny_time()
    if ny_now.weekday() >= 5:  # 周六日
        return False
    market_open = ny_now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = ny_now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= ny_now <= market_close


# ============================================================================
# yfinance数据获取
# ============================================================================

def fetch_yfinance_history(yf_symbol: str, period: str, interval: str,
                           timeout: int = None) -> Optional[pd.DataFrame]:
    """
    从yfinance获取历史K线数据 (带超时保护)
    """
    import yfinance as yf

    if timeout is None:
        timeout = RUN_CONFIG["yfinance_timeout"]

    def _do_fetch():
        ticker = yf.Ticker(yf_symbol)
        return ticker.history(period=period, interval=interval)

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_fetch)
    try:
        result = future.result(timeout=timeout)
        executor.shutdown(wait=False)
        return result
    except FuturesTimeoutError:
        print(f"[Vision] yfinance超时({timeout}秒): {yf_symbol}")
        executor.shutdown(wait=False)
        return None
    except Exception as e:
        print(f"[Vision] yfinance异常: {yf_symbol} - {e}")
        executor.shutdown(wait=False)
        return None


def get_yfinance_params(timeframe_minutes: int, is_x4: bool = False) -> tuple:
    """
    将周期(分钟)转换为yfinance参数
    Returns: (interval, period, needs_resample, resample_factor)

    yfinance支持: 1m, 5m, 15m, 30m, 60m, 1h, 1d, 1wk
    不支持: 2h, 4h (需要从1h重采样)

    X4策略 (v2.1): 与L1主程序一致，4根当前周期K线聚合成1根X4 K线
    例如: 当前=4H, X4=16H (4根4H聚合)
    需要获取足够数据用于聚合: 30根X4 = 120根当前周期
    """
    tf = timeframe_minutes

    if tf <= 60:
        # 1H周期
        period = "3mo" if is_x4 else "1mo"
        return ("1h", period, False, None)
    elif tf <= 120:
        # 2H周期: 从1h重采样
        period = "3mo" if is_x4 else "1mo"
        return ("1h", period, True, 2)
    elif tf <= 240:
        # 4H周期: 从1h重采样
        # X4用更长历史(3个月)以获得更多4H K线
        period = "3mo" if is_x4 else "1mo"
        return ("1h", period, True, 4)
    elif tf <= 1440:
        # 日线周期
        period = "1y" if is_x4 else "6mo"
        return ("1d", period, False, None)
    else:
        # 周线周期
        return ("1wk", "2y", False, None)


def resample_bars(df: pd.DataFrame, factor: int) -> pd.DataFrame:
    """
    将K线重采样 (如1h→4h)
    factor: 重采样因子 (4表示4根合1根)
    """
    if df is None or df.empty:
        return df

    # 按factor根一组进行聚合
    resampled = []
    for i in range(0, len(df) - factor + 1, factor):
        group = df.iloc[i:i+factor]
        resampled.append({
            "Open": group["Open"].iloc[0],
            "High": group["High"].max(),
            "Low": group["Low"].min(),
            "Close": group["Close"].iloc[-1],
            "Volume": group["Volume"].sum() if "Volume" in group.columns else 0,
        })

    result = pd.DataFrame(resampled)
    result.index = pd.date_range(start="2025-01-01", periods=len(result), freq="h")
    result.index.name = "Date"
    return result


def fetch_bars(symbol: str, cfg: dict, is_x4: bool = False) -> Optional[List[Dict]]:
    """
    获取K线数据
    Returns: [{open, high, low, close, volume}, ...]

    v2.1: X4周期使用与L1主程序一致的聚合逻辑
    - 4根当前周期K线聚合成1根X4 K线
    - 例如: 4H × 4 = 16H K线
    """
    yf_symbol = cfg["yf_symbol"]
    l1_timeframe = cfg["l1_timeframe"]

    interval, period, needs_resample, resample_factor = get_yfinance_params(l1_timeframe, is_x4)

    hist = fetch_yfinance_history(yf_symbol, period=period, interval=interval)
    if hist is None or hist.empty:
        print(f"[Vision] {symbol} {'x4' if is_x4 else '当前'}周期数据为空")
        return None

    # 重采样到当前周期(如需要，如1h→4h)
    if needs_resample and resample_factor:
        hist = resample_bars(hist, resample_factor)

    # X4额外聚合: 4根当前周期 → 1根X4 (与L1主程序一致)
    x4_aggregate = CHART_CONFIG.get("x4_aggregate", 4)
    if is_x4 and x4_aggregate > 1:
        hist = resample_bars(hist, x4_aggregate)
        effective_multiplier = x4_aggregate
    else:
        effective_multiplier = 1

    # v2.8: 动态bars数量 — 根据品种周期计算
    _dyn_chart = get_chart_config(l1_timeframe, is_crypto=(cfg.get("type") == "crypto"))
    bars_count = _dyn_chart["x4_bars"] if is_x4 else _dyn_chart["current_bars"]

    # 转为bars列表
    bars = []
    for idx, row in hist.tail(bars_count).iterrows():
        close_val = float(row["Close"]) if not pd.isna(row["Close"]) else 0
        if close_val <= 0:
            continue
        bars.append({
            "open": float(row["Open"]) if not pd.isna(row["Open"]) else close_val,
            "high": float(row["High"]) if not pd.isna(row["High"]) else close_val,
            "low": float(row["Low"]) if not pd.isna(row["Low"]) else close_val,
            "close": close_val,
            "volume": float(row["Volume"]) if not pd.isna(row.get("Volume", 0)) else 0,
        })

    if len(bars) < 10:
        print(f"[Vision] {symbol} {'x4' if is_x4 else '当前'}周期K线不足: {len(bars)}根")
        return None

    # 计算实际周期
    if needs_resample and resample_factor:
        base_hours = resample_factor  # 如 1h×4 = 4h
    else:
        base_hours = l1_timeframe // 60 if l1_timeframe >= 60 else 1

    if is_x4:
        effective_interval = f"{base_hours * effective_multiplier}h"  # 如 4h×4 = 16h
    else:
        effective_interval = f"{base_hours}h"

    period_name = "x4" if is_x4 else "当前"
    print(f"[Vision] {symbol} {period_name}周期: {len(bars)}根K线 (实际={effective_interval})")
    return bars


# ============================================================================
# 图表生成
# ============================================================================

def bars_to_dataframe(bars: List[Dict]) -> Optional[pd.DataFrame]:
    """ohlcv bars列表 → pandas DataFrame (mplfinance格式)"""
    if not bars:
        return None

    df = pd.DataFrame(bars)
    rename_map = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    df = df.rename(columns=rename_map)

    for col in ["Open", "High", "Low", "Close"]:
        if col not in df.columns:
            return None

    if "Volume" not in df.columns:
        df["Volume"] = 0

    df.index = pd.date_range(start="2025-01-01", periods=len(df), freq="h")
    df.index.name = "Date"
    return df


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """计算EMA"""
    return series.ewm(span=period, adjust=False).mean()


def find_swing_points(df: pd.DataFrame, window: int = 8) -> tuple:
    """
    v2.1: 找出显著的波段高点和低点 (用于画趋势线)
    window=8 减少噪点，只保留显著转折点
    """
    highs_idx, highs_val = [], []
    lows_idx, lows_val = [], []
    high_col = df['High'].values
    low_col = df['Low'].values

    for i in range(window, len(df) - window):
        if high_col[i] == max(high_col[i-window:i+window+1]):
            highs_idx.append(i)
            highs_val.append(high_col[i])
        if low_col[i] == min(low_col[i-window:i+window+1]):
            lows_idx.append(i)
            lows_val.append(low_col[i])

    return highs_idx, highs_val, lows_idx, lows_val


def calculate_trend_direction(idx_list: list, val_list: list, n_points: int = 3) -> tuple:
    """
    v2.1: 计算最近n个点的趋势方向和斜率
    Returns: (direction: "UP"/"DOWN"/"SIDE", slope_pct: float, last_n_idx, last_n_val)
    """
    if len(idx_list) < 2:
        return "SIDE", 0.0, idx_list, val_list

    # 取最近n个点
    last_n_idx = idx_list[-n_points:] if len(idx_list) >= n_points else idx_list
    last_n_val = val_list[-n_points:] if len(val_list) >= n_points else val_list

    if len(last_n_val) < 2:
        return "SIDE", 0.0, last_n_idx, last_n_val

    # 计算斜率 (最后一个点 vs 第一个点)
    first_val = last_n_val[0]
    last_val = last_n_val[-1]

    if first_val == 0:
        return "SIDE", 0.0, last_n_idx, last_n_val

    slope_pct = (last_val - first_val) / first_val * 100

    # 判断方向 (阈值1%避免噪声)
    if slope_pct > 1.0:
        direction = "UP"
    elif slope_pct < -1.0:
        direction = "DOWN"
    else:
        direction = "SIDE"

    return direction, slope_pct, last_n_idx, last_n_val


def generate_simple_trend_chart(bars: List[Dict], title: str = "") -> Optional[str]:
    """
    v3.0: 极简趋势图 — 只画两条线 (实体部分，不含影线)
    - 红线: 连接每根K线的 max(Open, Close) — 实体顶部
    - 蓝线: 连接每根K线的 min(Open, Close) — 实体底部
    - 无K线/EMA/成交量/影线，GPT一眼判断方向
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("[Vision] matplotlib未安装")
        return None

    df = bars_to_dataframe(bars)
    if df is None:
        return None

    try:
        buf = io.BytesIO()

        fig, ax = plt.subplots(figsize=(12, 5))

        # 实体顶部和底部 (不含上下影线)
        body_top = np.maximum(df['Open'].values, df['Close'].values)
        body_bot = np.minimum(df['Open'].values, df['Close'].values)
        x = np.arange(len(df))

        # 画两条线
        ax.plot(x, body_top, color='red', linewidth=2.0, label='Body Top (max of Open/Close)', marker='o', markersize=3)
        ax.plot(x, body_bot, color='dodgerblue', linewidth=2.0, label='Body Bottom (min of Open/Close)', marker='o', markersize=3)

        # 填充实体之间区域 (淡灰色)
        ax.fill_between(x, body_bot, body_top, alpha=0.08, color='gray')

        # 简洁网格
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_title(title, fontsize=13, fontweight='bold')
        ax.legend(loc='upper left', fontsize=11)
        ax.set_xlabel('Bar #', fontsize=10)
        ax.set_ylabel('Price', fontsize=10)

        # X轴只标几个刻度
        tick_positions = [0, len(df)//4, len(df)//2, 3*len(df)//4, len(df)-1]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([str(p+1) for p in tick_positions])

        plt.tight_layout()
        fig.savefig(buf, dpi=100, bbox_inches='tight')
        plt.close(fig)

        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        # 计算方向 (供日志)
        top_change = (body_top[-1] - body_top[0]) / body_top[0] * 100 if body_top[0] > 0 else 0
        bot_change = (body_bot[-1] - body_bot[0]) / body_bot[0] * 100 if body_bot[0] > 0 else 0
        print(f"[Vision v3.0] {title} 实体顶{top_change:+.1f}% 实体底{bot_change:+.1f}%")

        return image_base64

    except Exception as e:
        print(f"[Vision] 简洁图表生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_pattern_chart(bars: List[Dict], title: str = "") -> Optional[str]:
    """
    v3.1: 形态专用图 — K线实体矩形(绿/红) + EMA20黄色虚线 + 成交量柱
    比极简图多一点(K线实体+EMA20+量能), 比旧复杂图少很多(无影线/多EMA/趋势线)
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("[Vision] matplotlib未安装")
        return None

    df = bars_to_dataframe(bars)
    if df is None:
        return None

    try:
        buf = io.BytesIO()
        fig, (ax_price, ax_vol) = plt.subplots(2, 1, figsize=(12, 6),
                                                 gridspec_kw={'height_ratios': [4, 1]},
                                                 sharex=True)

        opens = df['Open'].values
        closes = df['Close'].values
        volumes = df['Volume'].values
        x = np.arange(len(df))

        # K线实体矩形 (无影线)
        bar_width = 0.6
        for i in range(len(df)):
            o, c = opens[i], closes[i]
            if c >= o:
                # 阳线: 绿色
                ax_price.bar(x[i], c - o, bottom=o, width=bar_width,
                           color='#26a69a', edgecolor='#26a69a', linewidth=0.5)
            else:
                # 阴线: 红色
                ax_price.bar(x[i], o - c, bottom=c, width=bar_width,
                           color='#ef5350', edgecolor='#ef5350', linewidth=0.5)

        # EMA20 黄色虚线
        ema_period = PATTERN_CHART_CONFIG.get("ema_period", 20)
        if len(closes) >= ema_period:
            ema20 = calculate_ema(df['Close'], ema_period)
            ax_price.plot(x, ema20.values, color='#FFD700', linewidth=1.5,
                        linestyle='--', label=f'EMA{ema_period}', alpha=0.8)

        # 成交量柱 (灰色, 底部)
        vol_colors = ['#26a69a' if closes[i] >= opens[i] else '#ef5350' for i in range(len(df))]
        ax_vol.bar(x, volumes, width=bar_width, color=vol_colors, alpha=0.4)

        # 简洁网格
        ax_price.grid(True, alpha=0.2, linestyle='--')
        ax_vol.grid(True, alpha=0.2, linestyle='--')

        ax_price.set_title(title, fontsize=13, fontweight='bold')
        ax_price.legend(loc='upper left', fontsize=10)
        ax_price.set_ylabel('Price', fontsize=10)
        ax_vol.set_ylabel('Volume', fontsize=9)
        ax_vol.set_xlabel('Bar #', fontsize=10)

        # X轴刻度
        tick_positions = [0, len(df)//4, len(df)//2, 3*len(df)//4, len(df)-1]
        ax_vol.set_xticks(tick_positions)
        ax_vol.set_xticklabels([str(p+1) for p in tick_positions])

        plt.tight_layout()
        fig.savefig(buf, dpi=100, bbox_inches='tight')
        plt.close(fig)

        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        print(f"[Vision v3.1] {title} 形态图生成完成 ({len(bars)}根K线)")
        return image_base64

    except Exception as e:
        print(f"[Vision] 形态图表生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_chart_image(bars: List[Dict], title: str = "") -> Optional[str]:
    """
    v2.1: 生成K线+EMA+清晰趋势线图表 → base64字符串 (备用)
    包含:
    - EMA9(蓝), EMA21(橙), EMA55(紫)
    - 高点趋势线(红实线) - 只连最近3个显著高点
    - 低点趋势线(绿实线) - 只连最近3个显著低点
    - 趋势方向标注文字
    """
    try:
        import mplfinance as mpf
        import numpy as np
        import matplotlib.pyplot as plt
    except ImportError:
        print("[Vision] mplfinance未安装: pip install mplfinance")
        return None

    df = bars_to_dataframe(bars)
    if df is None:
        return None

    try:
        buf = io.BytesIO()

        # 计算EMA
        ema9 = calculate_ema(df['Close'], 9)
        ema21 = calculate_ema(df['Close'], 21)
        ema55 = calculate_ema(df['Close'], 55)

        # 构建addplot列表
        addplots = [
            mpf.make_addplot(ema9, color='blue', width=1.0),
            mpf.make_addplot(ema21, color='orange', width=1.2),
            mpf.make_addplot(ema55, color='purple', width=1.5),
        ]

        # v2.1: 找波段高低点 (window=8 减少噪点)
        highs_idx, highs_val, lows_idx, lows_val = find_swing_points(df, window=8)

        # v2.1: 计算趋势方向
        high_direction, high_slope, high_last_idx, high_last_val = calculate_trend_direction(highs_idx, highs_val, n_points=3)
        low_direction, low_slope, low_last_idx, low_last_val = calculate_trend_direction(lows_idx, lows_val, n_points=3)

        # v2.1: 只画最近3个高点的连线 (红色实线，更粗更显眼)
        if len(high_last_idx) >= 2:
            high_line = pd.Series([np.nan] * len(df), index=df.index, dtype=float)
            for i, idx in enumerate(high_last_idx):
                if idx < len(df):
                    high_line.iloc[idx] = float(high_last_val[i])
            high_line = high_line.interpolate(method='linear', limit_direction='both')
            addplots.append(mpf.make_addplot(high_line, color='crimson', linestyle='-', width=2.5))

        # v2.1: 只画最近3个低点的连线 (蓝色实线，与K线绿色区分)
        if len(low_last_idx) >= 2:
            low_line = pd.Series([np.nan] * len(df), index=df.index, dtype=float)
            for i, idx in enumerate(low_last_idx):
                if idx < len(df):
                    low_line.iloc[idx] = float(low_last_val[i])
            low_line = low_line.interpolate(method='linear', limit_direction='both')
            addplots.append(mpf.make_addplot(low_line, color='dodgerblue', linestyle='-', width=2.5))

        # v2.1: 综合判断趋势方向 (高低点都下降=DOWN, 都上升=UP, 其他=SIDE)
        if high_direction == "DOWN" and low_direction == "DOWN":
            overall_trend = "DOWN"
            trend_arrow = "↘"
        elif high_direction == "UP" and low_direction == "UP":
            overall_trend = "UP"
            trend_arrow = "↗"
        else:
            overall_trend = "SIDE"
            trend_arrow = "↔"

        # v2.1: 在标题中加入趋势方向标注
        trend_label = f" | TREND: {trend_arrow} {overall_trend} (H:{high_slope:+.1f}% L:{low_slope:+.1f}%)"
        enhanced_title = title + trend_label

        mpf.plot(
            df,
            type="candle",
            volume=True,
            style=CHART_CONFIG.get("style", "charles"),
            title=enhanced_title,
            figsize=(CHART_CONFIG.get("width", 12), CHART_CONFIG.get("height", 6)),
            addplot=addplots,
            savefig=dict(fname=buf, dpi=CHART_CONFIG.get("dpi", 100), bbox_inches="tight"),
        )

        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        print(f"[Vision v2.1] {title} 趋势线: 高点{high_direction}({high_slope:+.1f}%) 低点{low_direction}({low_slope:+.1f}%) → {overall_trend}")

        return image_base64

    except Exception as e:
        print(f"[Vision] 图表生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# 需求一: 干净K线图 (Vision专用) — K线 + EMA10 + 成交量，其余全去掉
# 规格: 1200×800px, 黑色背景, 无MACD/RSI/布林/趋势线/网格线
# ============================================================================

def generate_clean_chart(bars: List[Dict], title: str = "", timeframe: str = "daily") -> Optional[str]:
    """
    v1.0: Vision专用干净K线图
    只保留: K线(实体+影线，涨绿跌红) + EMA10(白色) + 成交量(底部，涨绿跌红)
    去掉: 所有其他指标/趋势线/网格线
    规格: 1200×800px, 黑色背景
    """
    try:
        import mplfinance as mpf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("[Vision] mplfinance未安装")
        return None

    df = bars_to_dataframe(bars)
    if df is None or len(df) < 5:
        return None

    try:
        buf = io.BytesIO()

        # EMA10 白色线
        ema10 = calculate_ema(df['Close'], 10)

        # 自定义黑色背景样式
        mc = mpf.make_marketcolors(
            up='#26a69a',     # 涨绿
            down='#ef5350',   # 跌红
            edge='inherit',
            wick='inherit',
            volume={'up': '#26a69a', 'down': '#ef5350'},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            facecolor='#000000',    # 黑色背景
            edgecolor='#333333',
            figcolor='#000000',
            gridcolor='#111111',    # 网格颜色与背景近似=不可见
            gridstyle='-',
            y_on_right=True,
        )

        addplots = [
            mpf.make_addplot(ema10, color='#ffffff', width=1.2, linestyle='-'),
        ]

        mpf.plot(
            df,
            type='candle',
            volume=True,
            style=style,
            title=f" {title}",
            figsize=(12, 8),         # 1200×800 @ dpi=100
            addplot=addplots,
            tight_layout=True,
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight',
                         facecolor='#000000'),
        )

        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        bar_count = len(df)
        print(f"[Vision v1.0] clean chart: {title} | {bar_count}根K线 | {timeframe}")
        return img_b64

    except Exception as e:
        print(f"[Vision] clean chart生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# ChatGPT Vision API
# ============================================================================

def call_chatgpt_vision(image_base64: str, prompt: str = None, max_retries: int = 3,
                        expected_mode: str = "trend", symbol: str = "") -> Optional[Dict]:
    """
    调用Vision API分析图表 — 统一使用Claude Sonnet 4 (GPT-5.2已停用)
    Returns: {"regime": ..., "direction": ..., "confidence": ..., "reason": ...}
    """
    # 统一走Claude (GPT-5.2已停用)
    return call_claude_vision(image_base64, prompt, max_retries, expected_mode, symbol=symbol)


# ============================================================================
# Claude Vision Fallback (GPT失败时自动切换)
# ============================================================================

def call_claude_vision(image_base64: str, prompt: str = None,
                       max_retries: int = 2,
                       expected_mode: str = "trend",
                       symbol: str = "") -> Optional[Dict]:
    """
    v3.3: Claude Vision fallback — GPT失败时自动调用。
    使用 Anthropic Messages API + base64 image。
    """
    if not ANTHROPIC_API_KEY:
        print("[Vision] ANTHROPIC_API_KEY未配置，Claude fallback不可用")
        return None

    try:
        import anthropic
    except ImportError:
        print("[Vision] anthropic未安装: pip install anthropic")
        return None

    if prompt is None:
        prompt = VISION_PROMPT

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            text = text.strip()

            if "{" in text and "}" in text:
                json_str = text[text.index("{"):text.rindex("}") + 1]
                result = json.loads(json_str)
                result["direction"] = result.get("direction", "SIDE").upper()
                result["confidence"] = float(result.get("confidence", 0.5))
                result["n_pattern"] = result.get("n_pattern", "NONE").upper()
                if "regime" not in result:
                    result["regime"] = "TRENDING" if result["direction"] in ("UP", "DOWN") else "RANGING"
                else:
                    result["regime"] = result["regime"].upper()
                print(f"[Vision] Claude fallback成功 (尝试{attempt+1})")
                # GCC: 持久化Claude读图记录
                try:
                    _hist_dir = os.path.join(STATE_DIR, "vision")
                    os.makedirs(_hist_dir, exist_ok=True)
                    _hist_entry = {
                        "ts": datetime.now().isoformat(),
                        "symbol": symbol,
                        "mode": expected_mode,
                        "model": "claude-sonnet-4-6",
                        "raw_text": text,
                        "parsed": result,
                    }
                    with open(os.path.join(_hist_dir, "vision_history.jsonl"), "a", encoding="utf-8") as _hf:
                        _hf.write(json.dumps(_hist_entry, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                return result

            print(f"[Vision] Claude返回非JSON (尝试{attempt+1}/{max_retries}): {text[:100]}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None

        except Exception as e:
            print(f"[Vision] Claude调用失败 (尝试{attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None

    return None


# ============================================================================
# 统一Vision调用接口
# ============================================================================

def get_prompt_for_period(period: str, current_label: str = "4-hour", x4_label: str = "16-hour") -> str:
    """
    v2.8: 根据周期选择对应的提示词 (动态label)
    - current: 关注短期动量
    - x4: 关注大趋势结构
    """
    if period == "x4":
        return build_prompt_x4_gpt(x4_label)
    return build_prompt_current_gpt(current_label)


def call_vision_api(image_base64: str, prompt: str = None, max_retries: int = 3, period: str = "current",
                    current_label: str = "4-hour", x4_label: str = "16-hour",
                    symbol: str = "") -> Optional[Dict]:
    """
    调用GPT-4o Vision API
    v2.9: Claude API已移除，仅GPT-4o
    """
    # v2.8: 如果未指定prompt，根据period和label动态生成
    if prompt is None:
        prompt = get_prompt_for_period(period, current_label, x4_label)
        print(f"[Vision v2.9] 使用{period}周期提示词 (label={current_label if period != 'x4' else x4_label})")

    print(f"[Vision v2.9] 使用GPT-4o")
    return call_chatgpt_vision(image_base64, prompt, max_retries, expected_mode="trend", symbol=symbol)


def _validate_pattern_result(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """v3.3: 校验并规范化形态识别结果"""
    if not isinstance(raw, dict):
        return None

    pattern = str(raw.get("pattern", "NONE")).upper()
    stage = str(raw.get("stage", "NONE")).upper()

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None

    if pattern not in PATTERN_ALLOWED_TYPES:
        return None
    if stage not in PATTERN_ALLOWED_STAGES:
        return None
    if not (0.0 <= confidence <= 1.0):
        return None

    STRUCTURE_ALLOWED = {"ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN", "UNKNOWN"}
    POSITION_ALLOWED  = {"HIGH", "MID", "LOW"}
    overall_structure = str(raw.get("overall_structure", "UNKNOWN")).upper()
    position          = str(raw.get("position", "MID")).upper()
    if overall_structure not in STRUCTURE_ALLOWED:
        overall_structure = "UNKNOWN"
    if position not in POSITION_ALLOWED:
        position = "MID"

    return {
        "pattern": pattern,
        "stage": stage,
        "confidence": confidence,
        "volume_confirmed": bool(raw.get("volume_confirmed", False)),
        "reason": str(raw.get("reason", "")),
        "overall_structure": overall_structure,
        "position": position,
    }


def _parse_radar_to_pattern(radar_dict: dict) -> Optional[Dict[str, Any]]:
    """GCC-0194: RADAR_PROMPT输出 → pattern_latest.json格式
    RADAR_PROMPT返回: {direction, confidence(0-100), reason, stoploss, brooks_pattern}
    转换为: {pattern, stage, confidence(0-1), volume_confirmed, reason, overall_structure, position, ...}
    """
    if not isinstance(radar_dict, dict):
        return None

    direction = str(radar_dict.get("direction", "SIDE")).upper()
    conf_raw = radar_dict.get("confidence", 50)
    try:
        conf_raw = float(conf_raw)
    except (TypeError, ValueError):
        conf_raw = 50.0
    # RADAR_PROMPT输出0-100整数, 转换为0.0-1.0
    if conf_raw > 1.0:
        confidence = min(1.0, max(0.0, conf_raw / 100.0))
    else:
        confidence = min(1.0, max(0.0, conf_raw))

    brooks_pattern = str(radar_dict.get("brooks_pattern", "NONE")).upper()
    reason = str(radar_dict.get("reason", ""))
    try:
        stoploss = float(radar_dict.get("stoploss", 0))
    except (TypeError, ValueError):
        stoploss = 0.0

    # 兼容旧形态名 (WEDGE→方向性, MTR→方向性)
    if brooks_pattern == "WEDGE" and direction in ("UP", "DOWN"):
        brooks_pattern = "WEDGE_FALLING" if direction == "UP" else "WEDGE_RISING"
    elif brooks_pattern == "MTR" and direction in ("UP", "DOWN"):
        brooks_pattern = "MTR_BUY" if direction == "UP" else "MTR_SELL"
    elif brooks_pattern in ("WEDGE", "MTR"):
        brooks_pattern = "NONE"

    # 白名单校验
    if brooks_pattern not in PATTERN_ALLOWED_TYPES:
        brooks_pattern = "NONE"

    # pattern字段: 使用brooks_pattern
    pattern = brooks_pattern

    # stage推导
    if pattern != "NONE" and confidence >= 0.7:
        stage = "BREAKOUT"
    elif pattern != "NONE":
        stage = "FORMING"
    else:
        stage = "NONE"

    # environment → overall_structure映射
    overall_structure = _infer_structure_from_radar(radar_dict, direction)

    # position: RADAR_PROMPT不直接输出position, 默认MID
    position = "MID"

    return {
        "pattern": pattern,
        "stage": stage,
        "confidence": confidence,
        "volume_confirmed": False,  # RADAR_PROMPT不输出此字段
        "reason": reason,
        "overall_structure": overall_structure,
        "position": position,
        "stoploss": stoploss,
        "brooks_pattern": brooks_pattern,
        "direction": direction,
    }


def _infer_structure_from_radar(radar_dict: dict, direction: str) -> str:
    """GCC-0194: 从RADAR_PROMPT的brooks_pattern推导overall_structure"""
    bp = str(radar_dict.get("brooks_pattern", "NONE")).upper()

    # 环境型形态直接映射
    if bp == "TRADING_RANGE":
        return "ACCUMULATION" if direction == "UP" else "DISTRIBUTION"
    elif bp in ("TIGHT_CHANNEL", "BROAD_CHANNEL"):
        return "MARKUP" if direction == "UP" else "MARKDOWN"
    elif bp == "CLIMAX":
        return "DISTRIBUTION" if direction == "UP" else "MARKDOWN"
    elif bp == "BREAKOUT":
        return "MARKUP" if direction == "UP" else "MARKDOWN"

    # 有方向的形态
    if direction == "UP":
        return "MARKUP"
    elif direction == "DOWN":
        return "MARKDOWN"
    return "UNKNOWN"


# 当前分析的品种和周期 (供日志使用)
_current_analysis_context = {"symbol": "", "period": "", "dual_results": {"current": {}, "x4": {}}}

# v2.9: call_vision_dual 已移除 (GPT-4o only, 不再需要双模型对比)


# ============================================================================
# L1对比
# ============================================================================

def read_l1_decision(symbol: str) -> Optional[Dict]:
    """
    从global_trend_state.json读取L1决策
    Returns: {current_trend, trend_x4, regime, big_trend}
    """
    state = load_json_file(L1_STATE_FILE)
    if not state or "symbols" not in state:
        return None

    sym_state = state.get("symbols", {}).get(symbol)
    if not sym_state:
        return None

    # v2.0: 统一使用 big_trend 作为x4大周期定义 (五模块综合判断)
    # 不再使用 trend_x4 (道氏理论原始计算)，避免混乱
    return {
        "current_trend": sym_state.get("current_trend", "SIDE"),
        "trend_x4": sym_state.get("big_trend", "SIDE"),  # 统一用big_trend
        "regime": sym_state.get("regime", "RANGING"),
        "current_regime": sym_state.get("current_regime", "UNKNOWN"),
        "regime_x4": sym_state.get("regime_x4", "UNKNOWN"),
        "big_trend": sym_state.get("big_trend", "SIDE"),
    }


def get_previous_analysis(symbol: str) -> Optional[Dict]:
    """获取该品种上一次的分析记录"""
    data = load_json_file(COMPARISON_FILE)
    comparisons = data.get("comparisons", [])
    # 找该品种最近的记录
    symbol_records = [c for c in comparisons if c.get("symbol") == symbol]
    if symbol_records:
        return symbol_records[-1]  # 最后一条
    return None


def compare_vision_vs_l1(vision_current: Dict, vision_x4: Dict,
                          l1_decision: Dict, symbol: str, price: float,
                          l1_timeframe: int = 240) -> Dict:
    """
    v2.2: 两层比较
    - Layer1: 同一根K线内 GPT vs Claude vs L1
    - Layer2: 跨K线 当前判断 vs 上一根K线判断
    """
    # Vision方向转换 (选中的结果)
    v_current_dir = vision_current.get("direction", "SIDE") if vision_current else "UNKNOWN"
    v_x4_dir = vision_x4.get("direction", "SIDE") if vision_x4 else "UNKNOWN"
    v_current_regime = vision_current.get("regime", "UNKNOWN") if vision_current else "UNKNOWN"
    v_x4_regime = vision_x4.get("regime", "UNKNOWN") if vision_x4 else "UNKNOWN"

    # v2.1: 获取分别的GPT-4o和Claude结果
    dual_results = _current_analysis_context.get("dual_results", {})
    current_dual = dual_results.get("current", {})
    x4_dual = dual_results.get("x4", {})

    gpt_current = current_dual.get("gpt4o", {})
    claude_current = current_dual.get("claude", {})
    gpt_x4 = x4_dual.get("gpt4o", {})
    claude_x4 = x4_dual.get("claude", {})

    # 提取方向
    gpt_cur_dir = gpt_current.get("direction", "UNKNOWN").upper() if gpt_current else "UNKNOWN"
    claude_cur_dir = claude_current.get("direction", "UNKNOWN").upper() if claude_current else "UNKNOWN"
    gpt_x4_dir = gpt_x4.get("direction", "UNKNOWN").upper() if gpt_x4 else "UNKNOWN"
    claude_x4_dir = claude_x4.get("direction", "UNKNOWN").upper() if claude_x4 else "UNKNOWN"

    # L1方向
    l1_current = l1_decision.get("current_trend", "SIDE").upper() if l1_decision else "UNKNOWN"
    l1_x4 = l1_decision.get("trend_x4", "SIDE").upper() if l1_decision else "UNKNOWN"

    # ========== Layer 1: 同一根K线内比较 ==========
    def is_match(a: str, b: str) -> Optional[bool]:
        if a == "UNKNOWN" or b == "UNKNOWN":
            return None
        return a == b

    # 当前周期比较
    layer1_gpt_claude_cur = is_match(gpt_cur_dir, claude_cur_dir)  # GPT vs Claude
    layer1_gpt_l1_cur = is_match(gpt_cur_dir, l1_current)          # GPT vs L1
    layer1_claude_l1_cur = is_match(claude_cur_dir, l1_current)    # Claude vs L1

    # X4周期比较
    layer1_gpt_claude_x4 = is_match(gpt_x4_dir, claude_x4_dir)
    layer1_gpt_l1_x4 = is_match(gpt_x4_dir, l1_x4)
    layer1_claude_l1_x4 = is_match(claude_x4_dir, l1_x4)

    # ========== Layer 2: 跨K线比较 (当前 vs 上一根) ==========
    prev = get_previous_analysis(symbol)

    layer2_gpt_consistent_cur = None
    layer2_claude_consistent_cur = None
    layer2_gpt_consistent_x4 = None
    layer2_claude_consistent_x4 = None
    prev_timestamp = None

    if prev:
        prev_timestamp = prev.get("timestamp")
        prev_gpt_cur = prev.get("gpt4o_current_direction", "UNKNOWN").upper()
        prev_claude_cur = prev.get("claude_current_direction", "UNKNOWN").upper()
        prev_gpt_x4 = prev.get("gpt4o_x4_direction", "UNKNOWN").upper()
        prev_claude_x4 = prev.get("claude_x4_direction", "UNKNOWN").upper()

        # GPT判断是否连贯 (当前周期)
        layer2_gpt_consistent_cur = is_match(gpt_cur_dir, prev_gpt_cur)
        # Claude判断是否连贯 (当前周期)
        layer2_claude_consistent_cur = is_match(claude_cur_dir, prev_claude_cur)
        # GPT判断是否连贯 (X4周期)
        layer2_gpt_consistent_x4 = is_match(gpt_x4_dir, prev_gpt_x4)
        # Claude判断是否连贯 (X4周期)
        layer2_claude_consistent_x4 = is_match(claude_x4_dir, prev_claude_x4)

    # 向后兼容
    current_match = v_current_dir.upper() == l1_current if v_current_dir != "UNKNOWN" and l1_current != "UNKNOWN" else None
    x4_match = v_x4_dir.upper() == l1_x4 if v_x4_dir != "UNKNOWN" and l1_x4 != "UNKNOWN" else None

    return {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "price_at_analysis": price,
        "l1_timeframe": l1_timeframe,
        # v2.1: GPT-4o 单独结果
        "gpt4o_current_direction": gpt_cur_dir,
        "gpt4o_current_confidence": gpt_current.get("confidence", 0) if gpt_current else 0,
        "gpt4o_x4_direction": gpt_x4_dir,
        "gpt4o_x4_confidence": gpt_x4.get("confidence", 0) if gpt_x4 else 0,
        # v2.1: Claude 单独结果
        "claude_current_direction": claude_cur_dir,
        "claude_current_confidence": claude_current.get("confidence", 0) if claude_current else 0,
        "claude_x4_direction": claude_x4_dir,
        "claude_x4_confidence": claude_x4.get("confidence", 0) if claude_x4 else 0,
        # Vision结果 (选中的，向后兼容)
        "vision_current_direction": v_current_dir,
        "vision_current_regime": v_current_regime,
        "vision_current_confidence": vision_current.get("confidence", 0) if vision_current else 0,
        "vision_x4_direction": v_x4_dir,
        "vision_x4_regime": v_x4_regime,
        "vision_x4_confidence": vision_x4.get("confidence", 0) if vision_x4 else 0,
        # L1结果
        "l1_current_trend": l1_current,
        "l1_trend_x4": l1_x4,
        "l1_regime": l1_decision.get("regime", "UNKNOWN") if l1_decision else "UNKNOWN",
        # 向后兼容
        "current_match": current_match,
        "x4_match": x4_match,
        # ===== v2.2: Layer 1 同K线比较 =====
        "layer1_gpt_claude_cur": layer1_gpt_claude_cur,   # GPT vs Claude (当前)
        "layer1_gpt_l1_cur": layer1_gpt_l1_cur,           # GPT vs L1 (当前)
        "layer1_claude_l1_cur": layer1_claude_l1_cur,     # Claude vs L1 (当前)
        "layer1_gpt_claude_x4": layer1_gpt_claude_x4,     # GPT vs Claude (X4)
        "layer1_gpt_l1_x4": layer1_gpt_l1_x4,             # GPT vs L1 (X4)
        "layer1_claude_l1_x4": layer1_claude_l1_x4,       # Claude vs L1 (X4)
        # ===== v2.2: Layer 2 跨K线比较 =====
        "prev_timestamp": prev_timestamp,
        "layer2_gpt_consistent_cur": layer2_gpt_consistent_cur,     # GPT连贯 (当前)
        "layer2_claude_consistent_cur": layer2_claude_consistent_cur,  # Claude连贯 (当前)
        "layer2_gpt_consistent_x4": layer2_gpt_consistent_x4,       # GPT连贯 (X4)
        "layer2_claude_consistent_x4": layer2_claude_consistent_x4,   # Claude连贯 (X4)
        # 验证(后续填写)
        "verified": False,
        "price_after_4bars": None,
        "who_correct": None,
    }


# ============================================================================
# 数据存储
# ============================================================================

def save_analysis_record(symbol: str, l1_timeframe: int,
                         current_result: Dict, x4_result: Dict, latency_ms: int):
    """保存Vision分析记录"""
    history = load_json_file(HISTORY_FILE)
    if "records" not in history:
        history["records"] = []

    record = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "l1_timeframe": l1_timeframe,
        "current": current_result,
        "x4": x4_result,
        "latency_ms": latency_ms,
    }

    history["records"].append(record)
    save_json_file(HISTORY_FILE, history)


def save_latest_result(symbol: str, current_result: Dict, x4_result: Dict):
    """
    v2.0: 保存最新分析结果供主程序读取

    主程序 llm_server 会读取此文件来获取 Vision 分析结果，
    用于覆盖 L1 当前周期趋势判断。

    文件格式:
    {
        "BTCUSDC": {
            "current": {"regime": "TRENDING", "direction": "DOWN", "confidence": 0.85},
            "x4": {"regime": "RANGING", "direction": "SIDE", "confidence": 0.75},
            "timestamp": "2026-01-30T14:00:00"
        },
        ...
    }
    """
    try:
        data = load_json_file(LATEST_FILE)
        if not isinstance(data, dict):
            data = {}

        data[symbol] = {
            "current": current_result,
            "x4": x4_result,
            "timestamp": datetime.now().isoformat(),
        }

        save_json_file(LATEST_FILE, data)
        print(f"[Vision] {symbol} latest.json 已更新")

    except Exception as e:
        print(f"[Vision] {symbol} latest.json 保存失败: {e}")


def save_comparison_record(comparison: Dict):
    """保存对比记录"""
    data = load_json_file(COMPARISON_FILE)
    if "comparisons" not in data:
        data["comparisons"] = []
        data["stats"] = {}

    data["comparisons"].append(comparison)

    # v2.2: 更新统计 - 包含Layer1和Layer2
    comparisons = data["comparisons"]
    total = len(comparisons)

    # Layer1 统计 (同K线比较)
    def count_true(key):
        return sum(1 for c in comparisons if c.get(key) is True)
    def count_valid(key):
        return sum(1 for c in comparisons if c.get(key) is not None)
    def rate(key):
        valid = count_valid(key)
        return count_true(key) / valid if valid > 0 else 0

    data["stats"] = {
        "total": total,
        "last_updated": datetime.now().isoformat(),
        # Layer1: GPT vs Claude
        "layer1_gpt_claude_cur": rate("layer1_gpt_claude_cur"),
        "layer1_gpt_claude_x4": rate("layer1_gpt_claude_x4"),
        # Layer1: GPT vs L1
        "layer1_gpt_l1_cur": rate("layer1_gpt_l1_cur"),
        "layer1_gpt_l1_x4": rate("layer1_gpt_l1_x4"),
        # Layer1: Claude vs L1
        "layer1_claude_l1_cur": rate("layer1_claude_l1_cur"),
        "layer1_claude_l1_x4": rate("layer1_claude_l1_x4"),
        # Layer2: 连贯性
        "layer2_gpt_consistent_cur": rate("layer2_gpt_consistent_cur"),
        "layer2_gpt_consistent_x4": rate("layer2_gpt_consistent_x4"),
        "layer2_claude_consistent_cur": rate("layer2_claude_consistent_cur"),
        "layer2_claude_consistent_x4": rate("layer2_claude_consistent_x4"),
        # 向后兼容
        "current_match_rate": rate("current_match"),
        "x4_match_rate": rate("x4_match"),
    }

    save_json_file(COMPARISON_FILE, data)

    # v2.2: 写入永久日志 - Layer1 + Layer2 比较
    def mark(v):
        return "Y" if v is True else "N" if v is False else "-"

    sym = comparison['symbol']
    ts = comparison['timestamp'][11:19]  # HH:MM:SS

    # 模型判断
    gpt_cur = comparison.get('gpt4o_current_direction', '-')[:4]
    gpt_x4 = comparison.get('gpt4o_x4_direction', '-')[:4]
    cla_cur = comparison.get('claude_current_direction', '-')[:4]
    cla_x4 = comparison.get('claude_x4_direction', '-')[:4]
    l1_cur = comparison.get('l1_current_trend', '-')[:4]
    l1_x4 = comparison.get('l1_trend_x4', '-')[:4]

    # Layer1 比较
    l1_gc_cur = mark(comparison.get('layer1_gpt_claude_cur'))
    l1_gl_cur = mark(comparison.get('layer1_gpt_l1_cur'))
    l1_cl_cur = mark(comparison.get('layer1_claude_l1_cur'))
    l1_gc_x4 = mark(comparison.get('layer1_gpt_claude_x4'))
    l1_gl_x4 = mark(comparison.get('layer1_gpt_l1_x4'))
    l1_cl_x4 = mark(comparison.get('layer1_claude_l1_x4'))

    # Layer2 比较
    l2_gpt_cur = mark(comparison.get('layer2_gpt_consistent_cur'))
    l2_cla_cur = mark(comparison.get('layer2_claude_consistent_cur'))
    l2_gpt_x4 = mark(comparison.get('layer2_gpt_consistent_x4'))
    l2_cla_x4 = mark(comparison.get('layer2_claude_consistent_x4'))

    log_verification("=" * 70)
    log_verification(f"[{sym}] {ts} | Price: {comparison.get('price_at_analysis', 0):.2f}")
    log_verification("-" * 70)
    # v2.9: Claude已移除，仅显示GPT-4o和L1
    log_verification(f"{'Model':<8} {'Current':>8} {'X4':>8}")
    log_verification(f"{'GPT-4o':<8} {gpt_cur:>8} {gpt_x4:>8}")
    log_verification(f"{'L1-Tech':<8} {l1_cur:>8} {l1_x4:>8}")
    log_verification("-" * 70)
    log_verification(f"Layer1 (same bar):")
    log_verification(f"  GPT=L1: cur={l1_gl_cur} x4={l1_gl_x4}")
    log_verification(f"Layer2 (vs prev bar):")
    log_verification(f"  GPT consistent: cur={l2_gpt_cur} x4={l2_gpt_x4}")


def save_prediction_log(symbol: str, current_result: Optional[Dict], x4_result: Optional[Dict],
                        l1_decision: Dict, price: float):
    """
    保存统一日志，包含GPT-4o、Claude、L1三方预测
    格式: NDJSON，每行一条完整记录
    文件: state/vision/vision_analysis.log
    """
    # 从内存获取双模型对比结果
    dual_results = _current_analysis_context.get("dual_results", {})
    current_dual = dual_results.get("current", {})
    x4_dual = dual_results.get("x4", {})

    gpt_current = current_dual.get("gpt4o")
    claude_current = current_dual.get("claude")
    gpt_x4 = x4_dual.get("gpt4o")
    claude_x4 = x4_dual.get("claude")

    # 构建统一日志记录
    record = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "price": round(price, 2),
        "verify_after": (datetime.now() + timedelta(hours=12)).isoformat()[:16],
        "current": {
            "gpt4o": gpt_current.get("direction") if gpt_current else None,
            "gpt4o_conf": gpt_current.get("confidence") if gpt_current else None,
            "gpt4o_reason": gpt_current.get("reason", "")[:80] if gpt_current else None,
            "claude": claude_current.get("direction") if claude_current else None,
            "claude_conf": claude_current.get("confidence") if claude_current else None,
            "claude_reason": claude_current.get("reason", "")[:80] if claude_current else None,
            "l1": l1_decision.get("current_trend"),
            "agree": (gpt_current.get("direction") == claude_current.get("direction")) if gpt_current and claude_current else None,
        },
        "x4": {
            "gpt4o": gpt_x4.get("direction") if gpt_x4 else None,
            "gpt4o_conf": gpt_x4.get("confidence") if gpt_x4 else None,
            "gpt4o_reason": gpt_x4.get("reason", "")[:80] if gpt_x4 else None,
            "claude": claude_x4.get("direction") if claude_x4 else None,
            "claude_conf": claude_x4.get("confidence") if claude_x4 else None,
            "claude_reason": claude_x4.get("reason", "")[:80] if claude_x4 else None,
            "l1": l1_decision.get("trend_x4"),
            "agree": (gpt_x4.get("direction") == claude_x4.get("direction")) if gpt_x4 and claude_x4 else None,
        },
    }

    # 写入统一日志文件
    try:
        ensure_state_dir()
        with open(UNIFIED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 打印汇总
        cur = record["current"]
        x4 = record["x4"]
        agree_cur = "[一致]" if cur["agree"] else "[分歧]" if cur["agree"] is False else "[?]"
        agree_x4 = "[一致]" if x4["agree"] else "[分歧]" if x4["agree"] is False else "[?]"
        # v2.9: Claude已移除，仅显示GPT-4o和L1
        print(f"\n[Vision] === {symbol} GPT+L1预测汇总 ===")
        print(f"  当前: GPT={cur['gpt4o']}({cur['gpt4o_conf']}) L1={cur['l1']} {agree_cur}")
        print(f"  X4:   GPT={x4['gpt4o']}({x4['gpt4o_conf']}) L1={x4['l1']} {agree_x4}")
        print(f"  价格: {price:.2f} | 验证时间: {record['verify_after']}")
    except Exception as e:
        print(f"[Vision] 统一日志写入失败: {e}")


def get_last_analysis_time(symbol: str) -> Optional[datetime]:
    """获取品种上次分析时间"""
    data = load_json_file(LAST_ANALYSIS_FILE)
    ts = data.get(symbol)
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except:
            pass
    return None


def update_last_analysis_time(symbol: str):
    """更新品种上次分析时间"""
    data = load_json_file(LAST_ANALYSIS_FILE)
    data[symbol] = datetime.now().isoformat()
    save_json_file(LAST_ANALYSIS_FILE, data)


def cleanup_old_records():
    """清理超过保留天数的记录"""
    retention_days = RUN_CONFIG["data_retention_days"]
    cutoff = datetime.now() - timedelta(days=retention_days)

    # 清理history
    history = load_json_file(HISTORY_FILE)
    if "records" in history:
        original_count = len(history["records"])
        history["records"] = [
            r for r in history["records"]
            if datetime.fromisoformat(r.get("timestamp", "2000-01-01")) > cutoff
        ]
        if len(history["records"]) < original_count:
            save_json_file(HISTORY_FILE, history)
            print(f"[Vision] 清理history: {original_count - len(history['records'])}条")

    # 清理comparison
    data = load_json_file(COMPARISON_FILE)
    if "comparisons" in data:
        original_count = len(data["comparisons"])
        data["comparisons"] = [
            c for c in data["comparisons"]
            if datetime.fromisoformat(c.get("timestamp", "2000-01-01")) > cutoff
        ]
        if len(data["comparisons"]) < original_count:
            save_json_file(COMPARISON_FILE, data)
            print(f"[Vision] 清理comparison: {original_count - len(data['comparisons'])}条")


# ============================================================================
# K线周期验证逻辑 (v2.5: Vision先行指标验证)
# ============================================================================
# v2.5核心理念:
# - Vision是先行指标，比L1快约2-3根K线
# - 正确评估: Vision(N) vs L1(N+2) 和 Vision(N) vs L1(N+3)
# - Vision预判 → 2-3根K线后 → L1确认 = Vision有效
# - 同时记录2根和3根确认率，比较哪个更准

VERIFY_AFTER_BARS = 2  # 首次验证在2根K线后
VERIFY_AFTER_BARS_ALT = 3  # 二次验证在3根K线后 (可选比较)
TREND_THRESHOLD_PCT = 1.0  # 涨跌超过1%算趋势，否则算震荡


def get_current_l1_trend(symbol: str) -> Dict:
    """
    v2.6: 从global_trend_state.json读取L1趋势
    主程序会将L1趋势保存到此文件 (格式: state["symbols"][symbol])

    Returns:
        {"current_trend": "UP/DOWN/SIDE", "big_trend": "UP/DOWN/SIDE"}
    """
    # 读取主程序保存的趋势状态文件
    trend_file = os.path.join(os.path.dirname(__file__), "global_trend_state.json")
    try:
        if os.path.exists(trend_file):
            with open(trend_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 格式: state["symbols"][symbol]
            symbols_data = data.get("symbols", {})
            symbol_data = symbols_data.get(symbol, {})
            if symbol_data:
                return {
                    "current_trend": symbol_data.get("current_trend", "UNKNOWN").upper(),
                    "big_trend": symbol_data.get("big_trend", "UNKNOWN").upper(),
                }
    except Exception as e:
        print(f"[Vision] 读取{symbol} L1趋势文件失败: {e}")

    # 如果文件不存在或符号不在其中，返回UNKNOWN (跳过L1验证)
    return {"current_trend": "UNKNOWN", "big_trend": "UNKNOWN"}


def get_current_price(symbol: str) -> Optional[float]:
    """获取当前价格"""
    cfg = SYMBOLS_BASE_CONFIG.get(symbol)
    if not cfg:
        return None

    try:
        import yfinance as yf
        ticker = yf.Ticker(cfg["yf_symbol"])
        hist = ticker.history(period="1d", interval="1m")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"[Vision] 获取{symbol}当前价格失败: {e}")
    return None


def verify_predictions():
    """
    v2.1fix: 按K线周期验证预测是否正确 (不是固定12小时)

    验证时机:
    - 预测后等待1根K线收盘 (如4h图就等4小时)
    - 新K线收盘后比较预测vs实际

    验证逻辑:
    - 涨幅 > 1%: 实际趋势=UP
    - 跌幅 > 1%: 实际趋势=DOWN
    - 波动 < 1%: 实际趋势=SIDE (震荡)

    判断谁对:
    - GPT-4o说UP，实际涨 → GPT-4o对
    - Claude说DOWN，实际跌 → Claude对
    """
    data = load_json_file(COMPARISON_FILE)
    if "comparisons" not in data:
        return

    comparisons = data["comparisons"]
    verified_count = 0
    updated = False
    verification_results = []  # 收集本轮验证结果

    now = datetime.now()

    for comp in comparisons:
        # 跳过已验证的
        if comp.get("verified"):
            continue

        # v2.1fix: 按K线周期计算验证时间
        try:
            analysis_time = datetime.fromisoformat(comp["timestamp"])
        except:
            continue

        # 获取timeframe (默认240分钟=4h，兼容旧记录)
        timeframe_mins = comp.get("l1_timeframe", 240)
        verify_after_mins = timeframe_mins * VERIFY_AFTER_BARS  # 2根K线后验证
        verify_cutoff = analysis_time + timedelta(minutes=verify_after_mins)

        if now < verify_cutoff:
            continue  # 还没到验证时间

        symbol = comp.get("symbol")
        price_at_analysis = comp.get("price_at_analysis", 0)

        if not symbol or not price_at_analysis:
            continue

        # 获取当前价格
        current_price = get_current_price(symbol)
        if not current_price:
            continue

        # 计算涨跌幅
        price_change_pct = ((current_price - price_at_analysis) / price_at_analysis) * 100

        # 判断实际趋势
        if price_change_pct > TREND_THRESHOLD_PCT:
            actual_trend = "UP"
        elif price_change_pct < -TREND_THRESHOLD_PCT:
            actual_trend = "DOWN"
        else:
            actual_trend = "SIDE"

        # v2.1: 分别判断 GPT-4o 和 Claude 当前周期是否正确
        gpt_current = comp.get("gpt4o_current_direction", "").upper()
        claude_current = comp.get("claude_current_direction", "").upper()

        def check_correct(prediction: str, actual: str) -> bool:
            if prediction in ["UP", "DOWN"]:
                return prediction == actual
            else:  # SIDE/RANGING
                return actual == "SIDE"

        gpt_current_correct = check_correct(gpt_current, actual_trend) if gpt_current else None
        claude_current_correct = check_correct(claude_current, actual_trend) if claude_current else None

        # 判断Vision当前周期是否正确 (向后兼容，使用选中的结果)
        vision_current = comp.get("vision_current_direction", "").upper()
        vision_current_correct = check_correct(vision_current, actual_trend) if vision_current else None

        # 判断L1当前周期是否正确
        l1_current = comp.get("l1_current_trend", "").upper()
        l1_current_correct = check_correct(l1_current, actual_trend) if l1_current else None

        # v2.1: 分别判断 GPT-4o 和 Claude X4周期是否正确
        gpt_x4 = comp.get("gpt4o_x4_direction", "").upper()
        claude_x4 = comp.get("claude_x4_direction", "").upper()

        gpt_x4_correct = check_correct(gpt_x4, actual_trend) if gpt_x4 else None
        claude_x4_correct = check_correct(claude_x4, actual_trend) if claude_x4 else None

        # 判断Vision X4是否正确 (向后兼容)
        vision_x4 = comp.get("vision_x4_direction", "").upper()
        vision_x4_correct = check_correct(vision_x4, actual_trend) if vision_x4 else None

        # 判断L1 X4是否正确
        l1_x4 = comp.get("l1_trend_x4", "").upper()
        l1_x4_correct = check_correct(l1_x4, actual_trend) if l1_x4 else None

        # ===== v2.6: L1确认率 - 2根和3根K线双重验证 =====
        # 判断当前是2根还是3根验证时机
        verify_3bar_mins = timeframe_mins * VERIFY_AFTER_BARS_ALT  # 3根K线
        verify_3bar_cutoff = analysis_time + timedelta(minutes=verify_3bar_mins)
        is_3bar_verify = now >= verify_3bar_cutoff

        # 获取当前L1趋势
        current_l1 = get_current_l1_trend(symbol)
        l1_now_current = current_l1.get("current_trend", "UNKNOWN")
        l1_now_big = current_l1.get("big_trend", "UNKNOWN")

        # 判断L1确认
        gpt_l1_confirmed = (gpt_current == l1_now_current) if gpt_current and l1_now_current != "UNKNOWN" else None
        claude_l1_confirmed = (claude_current == l1_now_current) if claude_current and l1_now_current != "UNKNOWN" else None

        # v2.5: 判断市场状态
        l1_original = comp.get("l1_current_trend", "").upper()
        vision_l1_same_moment = (vision_current == l1_original) if vision_current and l1_original else None
        if vision_l1_same_moment:
            if vision_current in ("UP", "DOWN"):
                market_state = "STRONG_TREND"
            else:
                market_state = "RANGING"
        else:
            market_state = "NORMAL_TREND"

        # v2.6: 区分2根和3根验证
        if not comp.get("verified_2bar"):
            # 首次验证 (2根K线)
            comp["verified_2bar"] = True
            comp["verify_2bar_timestamp"] = now.isoformat()
            comp["gpt_l1_confirmed_2bar"] = gpt_l1_confirmed
            comp["claude_l1_confirmed_2bar"] = claude_l1_confirmed
            comp["l1_at_2bar"] = l1_now_current

            # 如果已经到3根时间，同时记录3根数据
            if is_3bar_verify:
                comp["verified_3bar"] = True
                comp["verify_3bar_timestamp"] = now.isoformat()
                comp["gpt_l1_confirmed_3bar"] = gpt_l1_confirmed
                comp["claude_l1_confirmed_3bar"] = claude_l1_confirmed
                comp["l1_at_3bar"] = l1_now_current
                comp["verified"] = True  # 完全验证完成
            else:
                comp["verified"] = False  # 等待3根验证
                continue  # 跳过，等下一轮3根验证

        elif not comp.get("verified_3bar") and is_3bar_verify:
            # 二次验证 (3根K线)
            comp["verified_3bar"] = True
            comp["verify_3bar_timestamp"] = now.isoformat()
            comp["gpt_l1_confirmed_3bar"] = gpt_l1_confirmed
            comp["claude_l1_confirmed_3bar"] = claude_l1_confirmed
            comp["l1_at_3bar"] = l1_now_current
            comp["verified"] = True  # 完全验证完成
        else:
            continue  # 跳过已完成的

        # 更新通用字段 (仅在完全验证完成时)
        if comp.get("verified"):
            comp["verify_timestamp"] = now.isoformat()
            comp["price_after_verify"] = current_price
            comp["price_change_pct"] = round(price_change_pct, 2)
            comp["actual_trend"] = actual_trend
            comp["gpt_current_correct"] = gpt_current_correct
            comp["gpt_x4_correct"] = gpt_x4_correct
            comp["claude_current_correct"] = claude_current_correct
            comp["claude_x4_correct"] = claude_x4_correct
            comp["vision_current_correct"] = vision_current_correct
            comp["vision_x4_correct"] = vision_x4_correct
            comp["l1_current_correct"] = l1_current_correct
            comp["l1_x4_correct"] = l1_x4_correct
            # 向后兼容
            comp["gpt_l1_confirmed"] = comp.get("gpt_l1_confirmed_2bar")
            comp["claude_l1_confirmed"] = comp.get("claude_l1_confirmed_2bar")
            comp["l1_now_current"] = comp.get("l1_at_2bar")
            comp["market_state"] = market_state

        verified_count += 1
        updated = True

        # 收集验证结果用于日志
        verification_results.append({
            "symbol": symbol,
            "price_change_pct": price_change_pct,
            "actual_trend": actual_trend,
            "gpt_current": gpt_current,
            "gpt_current_correct": gpt_current_correct,
            "gpt_x4": gpt_x4,
            "gpt_x4_correct": gpt_x4_correct,
            "claude_current": claude_current,
            "claude_current_correct": claude_current_correct,
            "claude_x4": claude_x4,
            "claude_x4_correct": claude_x4_correct,
            "l1_current": l1_current,
            "l1_current_correct": l1_current_correct,
            "l1_x4": l1_x4,
            "l1_x4_correct": l1_x4_correct,
            # v2.5
            "gpt_l1_confirmed": gpt_l1_confirmed,
            "claude_l1_confirmed": claude_l1_confirmed,
            "l1_now_current": l1_now_current,
            "market_state": market_state,
        })

        # v2.5: 输出验证结果 (含L1确认)
        gpt_cur_mark = "Y" if gpt_current_correct else ("N" if gpt_current_correct is False else "?")
        claude_cur_mark = "Y" if claude_current_correct else ("N" if claude_current_correct is False else "?")
        gpt_confirm = "Y" if gpt_l1_confirmed else ("N" if gpt_l1_confirmed is False else "?")
        claude_confirm = "Y" if claude_l1_confirmed else ("N" if claude_l1_confirmed is False else "?")

        # v2.9: Claude已移除，仅显示GPT-4o
        print(f"[Vision] Verify {symbol}: change={price_change_pct:+.2f}% actual={actual_trend} state={market_state}")
        print(f"         GPT-4o:  预判{gpt_current} 价格{gpt_cur_mark} L1确认{gpt_confirm}(L1now={l1_now_current})")

    if updated:
        # 更新统计
        update_accuracy_stats(data)
        save_json_file(COMPARISON_FILE, data)

        # 写入验证日志
        log_verification("=" * 60)
        log_verification(f"验证批次: {verified_count}条记录")
        log_verification("-" * 60)
        for r in verification_results:
            # v2.1: 安全获取字段，兼容旧记录
            def mark(val):
                if val is True:
                    return "✓"
                elif val is False:
                    return "✗"
                else:
                    return "?"

            gpt_cur = mark(r.get("gpt_current_correct"))
            gpt_x4 = mark(r.get("gpt_x4_correct"))
            claude_cur = mark(r.get("claude_current_correct"))
            claude_x4 = mark(r.get("claude_x4_correct"))
            l1_cur = mark(r.get("l1_current_correct"))
            l1_x4 = mark(r.get("l1_x4_correct"))

            log_verification(f"{r['symbol']}: 涨跌{r['price_change_pct']:+.2f}% 实际={r['actual_trend']}")
            log_verification(f"  GPT-4o: 当前{r.get('gpt_current', '?')}{gpt_cur} X4{r.get('gpt_x4', '?')}{gpt_x4}")
            log_verification(f"  Claude: 当前{r.get('claude_current', '?')}{claude_cur} X4{r.get('claude_x4', '?')}{claude_x4}")
            log_verification(f"  L1:     当前{r.get('l1_current', '?')}{l1_cur} X4{r.get('l1_x4', '?')}{l1_x4}")

        # v2.5: 写入累计统计 (价格准确率 + L1确认率)
        stats = data.get("stats", {})
        log_verification("-" * 60)
        log_verification(f"累计统计 (已验证{stats.get('verified_total', 0)}条):")
        log_verification("")
        log_verification("价格准确率 (预判vs实际涨跌):")
        log_verification(f"  GPT-4o: {stats.get('gpt_current_accuracy', 0)*100:.1f}%")
        log_verification(f"  Claude: {stats.get('claude_current_accuracy', 0)*100:.1f}%")
        log_verification("")
        log_verification("L1确认率 (预判后2根K线L1确认):")
        log_verification(f"  GPT-4o: {stats.get('gpt_l1_confirm_rate', 0)*100:.1f}% ({stats.get('gpt_l1_confirm_count', 0)}条)")
        log_verification(f"  Claude: {stats.get('claude_l1_confirm_rate', 0)*100:.1f}% ({stats.get('claude_l1_confirm_count', 0)}条)")
        log_verification("")
        log_verification("市场状态分布:")
        log_verification(f"  单边行情: {stats.get('market_strong_trend', 0)}次")
        log_verification(f"  正常趋势: {stats.get('market_normal_trend', 0)}次 (Vision领先)")
        log_verification(f"  死水震荡: {stats.get('market_ranging', 0)}次")
        log_verification("=" * 60)

    if verified_count > 0:
        print(f"[Vision] 本轮验证: {verified_count}条记录")


def update_accuracy_stats(data: Dict):
    """v2.5: 更新准确率统计 - 价格准确率 + L1确认率"""
    comparisons = data.get("comparisons", [])
    verified = [c for c in comparisons if c.get("verified")]

    if not verified:
        return

    total_verified = len(verified)

    # ===== 价格准确率 (原有逻辑) =====
    # GPT-4o 价格准确率
    gpt_current_records = [c for c in verified if c.get("gpt_current_correct") is not None]
    gpt_x4_records = [c for c in verified if c.get("gpt_x4_correct") is not None]
    gpt_current_correct = sum(1 for c in gpt_current_records if c.get("gpt_current_correct"))
    gpt_x4_correct = sum(1 for c in gpt_x4_records if c.get("gpt_x4_correct"))

    # Claude 价格准确率
    claude_current_records = [c for c in verified if c.get("claude_current_correct") is not None]
    claude_x4_records = [c for c in verified if c.get("claude_x4_correct") is not None]
    claude_current_correct = sum(1 for c in claude_current_records if c.get("claude_current_correct"))
    claude_x4_correct = sum(1 for c in claude_x4_records if c.get("claude_x4_correct"))

    # Vision准确率 (选中的结果，向后兼容)
    vision_current_correct = sum(1 for c in verified if c.get("vision_current_correct"))
    vision_x4_correct = sum(1 for c in verified if c.get("vision_x4_correct"))

    # L1准确率
    l1_current_correct = sum(1 for c in verified if c.get("l1_current_correct"))
    l1_x4_correct = sum(1 for c in verified if c.get("l1_x4_correct"))

    # ===== v2.6: L1确认率 - 2根和3根分别统计 =====
    # 2根K线确认率
    gpt_l1_2bar = [c for c in verified if c.get("gpt_l1_confirmed_2bar") is not None]
    gpt_l1_2bar_confirmed = sum(1 for c in gpt_l1_2bar if c.get("gpt_l1_confirmed_2bar"))
    claude_l1_2bar = [c for c in verified if c.get("claude_l1_confirmed_2bar") is not None]
    claude_l1_2bar_confirmed = sum(1 for c in claude_l1_2bar if c.get("claude_l1_confirmed_2bar"))

    # 3根K线确认率
    gpt_l1_3bar = [c for c in verified if c.get("gpt_l1_confirmed_3bar") is not None]
    gpt_l1_3bar_confirmed = sum(1 for c in gpt_l1_3bar if c.get("gpt_l1_confirmed_3bar"))
    claude_l1_3bar = [c for c in verified if c.get("claude_l1_confirmed_3bar") is not None]
    claude_l1_3bar_confirmed = sum(1 for c in claude_l1_3bar if c.get("claude_l1_confirmed_3bar"))

    # 向后兼容 (使用2bar数据)
    gpt_l1_records = gpt_l1_2bar
    gpt_l1_confirmed_count = gpt_l1_2bar_confirmed
    claude_l1_records = claude_l1_2bar
    claude_l1_confirmed_count = claude_l1_2bar_confirmed

    # 市场状态统计
    strong_trend_count = sum(1 for c in verified if c.get("market_state") == "STRONG_TREND")
    ranging_count = sum(1 for c in verified if c.get("market_state") == "RANGING")
    normal_trend_count = sum(1 for c in verified if c.get("market_state") == "NORMAL_TREND")

    data["stats"]["verified_total"] = total_verified

    # 价格准确率
    data["stats"]["gpt_current_accuracy"] = round(gpt_current_correct / len(gpt_current_records), 3) if gpt_current_records else 0
    data["stats"]["gpt_x4_accuracy"] = round(gpt_x4_correct / len(gpt_x4_records), 3) if gpt_x4_records else 0
    data["stats"]["gpt_verified_count"] = len(gpt_current_records)

    data["stats"]["claude_current_accuracy"] = round(claude_current_correct / len(claude_current_records), 3) if claude_current_records else 0
    data["stats"]["claude_x4_accuracy"] = round(claude_x4_correct / len(claude_x4_records), 3) if claude_x4_records else 0
    data["stats"]["claude_verified_count"] = len(claude_current_records)

    # 向后兼容
    data["stats"]["vision_current_accuracy"] = round(vision_current_correct / total_verified, 3) if total_verified > 0 else 0
    data["stats"]["vision_x4_accuracy"] = round(vision_x4_correct / total_verified, 3) if total_verified > 0 else 0
    data["stats"]["l1_current_accuracy"] = round(l1_current_correct / total_verified, 3) if total_verified > 0 else 0
    data["stats"]["l1_x4_accuracy"] = round(l1_x4_correct / total_verified, 3) if total_verified > 0 else 0

    # v2.6: L1确认率 - 2根和3根分别统计
    # 2根K线确认率
    data["stats"]["gpt_l1_2bar_rate"] = round(gpt_l1_2bar_confirmed / len(gpt_l1_2bar), 3) if gpt_l1_2bar else 0
    data["stats"]["claude_l1_2bar_rate"] = round(claude_l1_2bar_confirmed / len(claude_l1_2bar), 3) if claude_l1_2bar else 0
    data["stats"]["gpt_l1_2bar_count"] = len(gpt_l1_2bar)
    data["stats"]["claude_l1_2bar_count"] = len(claude_l1_2bar)

    # 3根K线确认率
    data["stats"]["gpt_l1_3bar_rate"] = round(gpt_l1_3bar_confirmed / len(gpt_l1_3bar), 3) if gpt_l1_3bar else 0
    data["stats"]["claude_l1_3bar_rate"] = round(claude_l1_3bar_confirmed / len(claude_l1_3bar), 3) if claude_l1_3bar else 0
    data["stats"]["gpt_l1_3bar_count"] = len(gpt_l1_3bar)
    data["stats"]["claude_l1_3bar_count"] = len(claude_l1_3bar)

    # 向后兼容
    data["stats"]["gpt_l1_confirm_rate"] = data["stats"]["gpt_l1_2bar_rate"]
    data["stats"]["claude_l1_confirm_rate"] = data["stats"]["claude_l1_2bar_rate"]
    data["stats"]["gpt_l1_confirm_count"] = data["stats"]["gpt_l1_2bar_count"]
    data["stats"]["claude_l1_confirm_count"] = data["stats"]["claude_l1_2bar_count"]

    # v2.5: 市场状态分布
    data["stats"]["market_strong_trend"] = strong_trend_count
    data["stats"]["market_ranging"] = ranging_count
    data["stats"]["market_normal_trend"] = normal_trend_count


# ============================================================================
# 分析逻辑
# ============================================================================

def should_analyze(symbol: str, cfg: dict, force: bool = False) -> bool:
    """判断是否应该分析该品种"""
    # 强制模式跳过所有检查
    if force:
        return True

    # 美股只在开盘时分析
    if cfg["type"] == "stock" and RUN_CONFIG["stock_only_market_hours"]:
        if not is_us_market_open():
            return False

    # v2.8: 动态冷却时间 (跟随品种周期)
    _sym_tf = read_symbol_timeframe(symbol, default=DEFAULT_L1_TIMEFRAME)
    _sym_params = get_timeframe_params(_sym_tf, is_crypto=is_crypto_symbol(symbol))
    _cooldown_min = _sym_params["vision_cooldown_minutes"]
    last_time = get_last_analysis_time(symbol)
    if last_time:
        cooldown = timedelta(minutes=_cooldown_min)
        if datetime.now() - last_time < cooldown:
            return False

    return True


# ============================================================================
# v3.1: 形态检测 — 独立于趋势检测的第二阶段
# ============================================================================

# 形态检测冷却记录 {symbol: last_pattern_analysis_timestamp}
_pattern_last_analysis: Dict[str, float] = {}
_pattern_fail_streak: Dict[str, int] = {}
_pattern_circuit_until: Dict[str, float] = {}


def _record_pattern_failure(symbol: str):
    streak = int(_pattern_fail_streak.get(symbol, 0)) + 1
    _pattern_fail_streak[symbol] = streak
    if streak >= PATTERN_CIRCUIT_FAIL_THRESHOLD:
        until_ts = time.time() + PATTERN_CIRCUIT_BREAK_MINUTES * 60
        _pattern_circuit_until[symbol] = until_ts
        _pattern_fail_streak[symbol] = 0
        print(f"[Vision v3.4] {symbol} 连续失败{PATTERN_CIRCUIT_FAIL_THRESHOLD}次，熔断{PATTERN_CIRCUIT_BREAK_MINUTES}分钟")


def _record_pattern_success(symbol: str):
    _pattern_fail_streak[symbol] = 0
    _pattern_circuit_until.pop(symbol, None)

def fetch_pattern_bars(symbol: str, cfg: dict) -> Optional[List[Dict]]:
    """
    v3.1: 获取形态分析用K线 (50根当前周期)
    复用fetch_bars逻辑但固定50根
    """
    yf_symbol = cfg["yf_symbol"]
    l1_timeframe = cfg["l1_timeframe"]

    interval, period, needs_resample, resample_factor = get_yfinance_params(l1_timeframe, is_x4=False)

    hist = fetch_yfinance_history(yf_symbol, period=period, interval=interval)
    if hist is None or hist.empty:
        print(f"[Vision v3.1] {symbol} 形态分析数据为空")
        return None

    # 重采样到当前周期(如需要)
    if needs_resample and resample_factor:
        hist = resample_bars(hist, resample_factor)

    # 固定50根
    bars_count = PATTERN_CHART_CONFIG.get("bars", 50)
    bars = []
    for idx, row in hist.tail(bars_count).iterrows():
        close_val = float(row["Close"]) if not pd.isna(row["Close"]) else 0
        if close_val <= 0:
            continue
        bars.append({
            "open": float(row["Open"]) if not pd.isna(row["Open"]) else close_val,
            "high": float(row["High"]) if not pd.isna(row["High"]) else close_val,
            "low": float(row["Low"]) if not pd.isna(row["Low"]) else close_val,
            "close": close_val,
            "volume": float(row["Volume"]) if not pd.isna(row.get("Volume", 0)) else 0,
        })

    if len(bars) < 20:
        print(f"[Vision v3.1] {symbol} 形态分析K线不足: {len(bars)}根")
        return None

    print(f"[Vision v3.1] {symbol} 形态分析: {len(bars)}根K线")
    return bars


def analyze_patterns(symbol: str, cfg: dict) -> Optional[Dict]:
    """
    v3.3: 形态检测主函数
    独立于趋势检测，有自己的冷却周期
    Returns: {symbol, pattern, stage, confidence, volume_confirmed, reason, overall_structure, position}
    """
    global _pattern_last_analysis

    # 熔断检查
    now = time.time()
    circuit_until = float(_pattern_circuit_until.get(symbol, 0))
    if circuit_until > now:
        remain_min = int((circuit_until - now) / 60)
        print(f"[Vision v3.4] {symbol} 形态识别熔断中 (剩余{remain_min}分钟)")
        return None

    # 冷却检查
    last_time = _pattern_last_analysis.get(symbol, 0)
    cooldown_seconds = PATTERN_COOLDOWN_MINUTES * 60
    if now - last_time < cooldown_seconds:
        remaining = int((cooldown_seconds - (now - last_time)) / 60)
        print(f"[Vision v3.1] {symbol} 形态检测冷却中 (剩余{remaining}分钟)")
        return None

    # 美股开盘检查
    if cfg.get("type") == "stock" and RUN_CONFIG.get("stock_only_market_hours"):
        if not is_us_market_open():
            return None

    print(f"\n[Vision v3.1] === 形态检测 {symbol} ===")
    start_time = time.time()

    # 解析周期标签 (必须在generate_clean_chart之前, 否则_current_label未定义)
    _sym_tf = read_symbol_timeframe(symbol, default=DEFAULT_L1_TIMEFRAME)
    _sym_params = get_timeframe_params(_sym_tf, is_crypto=(cfg.get("type") == "crypto"))
    _current_label = _sym_params["current_label"]

    # 1. 获取50根K线
    bars = fetch_pattern_bars(symbol, cfg)
    if not bars:
        return None

    # 2. 生成形态图 (GCC-0046: 切换到TV风格干净K线图)
    chart_base64 = generate_clean_chart(bars, f"{symbol} - Pattern Analysis ({len(bars)} bars)", timeframe=_current_label)
    if not chart_base64:
        print(f"[Vision v3.1] {symbol} 形态图生成失败")
        return None

    # 3. GCC-0194: 使用Brooks RADAR_PROMPT (统一单次GPT调用)
    from brooks_vision import RADAR_PROMPT
    pattern_prompt = RADAR_PROMPT

    print(f"[Vision v3.5] {symbol} 调用GPT Brooks形态识别 ({_current_label})...")
    result = call_chatgpt_vision(chart_base64, pattern_prompt, max_retries=2, expected_mode="trend", symbol=symbol)

    latency_ms = int((time.time() - start_time) * 1000)

    if not result:
        print(f"[Vision v3.5] {symbol} GPT Brooks形态识别失败 ({latency_ms}ms)")
        _pattern_last_analysis[symbol] = now
        _record_pattern_failure(symbol)
        return None

    # 4. GCC-0194: RADAR_PROMPT输出 → pattern_latest.json格式
    normalized = _parse_radar_to_pattern(result)
    if not normalized:
        print(f"[Vision v3.5] {symbol} RADAR结果解析失败，丢弃")
        _pattern_last_analysis[symbol] = now
        _record_pattern_failure(symbol)
        return None

    pattern = normalized["pattern"]
    confidence = normalized["confidence"]
    stage = normalized["stage"]
    volume_confirmed = normalized["volume_confirmed"]
    reason = normalized["reason"]
    overall_structure = normalized.get("overall_structure", "UNKNOWN")
    position = normalized.get("position", "MID")

    # GCC-0194: 新增字段
    brooks_pattern = normalized.get("brooks_pattern", "NONE")
    direction = normalized.get("direction", "SIDE")
    stoploss = normalized.get("stoploss", 0.0)

    # 记录日志
    log_msg = f"[Pattern] {symbol}: {pattern} dir={direction} conf={confidence:.2f} stage={stage} brooks={brooks_pattern} struct={overall_structure}/{position}"
    print(f"[Vision v3.5] {log_msg}")

    # 写入vision_analysis.log
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(UNIFIED_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {log_msg}\n")
    except Exception:
        pass

    # 5. 保存到 pattern_latest.json (GCC-0194: 新增direction/stoploss/brooks_pattern)
    pattern_data = {
        "pattern": pattern,
        "stage": stage,
        "confidence": confidence,
        "volume_confirmed": volume_confirmed,
        "reason": reason,
        "overall_structure": overall_structure,
        "position": position,
        "direction": direction,              # GCC-0194: UP/DOWN/SIDE
        "stoploss": stoploss,                # GCC-0194: 止损价
        "brooks_pattern": brooks_pattern,    # GCC-0194: Brooks形态名
        "timeframe_minutes": int(_sym_tf),
        "timeframe_label": _current_label,
        "analysis_interval_minutes": int(RUN_CONFIG.get("analysis_interval_minutes", 30)),
        "timestamp": datetime.now().isoformat(),
        "latency_ms": latency_ms,
    }

    try:
        all_patterns = load_json_file(PATTERN_LATEST_FILE)
        if not isinstance(all_patterns, dict):
            all_patterns = {}
        all_patterns[symbol] = pattern_data
        save_json_file(PATTERN_LATEST_FILE, all_patterns)
        print(f"[Vision v3.5] {symbol} pattern_latest.json 已更新")
    except Exception as e:
        print(f"[Vision v3.5] {symbol} pattern_latest.json 保存失败: {e}")

    # 提取baseline价格并写入baseline_state.json (用bars_ago从OHLCV取精确价格)
    try:
        _bl_buy = result.get("baseline_buy", {})
        _bl_sell = result.get("baseline_sell", {})
        if _bl_buy or _bl_sell:
            from baseline_vision_task import _load_state as _bl_load, _save_state as _bl_save
            _bl_state = _bl_load()
            _bl_entry = _bl_state.get(symbol, {})
            _bl_buy_price = _bl_entry.get("buy_price")
            _bl_sell_price = _bl_entry.get("sell_price")
            _bl_buy_ago = _bl_entry.get("buy_bars_ago")
            _bl_sell_ago = _bl_entry.get("sell_bars_ago")
            # 用bars_ago从bars取精确收盘价 + 颜色校验
            _bl_buy_found = _bl_entry.get("buy_found", False)
            _bl_sell_found = _bl_entry.get("sell_found", False)
            if _bl_buy.get("found") and _bl_buy.get("bars_ago") is not None:
                _bi = len(bars) - 1 - int(_bl_buy["bars_ago"])
                if 0 <= _bi < len(bars):
                    _bar = bars[_bi]
                    if _bar["close"] > _bar["open"]:  # 阳线校验
                        _bl_buy_price = _bar["close"]
                        _bl_buy_ago = _bl_buy["bars_ago"]
                        _bl_buy_found = True
                    else:
                        print(f"[Vision v3.5] {symbol} buy bars_ago={_bl_buy['bars_ago']} 不是阳线, 丢弃")
            if _bl_sell.get("found") and _bl_sell.get("bars_ago") is not None:
                _si = len(bars) - 1 - int(_bl_sell["bars_ago"])
                if 0 <= _si < len(bars):
                    _bar = bars[_si]
                    if _bar["close"] < _bar["open"]:  # 阴线校验
                        _bl_sell_price = _bar["close"]
                        _bl_sell_ago = _bl_sell["bars_ago"]
                        _bl_sell_found = True
                    else:
                        print(f"[Vision v3.5] {symbol} sell bars_ago={_bl_sell['bars_ago']} 不是阴线, 丢弃")
            # 合理性校验: buy是低位, sell是高位 → buy_price < sell_price
            if _bl_buy_found and _bl_sell_found and _bl_buy_price is not None and _bl_sell_price is not None:
                if _bl_buy_price >= _bl_sell_price:
                    print(f"[Vision v3.5] {symbol} buy={_bl_buy_price:.2f} >= sell={_bl_sell_price:.2f} 反转异常, 丢弃双基准")
                    _bl_buy_price = _bl_entry.get("buy_price")
                    _bl_sell_price = _bl_entry.get("sell_price")
                    _bl_buy_found = _bl_entry.get("buy_found", False)
                    _bl_sell_found = _bl_entry.get("sell_found", False)
                    _bl_buy_ago = _bl_entry.get("buy_bars_ago")
                    _bl_sell_ago = _bl_entry.get("sell_bars_ago")
            _bl_entry.update({
                "buy_price": _bl_buy_price,
                "sell_price": _bl_sell_price,
                "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "source": "vision_radar",
                "buy_bars_ago": _bl_buy_ago,
                "sell_bars_ago": _bl_sell_ago,
                "buy_found": _bl_buy_found,
                "sell_found": _bl_sell_found,
            })
            _bl_state[symbol] = _bl_entry
            _bl_save(_bl_state)
            print(f"[Vision v3.5] {symbol} baseline更新: buy={_bl_buy_price} sell={_bl_sell_price}")
    except Exception as _e_bl:
        print(f"[Vision v3.5] {symbol} baseline写入失败: {_e_bl}")

    # 更新冷却
    _pattern_last_analysis[symbol] = now
    _record_pattern_success(symbol)

    print(f"[Vision v3.5] {symbol} 形态检测完成 ({latency_ms}ms)")
    return {
        "symbol": symbol,
        **pattern_data,
    }


def analyze_symbol(symbol: str, cfg: dict) -> Optional[Dict]:
    """
    分析单个品种
    Returns: {symbol, current, x4, comparison}
    """
    print(f"\n[Vision] === 分析 {symbol} ===")
    start_time = time.time()

    # 1. 获取当前周期K线
    current_bars = fetch_bars(symbol, cfg, is_x4=False)
    if not current_bars:
        print(f"[Vision] {symbol} 当前周期数据获取失败")
        return None

    # v2.4: X4周期不再调用Vision API，直接用L1算法 (L1准确率66.1% > GPT 58.8%)
    # 只获取当前周期K线，不再获取X4

    # 2. v3.0: 生成极简趋势图 (实体顶底两条线)
    print(f"[Vision] {symbol} 生成极简趋势图...")
    current_chart = generate_simple_trend_chart(current_bars, f"{symbol} - {len(current_bars)} bars")

    if not current_chart:
        print(f"[Vision] {symbol} 图表生成失败")
        return None

    # v2.8: 动态标签 — 根据品种当前周期计算
    _sym_tf = read_symbol_timeframe(symbol, default=DEFAULT_L1_TIMEFRAME)
    _sym_params = get_timeframe_params(_sym_tf, is_crypto=(cfg.get("type") == "crypto"))
    _current_label = _sym_params["current_label"]
    _x4_label = _sym_params["x4_label"]

    # 3. Vision分析 - 只分析当前周期
    print(f"[Vision v2.8] {symbol} 调用Vision API - 仅当前周期 ({VISION_MODEL}, {_current_label})...")

    # 设置分析上下文 (供日志使用)
    _current_analysis_context["symbol"] = symbol
    _current_analysis_context["dual_results"] = {"current": {}, "x4": {}}  # 重置

    _current_analysis_context["period"] = "current"
    current_result = call_vision_api(current_chart, period="current",
                                     current_label=_current_label, x4_label=_x4_label,
                                     symbol=symbol)

    # v2.4: X4周期直接用L1算法，不调用Vision API
    l1_decision = read_l1_decision(symbol)
    x4_result = None
    if l1_decision:
        l1_x4_dir = l1_decision.get("trend_x4", "SIDE").upper()
        x4_result = {
            "regime": "TRENDING" if l1_x4_dir in ("UP", "DOWN") else "RANGING",
            "direction": l1_x4_dir,
            "confidence": 0.66,  # L1算法历史准确率
            "reason": "v2.4: X4直接用L1算法 (准确率66.1%)",
            "source": "L1_ALGORITHM"
        }

    latency_ms = int((time.time() - start_time) * 1000)

    # 4. 打印结果
    if current_result:
        print(f"[Vision] {symbol} 当前周期: {current_result['regime']} {current_result['direction']} (conf={current_result['confidence']:.2f})")
    else:
        print(f"[Vision] {symbol} 当前周期分析失败")

    if x4_result:
        print(f"[Vision v2.4] {symbol} X4周期: 使用L1算法 → {x4_result['direction']}")
    else:
        print(f"[Vision] {symbol} X4周期: L1决策未找到")

    # 5. 保存分析记录
    save_analysis_record(symbol, cfg["l1_timeframe"], current_result, x4_result, latency_ms)

    # 5.1 v2.0: 保存最新结果供主程序读取
    if current_result or x4_result:
        save_latest_result(symbol, current_result, x4_result)

    # 5.2 v3.678: 每次Vision分析都写入Vision Cache (不等4H主循环)
    if current_result and current_bars:
        try:
            from modules.key001_vision_cache import (
                VisionCache, VisionSnapshot,
                compute_price_signature, compute_volume_signature, compute_structure_points,
            )
            _vc_dir = str(current_result.get("direction", "SIDE")).upper()
            _vc_bias = {"UP": "BUY", "DOWN": "SELL"}.get(_vc_dir, "HOLD")
            _vc_n_pat = str(current_result.get("n_pattern", "NONE")).upper()
            _vc_pattern = _vc_n_pat if _vc_n_pat != "NONE" else str(current_result.get("regime", "UNKNOWN")).upper()
            _vc_closes = [float(b["close"]) for b in current_bars]
            _vc_vols = [float(b.get("volume", 0)) for b in current_bars]
            _vc_snap = VisionSnapshot(
                snapshot_id=f"{symbol}_{_sym_tf}_{int(time.time())}",
                ts_iso=datetime.now(timezone.utc).isoformat(),
                symbol=symbol,
                timeframe=str(_sym_tf),
                price_at_snapshot=float(current_bars[-1]["close"]),
                pattern=_vc_pattern,
                bias=_vc_bias,
                confidence=float(current_result.get("confidence", 0.5)),
                key_features=[f"red_{current_result.get('red_line','?')}", f"blue_{current_result.get('blue_line','?')}"],
                price_signature=compute_price_signature(_vc_closes),
                volume_signature=compute_volume_signature(_vc_vols),
                structure_points=compute_structure_points(_vc_closes),
            )
            VisionCache().save(_vc_snap)
            print(f"[Vision][VCACHE] {symbol} snapshot saved: {_vc_pattern}/{_vc_bias} conf={_vc_snap.confidence:.0%} sigs={len(_vc_snap.price_signature)}")
        except Exception as _vce:
            print(f"[Vision][VCACHE] {symbol} save failed: {_vce}")

    # 6. v2.4: l1_decision已在前面读取，直接使用
    if l1_decision:
        print(f"[Vision] {symbol} L1决策: current={l1_decision['current_trend']} x4={l1_decision['trend_x4']} (X4直接用L1)")

        # 获取当前价格(从最后一根K线)
        price = current_bars[-1]["close"] if current_bars else 0

        comparison = compare_vision_vs_l1(current_result, x4_result, l1_decision, symbol, price, cfg["l1_timeframe"])
        save_comparison_record(comparison)

        # 打印对比结果
        current_match = "Y" if comparison["current_match"] else "N" if comparison["current_match"] is False else "?"
        x4_match = "Y" if comparison["x4_match"] else "N" if comparison["x4_match"] is False else "?"
        print(f"[Vision] {symbol} match: current={current_match} x4={x4_match}")

        # 7.1 保存三方预测日志(GPT-4o, Claude, L1) 用于12小时后验证
        save_prediction_log(symbol, current_result, x4_result, l1_decision, price)
    else:
        print(f"[Vision] {symbol} L1决策未找到(可能主程序未刷新)")

    # 8. 更新最后分析时间
    update_last_analysis_time(symbol)

    print(f"[Vision] {symbol} 完成 (耗时{latency_ms}ms)")

    return {
        "symbol": symbol,
        "current": current_result,
        "x4": x4_result,
        "latency_ms": latency_ms,
    }


def analyze_all_symbols(force: bool = False):
    """分析所有品种"""
    print(f"\n{'='*60}")
    print(f"[Vision] 开始分析 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if force:
        print(f"[Vision] *** 强制模式: 忽略冷却时间 ***")
    print(f"{'='*60}")

    analyzed = 0
    skipped = 0

    # 动态获取配置 (从主程序读取L1周期)
    symbols_config = get_symbols_config()

    for symbol, cfg in symbols_config.items():
        if should_analyze(symbol, cfg, force=force):
            result = analyze_symbol(symbol, cfg)
            if result:
                analyzed += 1
            # 品种间间隔,避免API限流
            time.sleep(2)
        else:
            skipped += 1

    print(f"\n[Vision] 本轮完成: 分析{analyzed}个, 跳过{skipped}个")

    # v3.1: 形态检测 (独立冷却, 不受趋势冷却影响)
    pattern_count = 0
    print(f"\n[Vision v3.1] --- 形态检测阶段 ---")
    for symbol, cfg in symbols_config.items():
        try:
            p_result = analyze_patterns(symbol, cfg)
            if p_result and p_result.get("pattern", "NONE") != "NONE":
                pattern_count += 1
            time.sleep(2)
        except Exception as e:
            print(f"[Vision v3.1] {symbol} 形态检测异常: {e}")
    print(f"[Vision v3.1] 形态检测完成: {pattern_count}个形态发现")


def print_stats():
    """v2.1: 打印统计信息 - 分别显示GPT-4o和Claude准确率"""
    data = load_json_file(COMPARISON_FILE)
    stats = data.get("stats", {})
    comparisons = data.get("comparisons", [])

    # v2.1: 统计待验证的V2.1记录
    v21_records = [c for c in comparisons if c.get("gpt4o_current_direction")]
    v21_pending = [c for c in v21_records if not c.get("verified")]
    v21_verified = len(v21_records) - len(v21_pending)

    # v2.9: Claude已移除，仅显示GPT-4o和L1
    print(f"\n{'='*60}")
    print("[Vision v2.9] Accuracy Stats (GPT-4o vs L1)")
    print(f"{'='*60}")
    print(f"  Total comparisons: {stats.get('total', 0)}")
    print(f"  Verified count:    {stats.get('verified_total', 0)}")
    print(f"")

    # v2.1: 显示V2.1记录状态
    if v21_records:
        print(f"  --- V2.1 Records Status ---")
        print(f"  V2.1 records: {len(v21_records)} | Verified: {v21_verified} | Pending: {len(v21_pending)}")
        if v21_pending and v21_verified == 0:
            first_ts = v21_records[0].get("timestamp", "")[:16]
            first_tf = v21_records[0].get("l1_timeframe", 240)
            print(f"  [Pending] First V2.1: {first_ts} (verify after {first_tf}min)")
        print(f"")

    print(f"  --- Accuracy Comparison (verified after 2 bars) ---")
    print(f"  {'Model':<12} {'Current':>10} {'X4':>10} {'Count':>8}")
    print(f"  {'-'*42}")

    gpt_verified = stats.get('gpt_verified_count', 0)

    if gpt_verified > 0:
        print(f"  {'GPT-4o':<12} {stats.get('gpt_current_accuracy', 0)*100:>9.1f}% {stats.get('gpt_x4_accuracy', 0)*100:>9.1f}% {gpt_verified:>8}")
    else:
        print(f"  {'GPT-4o':<12} {'pending':>10} {'pending':>10} {0:>8}")

    print(f"  {'L1-Tech':<12} {stats.get('l1_current_accuracy', 0)*100:>9.1f}% {stats.get('l1_x4_accuracy', 0)*100:>9.1f}% {stats.get('verified_total', 0):>8}")
    print(f"  {'-'*42}")
    print(f"")

    # v2.6: L1确认率 - 2根和3根对比，找出最佳延迟
    print(f"  --- L1 Confirmation Rate (Vision→L1) ---")
    print(f"  {'Model':<12} {'@2bars':>10} {'@3bars':>10} {'Best':>8}")
    print(f"  {'-'*42}")
    gpt_2bar = stats.get('gpt_l1_2bar_rate', 0)
    gpt_3bar = stats.get('gpt_l1_3bar_rate', 0)
    gpt_2bar_n = stats.get('gpt_l1_2bar_count', 0)
    gpt_3bar_n = stats.get('gpt_l1_3bar_count', 0)

    if gpt_2bar_n > 0 or gpt_3bar_n > 0:
        gpt_best = "3bar" if gpt_3bar > gpt_2bar else "2bar"
        print(f"  {'GPT→L1':<12} {gpt_2bar*100:>9.1f}% {gpt_3bar*100:>9.1f}% {gpt_best:>8}")
    else:
        print(f"  {'GPT→L1':<12} {'pending':>10} {'pending':>10} {'-':>8}")

    print(f"  {'-'*42}")
    print(f"  (n: 2bar={gpt_2bar_n}, 3bar={gpt_3bar_n})")
    print(f"")

    print(f"  --- Layer1: Same Bar Comparison ---")
    print(f"  {'Pair':<12} {'Current':>10} {'X4':>10}")
    print(f"  {'-'*34}")
    print(f"  {'GPT=L1':<12} {stats.get('layer1_gpt_l1_cur', 0)*100:>9.1f}% {stats.get('layer1_gpt_l1_x4', 0)*100:>9.1f}%")
    print(f"")
    print(f"  --- Layer2: Cross Bar Consistency ---")
    print(f"  {'Model':<12} {'Current':>10} {'X4':>10}")
    print(f"  {'-'*34}")
    print(f"  {'GPT-4o':<12} {stats.get('layer2_gpt_consistent_cur', 0)*100:>9.1f}% {stats.get('layer2_gpt_consistent_x4', 0)*100:>9.1f}%")
    print(f"")
    print(f"  Last updated: {stats.get('last_updated', 'N/A')}")


# ============================================================================
# 主程序
# ============================================================================

def main(force_first_run: bool = False):
    """主入口"""
    print("="*60)
    print("  Vision Analyzer - AI视觉趋势分析")
    print("  道氏理论(x4定方向) + N字结构(当前周期找入场)")
    print("="*60)

    # 检查API Key
    if not OPENAI_API_KEY:
        print("\n[ERROR] OPENAI_API_KEY未配置!")
        print("请设置环境变量: export OPENAI_API_KEY=sk-...")
        return

    print(f"\n[Vision] API Key: {OPENAI_API_KEY[:8]}...{OPENAI_API_KEY[-4:]}")
    print(f"[Vision] 品种数量: {len(SYMBOLS_BASE_CONFIG)}")
    print(f"[Vision] 分析间隔: {RUN_CONFIG['analysis_interval_minutes']}分钟")
    print(f"[Vision] 品种冷却: {RUN_CONFIG['per_symbol_cooldown_minutes']}分钟")
    if force_first_run:
        print(f"[Vision] *** 强制模式: 首轮忽略冷却 ***")

    # 显示当前周期配置
    symbols_config = get_symbols_config()
    print(f"[Vision] 周期配置:")
    for sym, cfg in symbols_config.items():
        print(f"         {sym}: {cfg['l1_timeframe']}分钟 ({cfg['type']})")

    # 确保状态目录
    ensure_state_dir()

    # 主循环
    print(f"\n[Vision] 进入主循环 (Ctrl+C退出)...")

    first_run = True
    while True:
        try:
            # 首轮强制分析(如果指定了--force)
            force = force_first_run and first_run
            analyze_all_symbols(force=force)
            first_run = False

            # 验证12小时前的预测
            print(f"\n[Vision] 检查待验证记录...")
            verify_predictions()

            cleanup_old_records()
            print_stats()

            # 等待下一轮
            interval = RUN_CONFIG["analysis_interval_minutes"] * 60
            print(f"\n[Vision] 等待{RUN_CONFIG['analysis_interval_minutes']}分钟后下一轮...")
            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[Vision] 收到退出信号,正在关闭...")
            break
        except Exception as e:
            print(f"\n[Vision] 主循环异常: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)  # 异常后等待1分钟重试


def run_once():
    """单次运行(测试用)"""
    print("[Vision] 单次运行模式")

    if not OPENAI_API_KEY:
        print("[ERROR] OPENAI_API_KEY未配置!")
        return

    ensure_state_dir()

    # 只分析第一个品种测试
    symbols_config = get_symbols_config()
    symbol = list(symbols_config.keys())[0]
    cfg = symbols_config[symbol]
    print(f"[Vision] {symbol} L1周期: {cfg['l1_timeframe']}分钟")

    print(f"\n[Vision] 测试品种: {symbol}")
    result = analyze_symbol(symbol, cfg)

    if result:
        print("\n[Vision] 测试成功!")
        print_stats()
    else:
        print("\n[Vision] 测试失败!")


def print_daily_report():
    """打印每日验证报告"""
    data = load_json_file(COMPARISON_FILE)
    comparisons = data.get("comparisons", [])
    verified = [c for c in comparisons if c.get("verified")]

    if not verified:
        print("[Vision] 没有已验证的记录")
        return

    print(f"\n{'='*80}")
    print("  Vision vs L1 验证报告")
    print(f"{'='*80}")

    # 按日期分组
    by_date = {}
    for c in verified:
        try:
            ts = datetime.fromisoformat(c["timestamp"])
            date_key = ts.strftime("%Y-%m-%d")
        except:
            continue

        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(c)

    # 打印每日统计
    print(f"\n{'日期':<12} {'验证数':>6} {'Vision当前':>10} {'Vision X4':>10} {'L1当前':>10} {'L1 X4':>10}")
    print("-" * 70)

    total_v_cur = 0
    total_v_x4 = 0
    total_l1_cur = 0
    total_l1_x4 = 0
    total_count = 0

    for date_key in sorted(by_date.keys(), reverse=True):
        records = by_date[date_key]
        count = len(records)
        v_cur = sum(1 for r in records if r.get("vision_current_correct"))
        v_x4 = sum(1 for r in records if r.get("vision_x4_correct"))
        l1_cur = sum(1 for r in records if r.get("l1_current_correct"))
        l1_x4 = sum(1 for r in records if r.get("l1_x4_correct"))

        total_v_cur += v_cur
        total_v_x4 += v_x4
        total_l1_cur += l1_cur
        total_l1_x4 += l1_x4
        total_count += count

        v_cur_pct = f"{v_cur}/{count}={v_cur/count*100:.0f}%"
        v_x4_pct = f"{v_x4}/{count}={v_x4/count*100:.0f}%"
        l1_cur_pct = f"{l1_cur}/{count}={l1_cur/count*100:.0f}%"
        l1_x4_pct = f"{l1_x4}/{count}={l1_x4/count*100:.0f}%"

        print(f"{date_key:<12} {count:>6} {v_cur_pct:>10} {v_x4_pct:>10} {l1_cur_pct:>10} {l1_x4_pct:>10}")

    # 总计
    print("-" * 70)
    if total_count > 0:
        print(f"{'总计':<12} {total_count:>6} {total_v_cur/total_count*100:>9.1f}% {total_v_x4/total_count*100:>9.1f}% {total_l1_cur/total_count*100:>9.1f}% {total_l1_x4/total_count*100:>9.1f}%")

    # 详细记录
    print(f"\n{'='*80}")
    print("  最近验证记录 (最新20条)")
    print(f"{'='*80}")
    print(f"{'时间':<20} {'品种':<10} {'涨跌':>8} {'实际':>6} {'V当前':>6} {'V_X4':>6} {'L1当前':>6} {'L1_X4':>6}")
    print("-" * 80)

    for c in sorted(verified, key=lambda x: x.get("timestamp", ""), reverse=True)[:20]:
        try:
            ts = datetime.fromisoformat(c["timestamp"]).strftime("%m-%d %H:%M")
        except:
            ts = "?"
        symbol = c.get("symbol", "?")[:8]
        pct = c.get("price_change_pct", 0)
        actual = c.get("actual_trend", "?")

        v_cur = "✓" if c.get("vision_current_correct") else "✗"
        v_x4 = "✓" if c.get("vision_x4_correct") else "✗"
        l1_cur = "✓" if c.get("l1_current_correct") else "✗"
        l1_x4 = "✓" if c.get("l1_x4_correct") else "✗"

        print(f"{ts:<20} {symbol:<10} {pct:>+7.2f}% {actual:>6} {v_cur:>6} {v_x4:>6} {l1_cur:>6} {l1_x4:>6}")

    print(f"\n{'='*80}")

    # 结论
    if total_count >= 10:
        v_better = (total_v_cur + total_v_x4) > (total_l1_cur + total_l1_x4)
        winner = "Vision" if v_better else "L1"
        print(f"\n  结论: 基于{total_count}条验证记录, {winner} 整体更准确")
        print(f"  - Vision: 当前{total_v_cur/total_count*100:.1f}% + X4{total_v_x4/total_count*100:.1f}%")
        print(f"  - L1:     当前{total_l1_cur/total_count*100:.1f}% + X4{total_l1_x4/total_count*100:.1f}%")
    else:
        print(f"\n  数据不足: 需要至少10条验证记录才能得出结论 (当前{total_count}条)")


def print_all_records():
    """打印所有验证记录的详细信息"""
    data = load_json_file(COMPARISON_FILE)
    comparisons = data.get("comparisons", [])
    verified = [c for c in comparisons if c.get("verified")]

    if not verified:
        print("[Vision] 没有已验证的记录")
        return

    print(f"\n{'='*100}")
    print("  所有验证记录")
    print(f"{'='*100}")

    for c in sorted(verified, key=lambda x: x.get("timestamp", ""), reverse=True):
        try:
            ts = datetime.fromisoformat(c["timestamp"]).strftime("%Y-%m-%d %H:%M")
            verify_ts = datetime.fromisoformat(c.get("verify_timestamp", "")).strftime("%Y-%m-%d %H:%M")
        except:
            ts = "?"
            verify_ts = "?"

        symbol = c.get("symbol", "?")
        price_at = c.get("price_at_analysis", 0)
        price_after = c.get("price_after_12h", 0)
        pct = c.get("price_change_pct", 0)
        actual = c.get("actual_trend", "?")

        print(f"\n--- {symbol} @ {ts} ---")
        print(f"  价格: {price_at:.2f} → {price_after:.2f} ({pct:+.2f}%) → 实际={actual}")
        print(f"  验证时间: {verify_ts}")

        v_cur_dir = c.get("vision_current_direction", "?")
        v_x4_dir = c.get("vision_x4_direction", "?")
        l1_cur_dir = c.get("l1_current_trend", "?")
        l1_x4_dir = c.get("l1_trend_x4", "?")

        v_cur = "✓" if c.get("vision_current_correct") else "✗"
        v_x4 = "✓" if c.get("vision_x4_correct") else "✗"
        l1_cur = "✓" if c.get("l1_current_correct") else "✗"
        l1_x4 = "✓" if c.get("l1_x4_correct") else "✗"

        print(f"  Vision: 当前={v_cur_dir}{v_cur}  X4={v_x4_dir}{v_x4}")
        print(f"  L1:     当前={l1_cur_dir}{l1_cur}  X4={l1_x4_dir}{l1_x4}")


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    elif "--force" in sys.argv:
        # 强制模式：启动时立即分析所有品种，然后进入正常循环
        main(force_first_run=True)
    elif "--report" in sys.argv:
        # 打印每日验证报告
        ensure_state_dir()
        print_daily_report()
    elif "--all" in sys.argv:
        # 打印所有验证记录
        ensure_state_dir()
        print_all_records()
    elif "--verify" in sys.argv:
        # 手动触发验证
        ensure_state_dir()
        print("[Vision] 手动触发验证...")
        verify_predictions()
        print_stats()
    else:
        main()
