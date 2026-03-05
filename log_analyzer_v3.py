#!/usr/bin/env python3
"""
Log Analyzer v3.14 - 增强版日志分析器
======================================

v3.14 更新 (2026-03-01):
- GCC-0174 S5d-S5e: CardBridge Phase门控检测 (card_phase_gate/card_acc_backfill)
- 检测组39新增2个子类: Phase1拦截+4H回填统计
- 日报Section 2a-22扩展: 因果匹配+Phase拦截品种分布

v3.13 更新 (2026-03-01):
- fix: GCC-0173 MACD检测代码缩进BUG修复 (在for循环外→永远不执行)
- GCC-0174知识卡活化: card_match/card_distill/card_error (CardBridge规则匹配)
- 检测组从38组扩展到39组 (+3 GCC-0174子类)
- 日报新增Section 2a-22: CardBridge规则匹配次数+品种分布+蒸馏快照
- KEY-009总结行扩展: 纳入管线A/B/C/D四管线数据

v3.12 更新 (2026-03-01):
- GCC-0173管线C审计: macd_acc/macd_gate (MACD背离准确率)
- 检测组从37组扩展到38组 (+2 GCC-0173子类)
- 日报新增Section 2a-21: 管线C MACD背离品种×类型准确率

v3.11 更新 (2026-03-01):
- GCC-0172管线B审计: bv_eval/bv_acc/bv_gate (BrooksVision形态准确率)
- 检测组从36组扩展到37组 (+3 GCC-0172子类)
- 日报新增Section 2a-20: 管线B形态准确率表+高低胜率品种

v3.10 更新 (2026-03-01):
- GCC-0171管线A审计: vf_eval/vf_acc/vf_promote/vf_demote/vf_3day_review
- 检测组从35组扩展到36组 (+5 GCC-0171子类)
- 日报新增Section 2a-19: 管线A Vision拦截准确率+品种Phase状态

v3.9 更新 (2026-02-19):
- FilterChain三道闸门统计: filter_chain_pass/block_vision/block_volume/block_micro
- 检测组从30组扩展到31组 (+5 filter_chain子类)
- 日报新增Section 2a-17: FilterChain通过率+按品种分布

v3.8 更新 (2026-02-15):
- Vision N字冲突检测: vision_n_conflict (Vision覆盖被N字门控阻止)
- 检测组从17组扩展到18组

v3.7 更新 (2026-02-15):
- KEY-002品种自适应检测: key002_diff/key002_same + 品种分布表
- N字门控实际拦截检测: n_gate_block_active (v3.660全品种ACTIVE)
- 检测组从15组扩展到17组

v3.5 更新 (2026-02-12):
- 共识度评分检测: consensus_low/consensus_high/consensus_contrary 3种模式
- 配合scan_engine v21.8 跨周期共识度评分(Phase1仅记录)

v3.3 更新 (2026-02-08):
- 外挂信号全生命周期追踪: PluginSignalTracker
- 追踪7+1外挂的触发/执行/阻止, 阻止原因分类统计 (含缠论BS)
- 数据源: scan_engine.log + server.log + signal_decisions.jsonl + plugin_profit_state.json
- 报告新增"外挂信号追踪"章节

v3.2 更新 (2026-02-07):
- 4方校准检测: 缠论规则/Vision/x4道氏/x4缠论准确率对比
- x4缠论胜出事件追踪: x4道氏vs缠论准确率竞争
- Vision覆盖L1: confidence>90%覆盖缠论基线
- 修复: dual_track数据路径从顶层改为stats子对象

v3.1 (2026-02-07):
- CNN覆盖融合、Vision准确率覆盖L1事件
- 双底双顶取消x4过滤: 检测跳过x4过滤日志
- 5方准确率报告: 读取human_dual_track.json统计

v3.0 功能:
1. LogicChecker - 主程序逻辑问题检测
   - big_trend vs current_trend 不一致
   - Vision覆盖逻辑错误
   - 道氏理论 HH/HL/LH/LL 判断异常
   - v3.1: CNN覆盖/Vision准确率覆盖追踪

2. RedundantTradeChecker - 多余交易检测
   - 同K线内反复交易 (震荡频繁买卖)
   - 亏损交易模式 (买高卖低)
   - 外挂重复触发
   - 无效交易 (小盈小亏)

3. RhythmAnalyzer - 买卖节奏分析
   - 底部买入质量 (pos_in_channel < 0.2)
   - 顶部卖出质量 (pos_in_channel > 0.8)
   - x4大周期方向确认

4. 改善建议系统
   - 每日改善建议
   - 每周改善建议
   - 每月改善建议

运行方式:
  每日分析:  python log_analyzer_v3.py --daily
  每周分析:  python log_analyzer_v3.py --weekly
  每月分析:  python log_analyzer_v3.py --monthly
  完整分析:  python log_analyzer_v3.py --full
  持续监控:  python log_analyzer_v3.py --watch [--interval 300]
"""

import os
import sys
import re
import json
import time
import logging
import io
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from zoneinfo import ZoneInfo
from pathlib import Path

# Windows控制台UTF-8编码支持
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 配置
# ============================================================

CONFIG = {
    "log_files": {
        "server": "logs/server.log",
        "scan_engine": "logs/price_scan_engine.log",
        "deepseek_arbiter": "logs/deepseek_arbiter.log",
        "macd_divergence": "logs/macd_divergence.log",
        "rob_hoffman": "logs/rob_hoffman_plugin.log",
        "l1_diagnosis": "logs/l1_module_diagnosis.log",
        "value_analysis": "logs/value_analysis.log",
    },
    "data_files": {
        "trade_history": "logs/trade_history.json",
        "cycle_history": "logs/cycle_history.json",
        "portfolio_snapshots": "logs/portfolio_snapshots.json",
        "state": "logs/state.json",
        "human_dual_track": "state/human_dual_track.json",
    },
    "output_dir": "logs/analyzer",
    "quality_scores_file": "logs/analyzer/quality_scores.json",
    "improvement_history_file": "logs/analyzer/improvement_history.json",
}

# 品种列表
ALL_SYMBOLS_CRYPTO = ["BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC"]
ALL_SYMBOLS_STOCK = ["TSLA", "COIN", "AMD", "RDDT", "RKLB", "NBIS", "CRWV", "HIMS", "OPEN", "ONDS", "PLTR"]
ALL_SYMBOLS = ALL_SYMBOLS_CRYPTO + ALL_SYMBOLS_STOCK

# 日志配置
os.makedirs(CONFIG["output_dir"], exist_ok=True)
import sys as _sys_log
_stream_handler = logging.StreamHandler(
    open(_sys_log.stderr.fileno(), mode='w', encoding='utf-8', closefd=False)
    if hasattr(_sys_log.stderr, 'fileno') else _sys_log.stderr
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(f"{CONFIG['output_dir']}/analyzer_v3.log", encoding='utf-8'),
        _stream_handler,
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

class TradeQuality(Enum):
    """交易质量等级"""
    EXCELLENT = "EXCELLENT"  # pos < 0.2 for BUY, > 0.8 for SELL
    GOOD = "GOOD"            # 0.2-0.4 for BUY, 0.6-0.8 for SELL
    NEUTRAL = "NEUTRAL"      # 0.4-0.6
    POOR = "POOR"            # 0.6-0.8 for BUY, 0.2-0.4 for SELL
    TERRIBLE = "TERRIBLE"    # > 0.8 for BUY, < 0.2 for SELL


@dataclass
class TradeRecord:
    """交易记录"""
    ts: str
    symbol: str
    action: str  # BUY or SELL
    price: float
    units: float
    timeframe: str = "30"
    pos_in_channel: Optional[float] = None
    big_trend: Optional[str] = None
    current_trend: Optional[str] = None
    quality: Optional[TradeQuality] = None
    bar_id: Optional[str] = None  # YYYYMMDD_HHMM for same-bar detection
    source: Optional[str] = None  # 触发来源 (L2/P0/SuperTrend等)


@dataclass
class IssueRecord:
    """问题记录"""
    level: str  # CRITICAL/WARNING/INFO
    category: str
    symbol: str
    description: str
    log_line: str = ""
    suggestion: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ImprovementSuggestion:
    """改善建议"""
    priority: str  # HIGH/MEDIUM/LOW
    category: str
    title: str
    detail: str
    action: str
    metrics: Dict = field(default_factory=dict)


# ============================================================
# 工具函数
# ============================================================

def get_ny_now() -> datetime:
    """获取纽约当前时间"""
    return datetime.now(ZoneInfo("America/New_York"))


def get_today_date_ny() -> str:
    """获取纽约时间今天日期"""
    return get_ny_now().strftime("%Y-%m-%d")


def safe_json_read(filepath: str) -> Optional[Dict]:
    """安全读取JSON文件"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"读取JSON失败 {filepath}: {e}")
    return None


def safe_json_write(filepath: str, data: Any) -> bool:
    """安全写入JSON文件"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"写入JSON失败 {filepath}: {e}")
        return False


IMPROVEMENTS_FILE = os.path.join("state", "improvements.json")

def save_audit_improvements(suggestions: list, date_str: str):
    """
    v3.5: 每次daily/weekly分析后，自动将发现的问题写入 state/improvements.json

    逻辑:
    1. 读取现有 improvements.json (如果读取失败且文件存在 → 跳过, 防覆盖)
    2. 对比新发现的问题 vs 已有条目（按 title 去重）
    3. 新问题 → 新增条目，status=FOUND, layer=AUDIT
    4. 写回文件 (保留version/notes等手动字段)
    """
    data = safe_json_read(IMPROVEMENTS_FILE)
    if not data:
        if os.path.exists(IMPROVEMENTS_FILE):
            logger.warning(f"[改善追踪] {IMPROVEMENTS_FILE} 读取失败(文件存在), 跳过写入防止覆盖")
            return
        data = {"version": 1, "last_updated": "", "items": []}

    # v2.1 by-key 结构不含 items[]，跳过自动写入（由 gcc-evo 管理）
    if "items" not in data:
        logger.info(f"[改善追踪] 检测到v2.1 by-key结构，跳过自动写入（由gcc-evo管理）")
        return

    existing_titles = {i["title"] for i in data["items"]}

    # 计算下一个 AUD ID
    existing_aud_ids = [
        int(i["id"].split("-")[1])
        for i in data["items"]
        if i["id"].startswith("AUD-")
    ]
    next_num = max(existing_aud_ids, default=0) + 1

    added = 0
    priority_map = {"HIGH": "P0", "MEDIUM": "P1", "LOW": "P2"}

    for s in suggestions:
        title = s.title if hasattr(s, "title") else s.get("title", "")
        if not title or title in existing_titles:
            continue

        priority = s.priority if hasattr(s, "priority") else s.get("priority", "MEDIUM")
        category = s.category if hasattr(s, "category") else s.get("category", "")
        detail = s.detail if hasattr(s, "detail") else s.get("detail", "")
        action = s.action if hasattr(s, "action") else s.get("action", "")

        item = {
            "id": f"AUD-{next_num:03d}",
            "layer": "AUDIT",
            "priority": priority_map.get(priority, "P1"),
            "title": title,
            "status": "FOUND",
            "phase": None,
            "found_date": date_str,
            "updated_date": date_str,
            "closed_date": None,
            "source": f"daily_v3_{date_str}",
            "description": f"{detail} | 建议: {action}",
            "files": [],
            "checklist": {"analyzed": False, "coded": False, "tested": False, "verified": False},
            "effect": None,
        }
        data["items"].append(item)
        existing_titles.add(title)
        next_num += 1
        added += 1

    if added > 0:
        data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        # v3.6: 写入前备份, 防止OneDrive同步冲突丢失数据
        backup_path = IMPROVEMENTS_FILE + ".bak"
        try:
            if os.path.exists(IMPROVEMENTS_FILE):
                import shutil
                shutil.copy2(IMPROVEMENTS_FILE, backup_path)
        except Exception:
            pass
        safe_json_write(IMPROVEMENTS_FILE, data)
        logger.info(f"[改善追踪] 自动写入 {added} 个新AUDIT项到 {IMPROVEMENTS_FILE} (共{len(data['items'])}项)")
    else:
        logger.info(f"[改善追踪] 无新发现(已有{len(data['items'])}项)")


def extract_symbol(line: str) -> str:
    """从日志行提取品种"""
    for sym in ALL_SYMBOLS:
        if sym in line:
            return sym
    match = re.search(r'\[(\w+USDC?)\]', line)
    if match:
        return match.group(1)
    return "UNKNOWN"


# yfinance symbol mapping for crypto
YFINANCE_SYMBOL_MAP = {
    "BTCUSDC": "BTC-USD",
    "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD",
    "ZECUSDC": "ZEC-USD",
}


def generate_candlestick_chart(symbol: str, date_str: str, trades: list,
                                timeframe_minutes: int = 240) -> Optional[str]:
    """Generate candlestick chart showing ONLY the 8AM-8AM reporting period with BUY/SELL markers.
    Returns base64-encoded PNG string, or None on failure."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        import yfinance as yf
        from datetime import datetime, timedelta
        import pytz

        # Map symbol for yfinance
        yf_symbol = YFINANCE_SYMBOL_MAP.get(symbol, symbol)

        # Reporting period: yesterday 8AM NY → today 8AM NY
        report_date = datetime.strptime(date_str, "%Y-%m-%d")
        period_start = (report_date - timedelta(days=1)).replace(hour=8, minute=0, second=0)
        period_end = report_date.replace(hour=8, minute=0, second=0)

        # Determine yfinance interval — use native timeframe when possible
        if timeframe_minutes <= 60:
            interval = "1h"
        elif timeframe_minutes <= 240:
            interval = "1h"   # fetch 1h, resample to 4h below if needed
        else:
            interval = "1d"

        # Fetch enough data to cover the reporting period + margin
        fetch_start = period_start - timedelta(days=2)
        fetch_end = period_end + timedelta(days=1)
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(start=fetch_start.strftime('%Y-%m-%d'),
                            end=fetch_end.strftime('%Y-%m-%d'),
                            interval=interval)
        if df.empty:
            return None

        # Localize index to naive datetime for comparison
        df.index = df.index.tz_localize(None) if df.index.tz is None else df.index.tz_convert('America/New_York').tz_localize(None)

        # Resample to target timeframe if needed (e.g. 1h → 4h)
        if timeframe_minutes > 60 and interval == "1h":
            df = df.resample(f'{timeframe_minutes}min', offset=f'{0}h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum'
            }).dropna()

        # Filter to ONLY the 8AM-8AM reporting period
        mask = (df.index >= period_start) & (df.index < period_end)
        df = df[mask]
        if df.empty:
            return None

        # Build candle lookup for snapping trade markers
        candle_times = [dt.to_pydatetime() if hasattr(dt, 'to_pydatetime') else dt for dt in df.index]
        candle_rows = [df.iloc[i] for i in range(len(df))]

        def _snap_trade_to_candle(trade_dt_naive):
            """Find nearest candle to a trade timestamp, return (index, row)."""
            best_idx, best_dist = 0, float('inf')
            for i, cdt in enumerate(candle_times):
                dist = abs((cdt - trade_dt_naive).total_seconds())
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            return best_idx, candle_rows[best_idx]

        # ---- Create figure ----
        num_bars = len(df)
        # Wider candles when fewer bars (6 bars for 4h)
        fig_width = max(8, min(12, num_bars * 1.2 + 2))
        bg_color = '#ffffff'
        fig, ax = plt.subplots(1, 1, figsize=(fig_width, 4.2), dpi=130)
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#e2e8f0')
            ax.spines[spine].set_linewidth(0.8)

        # Draw candlesticks — integer index for even spacing
        x_positions = list(range(num_bars))
        # Wider candles for fewer bars
        candle_width = 0.65 if num_bars <= 8 else 0.55 if num_bars <= 16 else 0.45
        green = '#22c55e'
        red = '#ef4444'
        green_light = '#dcfce7'
        red_light = '#fee2e2'

        for idx in range(num_bars):
            row = df.iloc[idx]
            x = x_positions[idx]
            o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
            is_up = c >= o
            body_color = green if is_up else red
            fill_color = green_light if is_up else red_light
            body_bottom = min(o, c)
            body_height = abs(c - o)

            # Wick
            ax.plot([x, x], [l, h], color=body_color, linewidth=1.2, solid_capstyle='round', zorder=2)
            # Body
            ax.add_patch(plt.Rectangle(
                (x - candle_width / 2, body_bottom), candle_width,
                max(body_height, (h - l) * 0.008),
                facecolor=fill_color, edgecolor=body_color, linewidth=1.2, zorder=3
            ))

        # Overlay BUY/SELL markers
        price_range = df['High'].max() - df['Low'].min()
        marker_offset = price_range * 0.06

        for trade in trades:
            try:
                trade_dt = datetime.strptime(trade.ts[:16], "%Y-%m-%d %H:%M")
                x_idx, candle = _snap_trade_to_candle(trade_dt)

                if trade.action == "BUY":
                    marker_y = candle['Low'] - marker_offset
                    ax.annotate('', xy=(x_idx, candle['Low']),
                               xytext=(x_idx, marker_y),
                               arrowprops=dict(arrowstyle='->', color=green, lw=2.0, shrinkA=0, shrinkB=1))
                    ax.text(x_idx, marker_y - marker_offset * 0.25, 'BUY',
                           fontsize=8.5, fontweight='bold', color=green,
                           ha='center', va='top', zorder=6)
                elif trade.action == "SELL":
                    marker_y = candle['High'] + marker_offset
                    ax.annotate('', xy=(x_idx, candle['High']),
                               xytext=(x_idx, marker_y),
                               arrowprops=dict(arrowstyle='->', color=red, lw=2.0, shrinkA=0, shrinkB=1))
                    ax.text(x_idx, marker_y + marker_offset * 0.25, 'SELL',
                           fontsize=8.5, fontweight='bold', color=red,
                           ha='center', va='bottom', zorder=6)
            except Exception:
                pass

        # ---- Axis formatting ----
        # X-axis: every bar gets a label (only 6 bars for 4h)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(
            [ct.strftime('%m/%d %H:%M') for ct in candle_times],
            fontsize=8.5, color='#64748b', rotation=0, ha='center'
        )

        ax.tick_params(axis='y', labelsize=8.5, colors='#64748b', length=0)
        ax.tick_params(axis='x', colors='#e2e8f0', length=3)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f'{x:,.0f}' if x >= 100 else f'{x:.2f}'
        ))

        # Light grid (y only)
        ax.yaxis.grid(True, color='#f1f5f9', linewidth=0.8, zorder=0)
        ax.xaxis.grid(False)

        # Y padding
        y_min = df['Low'].min()
        y_max = df['High'].max()
        y_pad = price_range * 0.15
        ax.set_ylim(y_min - y_pad, y_max + y_pad)
        ax.set_xlim(-0.8, num_bars - 0.2)

        # Title (left) + timeframe label (right)
        tf_label = f'{timeframe_minutes // 60}h' if timeframe_minutes >= 60 else f'{timeframe_minutes}m'
        ax.set_title(f'{symbol}  ', fontsize=13, fontweight='600', color='#0f172a',
                     loc='left', pad=10)
        ax.text(num_bars - 0.5, y_max + y_pad * 0.85, tf_label,
                fontsize=9, color='#94a3b8', ha='right', va='top')
        # Period subtitle
        ax.text(-0.5, y_max + y_pad * 0.85,
                f'{period_start.strftime("%m/%d")} 8AM → {period_end.strftime("%m/%d")} 8AM',
                fontsize=8, color='#94a3b8', ha='left', va='top')

        plt.tight_layout(pad=1.5)

        # Export to base64
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor=bg_color, edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode('utf-8')

    except Exception as e:
        logger.warning(f"[HTML] Chart generation failed for {symbol}: {e}")
        return None


# ============================================================
# 问题检测器基类
# ============================================================

class IssueDetector:
    """问题检测器"""

    def __init__(self):
        self.issues: List[IssueRecord] = []
        self.stats: Dict[str, Any] = defaultdict(int)
        self._seen_issues: set = set()

    def add_issue(self, level: str, category: str, symbol: str,
                  description: str, log_line: str = "", suggestion: str = ""):
        """添加问题"""
        dedup_key = f"{category}|{symbol}|{description[:50]}"
        if dedup_key in self._seen_issues:
            self.stats[f"{level}_{category}_dup"] += 1
            return
        self._seen_issues.add(dedup_key)

        issue = IssueRecord(
            level=level,
            category=category,
            symbol=symbol,
            description=description,
            log_line=log_line[:200] if log_line else "",
            suggestion=suggestion,
        )
        self.issues.append(issue)
        self.stats[f"{level}_{category}"] += 1

    def get_issues_by_level(self, level: str) -> List[IssueRecord]:
        return [i for i in self.issues if i.level == level]

    def get_summary(self) -> Dict:
        return {
            "total": len(self.issues),
            "critical": len(self.get_issues_by_level("CRITICAL")),
            "warning": len(self.get_issues_by_level("WARNING")),
            "info": len(self.get_issues_by_level("INFO")),
            "by_category": dict(self.stats),
        }


# ============================================================
# 1. LogicChecker - 主程序逻辑问题检测
# ============================================================

class LogicChecker:
    """
    主程序逻辑问题检测器

    检测内容:
    1. big_trend vs current_trend 不一致性
    2. Vision覆盖逻辑错误
    3. 道氏理论 HH/HL/LH/LL 判断异常
    4. 趋势切换频率异常
    5. v3.620: CNN覆盖融合事件追踪
    6. v3.620: Vision准确率覆盖L1事件追踪
    7. v3.620: 双底双顶跳过x4过滤事件追踪
    """

    PATTERNS = {
        # big_trend vs current_trend 矛盾 (非正常顺大逆小)
        "trend_conflict": re.compile(
            r"big_trend\s*[=:]\s*(UP|DOWN).*current_trend\s*[=:]\s*(DOWN|UP)",
            re.I
        ),

        # Vision覆盖异常
        "vision_override_error": re.compile(
            r"Vision覆盖.*错误|Vision.*override.*error|vision_override_to.*失败"
        ),
        "vision_confidence_low": re.compile(
            r"confidence\s*[=<:]\s*0\.[0-7]\d*.*覆盖|低置信度.*覆盖"
        ),
        "vision_ttl_expired": re.compile(
            r"Vision.*过期|Vision.*expired|TTL.*过期"
        ),

        # 道氏理论异常
        "dow_hh_but_down": re.compile(
            r"HH.*(?:DOWN|下降)|更高高点.*DOWN"
        ),
        "dow_ll_but_up": re.compile(
            r"LL.*(?:UP|上升)|更低低点.*UP"
        ),
        "dow_mixed": re.compile(
            r"HH.*LL|LL.*HH|道氏.*混乱|无清晰.*高低点"
        ),

        # 趋势快速切换
        "trend_flip": re.compile(
            r"(current_trend|big_trend).*(?:UP→DOWN|DOWN→UP|切换|flip)"
        ),

        # 仓位逻辑问题
        "position_overflow": re.compile(
            r"仓位.*超过|position.*exceed|仓位[>]\s*[56]"
        ),
        "position_underflow": re.compile(
            r"仓位.*负数|position.*negative|仓位[<]\s*0"
        ),

        # v3.620: CNN覆盖融合 (L2层面)
        "cnn_override": re.compile(
            r"CNN.*覆盖融合|cnn_override|CNN\([\d.]+%?\)\s*>\s*融合"
        ),

        # v3.640: 准确率覆盖L1 (Vision>90%覆盖缠论基线)
        "accuracy_override": re.compile(
            r"v3\.6[34]0.*覆盖L1|accuracy_override|★\s*\w+覆盖L1"
        ),

        # v3.640: x4缠论胜出 (准确率竞争)
        "x4_chan_wins": re.compile(
            r"x4缠论胜出|x4_chan.*>.*道氏"
        ),

        # v3.620: 双底双顶跳过x4过滤
        "double_pattern_skip_x4": re.compile(
            r"双底双顶.*跳过x4|跳过x4过滤.*双底|v3\.620.*跳过x4"
        ),

        # === P1-3: API/网络错误追踪 ===
        "api_3commas_error": re.compile(
            r"3[Cc]ommas.*(?:error|fail|timeout|exception|refused|Error|异常|超时)|"
            r"(?:error|fail|timeout|Error|异常|超时).*3[Cc]ommas",
            re.I
        ),
        "api_signalstack_error": re.compile(
            r"SignalStack.*(?:error|fail|timeout|exception|refused|Error|异常|超时)|"
            r"(?:error|fail|timeout|Error|异常|超时).*SignalStack",
            re.I
        ),
        "api_http_error": re.compile(
            r"HTTP\s*(?:error|[45]\d{2})|"
            r"requests\.exceptions|"
            r"ConnectionError|ConnectionRefused|"
            r"TimeoutError|ReadTimeout|ConnectTimeout|"
            r"ConnectionResetError|RemoteDisconnected"
        ),
        "order_execution_error": re.compile(
            r"(?:order|下单|执行交易).*(?:失败|error|fail|reject)|"
            r"(?:失败|error|fail|reject).*(?:order|下单|执行交易)|"
            r"execute_trade.*(?:error|fail|Exception)"
        ),
    }

    def __init__(self):
        self.trend_history: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)

    def check(self, log_lines: List[str], detector: IssueDetector) -> Dict:
        """检查主程序逻辑问题"""
        results = {
            "trend_conflicts": 0,
            "vision_errors": 0,
            "dow_anomalies": 0,
            "trend_flips": 0,
            "position_errors": 0,
            "cnn_overrides": 0,
            "accuracy_overrides": 0,
            "double_pattern_skip_x4": 0,
            "x4_chan_wins": 0,
            "api_errors": 0,
            "order_errors": 0,
            "api_error_details": [],
        }

        for line in log_lines:
            symbol = extract_symbol(line)

            # 1. big_trend vs current_trend 矛盾
            match = self.PATTERNS["trend_conflict"].search(line)
            if match and "顺大逆小" not in line and "反弹" not in line and "回调" not in line:
                big, current = match.groups()
                detector.add_issue(
                    "WARNING", "LOGIC_TREND_CONFLICT", symbol,
                    f"趋势矛盾: big_trend={big}, current_trend={current}",
                    line,
                    "检查Vision覆盖或Human模块道氏理论判断"
                )
                results["trend_conflicts"] += 1

            # 2. Vision覆盖错误
            if self.PATTERNS["vision_override_error"].search(line):
                detector.add_issue(
                    "CRITICAL", "LOGIC_VISION_ERROR", symbol,
                    "Vision覆盖执行错误",
                    line,
                    "检查vision_override_to逻辑和confidence阈值"
                )
                results["vision_errors"] += 1

            if self.PATTERNS["vision_confidence_low"].search(line):
                detector.add_issue(
                    "WARNING", "LOGIC_VISION_CONFIDENCE", symbol,
                    "低置信度Vision结果被应用",
                    line,
                    "应要求confidence >= 0.8才能覆盖"
                )
                results["vision_errors"] += 1

            # 3. 道氏理论异常
            if self.PATTERNS["dow_hh_but_down"].search(line):
                detector.add_issue(
                    "WARNING", "LOGIC_DOW_ANOMALY", symbol,
                    "道氏理论异常: HH(更高高点)但判定DOWN",
                    line,
                    "检查Human模块高低点计算"
                )
                results["dow_anomalies"] += 1

            if self.PATTERNS["dow_ll_but_up"].search(line):
                detector.add_issue(
                    "WARNING", "LOGIC_DOW_ANOMALY", symbol,
                    "道氏理论异常: LL(更低低点)但判定UP",
                    line,
                    "检查Human模块高低点计算"
                )
                results["dow_anomalies"] += 1

            # 4. 趋势快速切换追踪
            if self.PATTERNS["trend_flip"].search(line):
                results["trend_flips"] += 1
                self._track_trend_flip(line, symbol, detector)

            # 5. 仓位逻辑问题
            if self.PATTERNS["position_overflow"].search(line):
                detector.add_issue(
                    "CRITICAL", "LOGIC_POSITION", symbol,
                    "仓位溢出: 超过最大仓位",
                    line,
                    "检查仓位管理逻辑"
                )
                results["position_errors"] += 1

            if self.PATTERNS["position_underflow"].search(line):
                detector.add_issue(
                    "CRITICAL", "LOGIC_POSITION", symbol,
                    "仓位下溢: 仓位为负数",
                    line,
                    "检查仓位管理逻辑"
                )
                results["position_errors"] += 1

            # 6. v3.620: CNN覆盖融合事件
            if self.PATTERNS["cnn_override"].search(line):
                results["cnn_overrides"] += 1
                detector.add_issue(
                    "INFO", "V3620_CNN_OVERRIDE", symbol,
                    "CNN覆盖融合: CNN准确率高于融合，直接使用CNN结果",
                    line,
                    "正常行为(v3.620): CNN准确率>融合准确率时自动覆盖"
                )

            # 7. v3.640: Vision覆盖L1 (confidence>90%覆盖缠论基线)
            if self.PATTERNS["accuracy_override"].search(line):
                results["accuracy_overrides"] += 1
                detector.add_issue(
                    "INFO", "V3640_ACCURACY_OVERRIDE", symbol,
                    "Vision覆盖L1: confidence>90%覆盖缠论基线趋势",
                    line,
                    "正常行为(v3.640): Vision置信度>90%且与缠论不一致时覆盖"
                )

            # 8b. v3.640: x4缠论胜出 (准确率竞争)
            if self.PATTERNS["x4_chan_wins"].search(line):
                results["x4_chan_wins"] += 1

            # 8. v3.620: 双底双顶跳过x4过滤
            if self.PATTERNS["double_pattern_skip_x4"].search(line):
                results["double_pattern_skip_x4"] += 1

            # 9. API/网络错误 (P1-3)
            for api_key in ("api_3commas_error", "api_signalstack_error", "api_http_error"):
                if self.PATTERNS[api_key].search(line):
                    results["api_errors"] += 1
                    ts_m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', line)
                    results["api_error_details"].append({
                        "time": ts_m.group(1) if ts_m else "",
                        "type": api_key.replace("api_", "").replace("_error", ""),
                        "symbol": symbol,
                        "line": line.strip()[:150],
                    })
                    detector.add_issue(
                        "CRITICAL", "API_NETWORK_ERROR", symbol,
                        f"API/网络错误({api_key.replace('api_', '').replace('_error', '')}): 可能导致信号丢失",
                        line.strip()[:200],
                        "检查网络连接和API密钥有效性"
                    )
                    break  # 一行只匹配一种API错误

            if self.PATTERNS["order_execution_error"].search(line):
                results["order_errors"] += 1
                detector.add_issue(
                    "CRITICAL", "ORDER_EXEC_ERROR", symbol,
                    "下单执行失败: 信号产生但未成功下单",
                    line.strip()[:200],
                    "检查API连接和账户状态"
                )

        detector.stats["logic_check_results"] = results
        return results

    def _track_trend_flip(self, line: str, symbol: str, detector: IssueDetector):
        """追踪趋势快速切换"""
        trend_match = re.search(
            r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}).*(?:big_trend|current_trend)[=:]\s*(\w+)',
            line
        )
        if trend_match:
            ts, trend = trend_match.groups()
            self.trend_history[symbol].append((ts, trend))

            # 保留最近20条
            if len(self.trend_history[symbol]) > 20:
                self.trend_history[symbol] = self.trend_history[symbol][-20:]

            # 检查快速切换 (5次记录中切换3次以上)
            if len(self.trend_history[symbol]) >= 5:
                recent = self.trend_history[symbol][-5:]
                changes = sum(1 for i in range(1, len(recent)) if recent[i][1] != recent[i-1][1])
                if changes >= 3:
                    detector.add_issue(
                        "WARNING", "LOGIC_TREND_FLIP", symbol,
                        f"趋势快速切换: 最近5次记录中切换{changes}次",
                        line,
                        "可能是震荡市场，考虑增加趋势确认条件"
                    )

    # Rejected signal patterns
    REJECTED_PATTERNS = {
        "sr_veto_buy": re.compile(r'\[SR_VETO_BUY\].*?(\w+USDC?).*?禁止买入'),
        "sr_veto_sell": re.compile(r'\[SR_VETO_SELL\].*?(\w+USDC?).*?禁止卖出'),
        "pos_gate_buy": re.compile(r'满仓.*?跳过买入'),
        "pos_gate_sell": re.compile(r'空仓.*?跳过卖出'),
        "l1_veto_buy": re.compile(r'L1.*?否决.*?L2.*?BUY.*?→\s*HOLD|L1=HOLD.*L2=BUY.*→.*HOLD'),
        "l1_veto_sell": re.compile(r'L1.*?否决.*?L2.*?SELL.*?→\s*HOLD|L1=HOLD.*L2=SELL.*→.*HOLD'),
        "direction_conflict": re.compile(r'方向冲突.*?→\s*HOLD'),
        "native_hold": re.compile(r'信号为HOLD[，,]不执行交易'),
        # v3.650: L1参考模式(不下单)
        "l1_ref_buy": re.compile(r'\[v3\.650\]\s+L1参考信号:\s+(\S+)\s+BUY'),
        "l1_ref_sell": re.compile(r'\[v3\.650\]\s+L1参考信号:\s+(\S+)\s+SELL'),
        # L2 STRONG阻止扫描引擎反向信号
        "l2_strong_block": re.compile(r'\[v21[^\]]*\]\s+(\S+)\s+.*?(BUY|SELL)\s+L2空间阻止'),
        # v3.411 满仓/空仓最终拦截
        "full_pos_block": re.compile(r'\[v3\.411\]\s+⛔\s+满仓最终拦截\s+\[(\S+)\]'),
        "empty_pos_block": re.compile(r'\[v3\.411\]\s+⛔\s+空仓最终拦截\s+\[(\S+)\]'),
        # v21.6: 节奏质量过滤 (追高拦截/低位拦截)
        "rhythm_block": re.compile(r'\[v21\.\d+\]\s+(\S+)\s+(\S+)\s+(BUY|SELL)\s+节奏过滤:\s+(追高拦截|低位拦截)'),
        # v21.6: 唐纳奇支撑保护 (移动止损低位保护)
        "donchian_support": re.compile(r'\[v21\.\d+\]\s+(\S+)\s+移动止损\s+SELL\s+→\s+HOLD\s+\|\s+唐纳奇支撑保护'),
        # v21.7: 硬底保护 (节奏过滤中通道位置<20%绝对拦截)
        "hard_floor_block": re.compile(r'\[v21\.\d+\]\s+(\S+)\s+(\S+)\s+(BUY|SELL)\s+节奏过滤:\s+硬底保护'),
        # v21.7: EMA顺势过滤 (拦截/观察) — v3.653: EMA5→EMA\d+ (品种分化)
        # 注: 插件源名可含空格(如"Rob Hoffman")，用.+?替代\S+
        "ema5_block":    re.compile(r'\[v21\.\d+\]\s+(\S+)\s+.+?\s+(BUY|SELL)\s+EMA\d+拦截'),
        "ema5_observe":  re.compile(r'\[v21\.\d+\]\s+(\S+)\s+.+?\s+(BUY|SELL)\s+\[观察\]\s+EMA\d+逆势'),
        # v3.671: NStructPlugin EMA过滤日志格式不同
        "ema_filter_nstruct": re.compile(r'\[NStructPlugin\]\s+(\S+)\s+(BUY|SELL)\s+EMA过滤'),
        # v3.653: 校准器τ过滤 (噪声样本排除)
        "tau_filter": re.compile(r'\[HUMAN_CALIBRATOR\]\s+(\S+)\s+τ过滤'),
        # v3.653: 视角分歧度导致Vision覆盖阈值提高
        "view_divergence_raise": re.compile(r'\[v3\.653\]\s+视角分歧度=(\S+)>0\.15'),
        # v3.656: Anti-Whipsaw HOLD带降频
        "hold_band_suppress": re.compile(r'\[v3\.656\]\[(\S+)\]\s+HOLD带降频:\s+(.+?)\s+缠论(\w+)→SIDE'),
        # v3.656: HOLD带全局门控拦截 (L1/L2/外挂)
        "hold_band_block": re.compile(r'\[v3\.656\]\s+⛔\s+HOLD带拦截\s+\[(\S+)\]:\s+(\w+)\s+被阻止\s+\(来源=(\S+)\)'),
        # v3.657: Vision N字结构检测
        "vision_n_pattern": re.compile(r'\[v3\.657\]\[(\S+)\]\s+Vision N字结构:\s+(UP_N|DOWN_N)'),
        # v3.660: N字门控实际拦截 (全品种ACTIVE)
        "n_gate_block_active": re.compile(r'\[N_GATE拦截\]\s+(\S+)\s+(?:P0|L2-Gate|MACD-L2)?\s*(\w+)\s+src=(\S+)'),
        # v3.671: 美股盘外TradingView拦截
        "market_hours_block": re.compile(r'\[MARKET_HOURS\]\s+(\S+).*盘外推送.*忽略'),
        # v3.663: KEY-003价值分析BUY拦截
        "key003_value_guard": re.compile(r'\[KEY-003\]\[VALUE-GUARD\]\[拦截\]\s+(\S+)\s+BUY被拦截'),
    }

    def parse_rejected_signals(self, log_lines: List[str], date_str: str) -> Dict[str, List[Dict]]:
        """解析被拒信号记录

        Returns:
            {symbol: [{time, original_signal, reason, log_line}, ...]}
        """
        rejected = defaultdict(list)

        for line in log_lines:
            if date_str and date_str not in line:
                continue

            ts_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)', line)
            ts = ts_match.group(1) if ts_match else ""

            # SR veto buy
            m = self.REJECTED_PATTERNS["sr_veto_buy"].search(line)
            if m:
                sym = m.group(1) if m.lastindex else extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "BUY",
                    "reason": "[SR_VETO_BUY] 接近阻力位，禁止买入",
                    "log_line": line.strip()[:200]
                })
                continue

            # SR veto sell
            m = self.REJECTED_PATTERNS["sr_veto_sell"].search(line)
            if m:
                sym = m.group(1) if m.lastindex else extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "SELL",
                    "reason": "[SR_VETO_SELL] 接近支撑位，禁止卖出",
                    "log_line": line.strip()[:200]
                })
                continue

            # Position gate buy
            if self.REJECTED_PATTERNS["pos_gate_buy"].search(line):
                sym = extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "BUY",
                    "reason": "满仓跳过买入",
                    "log_line": line.strip()[:200]
                })
                continue

            # Position gate sell
            if self.REJECTED_PATTERNS["pos_gate_sell"].search(line):
                sym = extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "SELL",
                    "reason": "空仓跳过卖出",
                    "log_line": line.strip()[:200]
                })
                continue

            # L1 veto L2 BUY
            if self.REJECTED_PATTERNS["l1_veto_buy"].search(line):
                sym = extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "BUY",
                    "reason": "L1=HOLD 否决 L2=BUY",
                    "log_line": line.strip()[:200]
                })
                continue

            # L1 veto L2 SELL
            if self.REJECTED_PATTERNS["l1_veto_sell"].search(line):
                sym = extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "SELL",
                    "reason": "L1=HOLD 否决 L2=SELL",
                    "log_line": line.strip()[:200]
                })
                continue

            # Direction conflict
            if self.REJECTED_PATTERNS["direction_conflict"].search(line):
                sym = extract_symbol(line)
                rejected[sym].append({
                    "time": ts, "original_signal": "BUY/SELL",
                    "reason": "方向冲突 → HOLD",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.650: L1参考信号(不下单)
            m = self.REJECTED_PATTERNS["l1_ref_buy"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "BUY",
                    "reason": "v3.650 L1参考(不下单)",
                    "log_line": line.strip()[:200]
                })
                continue
            m = self.REJECTED_PATTERNS["l1_ref_sell"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "SELL",
                    "reason": "v3.650 L1参考(不下单)",
                    "log_line": line.strip()[:200]
                })
                continue

            # L2 STRONG阻止反向信号
            m = self.REJECTED_PATTERNS["l2_strong_block"].search(line)
            if m:
                sym = m.group(1)
                blocked_action = m.group(2)
                rejected[sym].append({
                    "time": ts, "original_signal": blocked_action,
                    "reason": "L2 STRONG阻止反向信号",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.411 满仓最终拦截
            m = self.REJECTED_PATTERNS["full_pos_block"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "BUY",
                    "reason": "v3.411 满仓最终拦截",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.411 空仓最终拦截
            m = self.REJECTED_PATTERNS["empty_pos_block"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "SELL",
                    "reason": "v3.411 空仓最终拦截",
                    "log_line": line.strip()[:200]
                })
                continue

            # v21.6: 节奏质量过滤 (追高拦截/低位拦截)
            m = self.REJECTED_PATTERNS["rhythm_block"].search(line)
            if m:
                sym, plugin, action, block_type = m.group(1), m.group(2), m.group(3), m.group(4)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": f"v21.6 {block_type}({plugin})",
                    "log_line": line.strip()[:200]
                })
                continue

            # v21.6: 唐纳奇支撑保护
            m = self.REJECTED_PATTERNS["donchian_support"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "SELL",
                    "reason": "v21.7 唐纳奇支撑保护(移动止损)",
                    "log_line": line.strip()[:200]
                })
                continue

            # v21.7: 硬底保护 (通道位置<20%绝对拦截)
            m = self.REJECTED_PATTERNS["hard_floor_block"].search(line)
            if m:
                sym, plugin, action = m.group(1), m.group(2), m.group(3)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": f"v21.7 硬底保护({plugin})",
                    "log_line": line.strip()[:200]
                })
                continue

            # v21.7: EMA5顺势过滤拦截 (Phase4启用时)
            m = self.REJECTED_PATTERNS["ema5_block"].search(line)
            if m:
                sym, action = m.group(1), m.group(2)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": "v21.7 EMA5拦截",
                    "log_line": line.strip()[:200]
                })
                continue
            # v3.671: NStructPlugin EMA过滤
            m = self.REJECTED_PATTERNS["ema_filter_nstruct"].search(line)
            if m:
                sym, action = m.group(1), m.group(2)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": "N字外挂EMA过滤",
                    "log_line": line.strip()[:200]
                })
                continue

            # v21.7: EMA顺势过滤观察 (Phase3记录)
            m = self.REJECTED_PATTERNS["ema5_observe"].search(line)
            if m:
                sym, plugin, action = m.group(1), m.group(2), m.group(3)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": f"v21.7 EMA观察({plugin})",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.653: 校准器τ过滤 (噪声样本排除)
            m = self.REJECTED_PATTERNS["tau_filter"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "CALIBRATOR",
                    "reason": "v3.653 τ过滤(噪声样本排除)",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.653: 视角分歧度导致覆盖阈值提高
            m = self.REJECTED_PATTERNS["view_divergence_raise"].search(line)
            if m:
                _vd_val = m.group(1)
                # 从上下文提取品种(server.log中通常有品种前缀)
                sym_m = re.search(r'\b(BTCUSDC|ETHUSDC|SOLUSDC|ZECUSDC|TSLA|COIN|AMD|RDDT|RKLB|NBIS|CRWV|HIMS|OPEN|ONDS|PLTR)\b', line)
                sym = sym_m.group(1) if sym_m else "UNKNOWN"
                rejected[sym].append({
                    "time": ts, "original_signal": "VISION_OVERRIDE",
                    "reason": f"v3.653 视角分歧度={_vd_val}→覆盖阈值提高至90%",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.656: HOLD带降频 (Anti-Whipsaw - compute_human_phase层)
            m = self.REJECTED_PATTERNS["hold_band_suppress"].search(line)
            if m:
                sym = m.group(1)
                _hb_detail = m.group(2)
                _hb_orig = m.group(3)
                rejected[sym].append({
                    "time": ts, "original_signal": _hb_orig.upper(),
                    "reason": f"v3.656 HOLD带降频({_hb_detail})",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.656: HOLD带全局门控拦截 (发单层: L1/L2/外挂)
            m = self.REJECTED_PATTERNS["hold_band_block"].search(line)
            if m:
                sym, action, src = m.group(1), m.group(2), m.group(3)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": f"v3.656 HOLD带拦截(来源={src})",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.671: 美股盘外拦截
            m = self.REJECTED_PATTERNS["market_hours_block"].search(line)
            if m:
                sym = m.group(1)
                rejected[sym].append({
                    "time": ts, "original_signal": "TV_WEBHOOK",
                    "reason": "v3.671 美股盘外TradingView推送忽略",
                    "log_line": line.strip()[:200]
                })
                continue

            # v3.660: N字门控实际拦截 (v3.671起改为观察日志，此模式仅匹配历史记录)
            m = self.REJECTED_PATTERNS["n_gate_block_active"].search(line)
            if m:
                sym, action, src = m.group(1), m.group(2), m.group(3)
                rejected[sym].append({
                    "time": ts, "original_signal": action,
                    "reason": f"v3.660 N字门控拦截(来源={src})",
                    "log_line": line.strip()[:200]
                })
                continue

        return dict(rejected)


# ============================================================
# 2. RedundantTradeChecker - 多余交易检测
# ============================================================

class RedundantTradeChecker:
    """
    多余交易和额外交易识别器

    检测内容:
    1. 同一K线内反复交易 (震荡市场频繁买卖)
    2. 亏损交易模式 (买高卖低序列)
    3. 外挂重复触发 (多个外挂对同一信号重复下单)
    4. 无效交易 (小盈小亏反复进出)
    """

    # 阈值配置
    LOSS_THRESHOLD_PCT = 0.5      # 亏损超过0.5%视为亏损交易
    SMALL_PNL_THRESHOLD_PCT = 0.3 # 小于0.3%视为无效交易
    CHURN_TRADES_THRESHOLD = 3    # 一天内>=3次无效交易视为频繁

    def __init__(self):
        self.trade_history: List[TradeRecord] = []

    def load_trades(self, filepath: str, date_str: str = None) -> List[TradeRecord]:
        """加载交易历史"""
        if not os.path.exists(filepath):
            logger.warning(f"交易历史文件不存在: {filepath}")
            return []

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw_trades = json.load(f)

            trades = []
            for t in raw_trades:
                ts = t.get("ts", "")
                if date_str and not ts.startswith(date_str):
                    continue

                # 生成bar_id用于同K线检测
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    tf = int(t.get("timeframe", "30"))
                    minute_aligned = (dt.minute // tf) * tf
                    bar_id = f"{dt.strftime('%Y%m%d_%H')}{minute_aligned:02d}"
                except Exception:
                    bar_id = ts[:16].replace("-", "").replace(" ", "_").replace(":", "")

                # v3.5: 读取pos_in_channel (v3.652主程序开始写入此字段)
                _pos = t.get("pos_in_channel")
                if _pos is not None:
                    try:
                        _pos = float(_pos)
                    except (ValueError, TypeError):
                        _pos = None

                trades.append(TradeRecord(
                    ts=ts,
                    symbol=t.get("symbol", "UNKNOWN"),
                    action=t.get("action", ""),
                    price=t.get("price", 0),
                    units=t.get("units", 0),
                    timeframe=str(t.get("timeframe", "30")),
                    pos_in_channel=_pos,
                    bar_id=bar_id,
                    source=t.get("source", "L2"),
                ))

            self.trade_history = sorted(trades, key=lambda x: x.ts)
            return self.trade_history

        except Exception as e:
            logger.error(f"加载交易历史失败: {e}")
            return []

    def check(self, detector: IssueDetector, trades: List[TradeRecord] = None) -> Dict:
        """执行所有检测"""
        if trades:
            self.trade_history = trades

        results = {
            "same_bar_trades": [],
            "loss_trades": [],
            "churn_trades": [],
            "duplicate_triggers": [],
            "total_loss_amount": 0.0,
        }

        # 1. 检测同K线反复交易
        same_bar = self._check_same_bar_trades(detector)
        results["same_bar_trades"] = same_bar

        # 2. 检测亏损交易模式
        loss_trades, total_loss = self._check_loss_patterns(detector)
        results["loss_trades"] = loss_trades
        results["total_loss_amount"] = total_loss

        # 3. 检测无效交易 (小盈小亏)
        churn = self._check_churn_trades(detector)
        results["churn_trades"] = churn

        detector.stats["redundant_check_results"] = results
        return results

    def _check_same_bar_trades(self, detector: IssueDetector) -> List[Dict]:
        """检测同一K线内的反复交易"""
        same_bar_issues = []
        by_bar: Dict[str, List[TradeRecord]] = defaultdict(list)

        for trade in self.trade_history:
            key = f"{trade.symbol}_{trade.bar_id}"
            by_bar[key].append(trade)

        for key, trades in by_bar.items():
            if len(trades) >= 2:
                has_buy = any(t.action == "BUY" for t in trades)
                has_sell = any(t.action == "SELL" for t in trades)

                if has_buy and has_sell:
                    symbol = trades[0].symbol
                    issue = {
                        "symbol": symbol,
                        "bar_id": trades[0].bar_id,
                        "trade_count": len(trades),
                        "trades": [f"{t.action}@{t.price:.2f}" for t in trades],
                    }
                    same_bar_issues.append(issue)

                    detector.add_issue(
                        "WARNING", "REDUNDANT_SAME_BAR", symbol,
                        f"同K线反复交易: {len(trades)}笔 ({trades[0].bar_id})",
                        str(issue["trades"]),
                        "震荡市场信号频繁切换，增加K线内冻结时间"
                    )

        detector.stats["same_bar_trade_count"] = len(same_bar_issues)
        return same_bar_issues

    def _check_loss_patterns(self, detector: IssueDetector) -> Tuple[List[Dict], float]:
        """检测亏损交易模式 - LIFO配对 (5档仓位制: 最近买入优先配对卖出)"""
        loss_trades = []
        total_loss = 0.0

        by_symbol: Dict[str, List[TradeRecord]] = defaultdict(list)
        for trade in self.trade_history:
            by_symbol[trade.symbol].append(trade)

        for symbol, trades in by_symbol.items():
            buy_stack: List[TradeRecord] = []  # LIFO stack

            for trade in trades:
                if trade.action == "BUY":
                    buy_stack.append(trade)
                elif trade.action == "SELL" and buy_stack:
                    # LIFO: 最近一次买入配对这次卖出
                    buy_trade = buy_stack.pop()
                    if buy_trade.price <= 0:
                        continue
                    pnl_pct = (trade.price - buy_trade.price) / buy_trade.price * 100

                    if pnl_pct < -self.LOSS_THRESHOLD_PCT:
                        loss_amount = (buy_trade.price - trade.price) * buy_trade.units
                        total_loss += loss_amount

                        issue = {
                            "symbol": symbol,
                            "buy_price": buy_trade.price,
                            "sell_price": trade.price,
                            "loss_pct": abs(pnl_pct),
                            "loss_amount": loss_amount,
                            "buy_ts": buy_trade.ts,
                            "sell_ts": trade.ts,
                            "buy_source": buy_trade.source or "L2",
                            "sell_source": trade.source or "L2",
                        }
                        loss_trades.append(issue)

                        detector.add_issue(
                            "WARNING", "REDUNDANT_LOSS_TRADE", symbol,
                            f"亏损: BUY@{buy_trade.price:.2f}({buy_trade.source or 'L2'})→SELL@{trade.price:.2f}({trade.source or 'L2'}) -{abs(pnl_pct):.1f}%",
                            f"亏损${loss_amount:.2f}",
                            "检查入场时机和止损策略"
                        )

        detector.stats["loss_trade_count"] = len(loss_trades)
        detector.stats["loss_trade_amount"] = total_loss
        return loss_trades, total_loss

    def _check_churn_trades(self, detector: IssueDetector) -> List[Dict]:
        """检测无效交易 (小盈小亏反复进出)"""
        churn_trades = []

        by_symbol: Dict[str, List[TradeRecord]] = defaultdict(list)
        for trade in self.trade_history:
            by_symbol[trade.symbol].append(trade)

        for symbol, trades in by_symbol.items():
            small_pnl_list = []
            i = 0
            while i < len(trades) - 1:
                if trades[i].action == "BUY":
                    buy_trade = trades[i]
                    for j in range(i + 1, len(trades)):
                        if trades[j].action == "SELL" and trades[j].symbol == symbol:
                            sell_trade = trades[j]
                            pnl_pct = abs((sell_trade.price - buy_trade.price) / buy_trade.price * 100)

                            if pnl_pct < self.SMALL_PNL_THRESHOLD_PCT:
                                small_pnl_list.append({
                                    "buy_price": buy_trade.price,
                                    "sell_price": sell_trade.price,
                                    "pnl_pct": pnl_pct,
                                })
                            break
                i += 1

            if len(small_pnl_list) >= self.CHURN_TRADES_THRESHOLD:
                issue = {
                    "symbol": symbol,
                    "churn_count": len(small_pnl_list),
                    "trades": small_pnl_list,
                }
                churn_trades.append(issue)

                detector.add_issue(
                    "WARNING", "REDUNDANT_CHURN", symbol,
                    f"频繁无效交易: {len(small_pnl_list)}次小盈亏(<{self.SMALL_PNL_THRESHOLD_PCT}%)",
                    "",
                    "增大止盈止损阈值或减少交易频率"
                )

        detector.stats["churn_trade_count"] = sum(c["churn_count"] for c in churn_trades)
        return churn_trades

    def get_trade_summary(self) -> Dict:
        """获取交易摘要统计"""
        if not self.trade_history:
            return {}

        by_symbol = defaultdict(lambda: {"buys": 0, "sells": 0, "volume": 0.0})
        for t in self.trade_history:
            by_symbol[t.symbol]["buys" if t.action == "BUY" else "sells"] += 1
            by_symbol[t.symbol]["volume"] += t.price * t.units

        return {
            "total_trades": len(self.trade_history),
            "by_symbol": dict(by_symbol),
            "unique_bars": len(set(f"{t.symbol}_{t.bar_id}" for t in self.trade_history))
        }


# ============================================================
# 2a-2. WhipsawDetector - 跨天来回买卖检测 (v3.6)
# ============================================================

class WhipsawDetector:
    """
    跨天来回买卖检测 - 周/月级别

    检测逻辑:
    1. 按品种分组交易记录
    2. 统计方向翻转次数 (BUY→SELL或SELL→BUY)
    3. LIFO配对计算每次来回P&L
    4. 标记whipsaw品种(flips>=3)和worst offenders(按净亏损排序)
    """

    FLIP_THRESHOLD = 3        # >=3次方向翻转视为whipsaw
    NET_LOSS_THRESHOLD = 50   # 来回净亏损>$50视为问题

    def load_trades_range(self, filepath: str, start_date: str, end_date: str) -> List[TradeRecord]:
        """加载日期范围内的交易记录"""
        if not os.path.exists(filepath):
            logger.warning(f"交易历史文件不存在: {filepath}")
            return []

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw_trades = json.load(f)

            trades = []
            for t in raw_trades:
                ts = t.get("ts", "")
                date_part = ts[:10]  # "YYYY-MM-DD"
                if date_part < start_date or date_part > end_date:
                    continue

                _pos = t.get("pos_in_channel")
                if _pos is not None:
                    try:
                        _pos = float(_pos)
                    except (ValueError, TypeError):
                        _pos = None

                trades.append(TradeRecord(
                    ts=ts,
                    symbol=t.get("symbol", "UNKNOWN"),
                    action=t.get("action", ""),
                    price=t.get("price", 0),
                    units=t.get("units", 0),
                    timeframe=str(t.get("timeframe", "30")),
                    pos_in_channel=_pos,
                    source=t.get("source", "L2"),
                ))

            return sorted(trades, key=lambda x: x.ts)

        except Exception as e:
            logger.error(f"WhipsawDetector加载交易历史失败: {e}")
            return []

    def detect(self, trades: List[TradeRecord]) -> Dict:
        """主检测入口"""
        if not trades:
            return {"whipsaw_symbols": [], "worst_offenders": [], "round_trips": [], "summary": {}}

        # 按品种分组
        by_symbol: Dict[str, List[TradeRecord]] = defaultdict(list)
        for t in trades:
            by_symbol[t.symbol].append(t)

        whipsaw_symbols = []
        all_round_trips = []
        symbol_analyses = {}

        for symbol, sym_trades in by_symbol.items():
            analysis = self._analyze_symbol_sequence(symbol, sym_trades)
            symbol_analyses[symbol] = analysis
            if analysis["direction_flips"] >= self.FLIP_THRESHOLD:
                whipsaw_symbols.append(analysis)
            all_round_trips.extend(analysis["round_trips"])

        # 按净亏损排序 worst offenders
        worst_offenders = sorted(
            [a for a in symbol_analyses.values() if a["net_pnl"] < -self.NET_LOSS_THRESHOLD],
            key=lambda x: x["net_pnl"]
        )

        return {
            "whipsaw_symbols": whipsaw_symbols,
            "worst_offenders": worst_offenders,
            "round_trips": all_round_trips,
            "symbol_analyses": symbol_analyses,
            "summary": {
                "total_symbols": len(by_symbol),
                "whipsaw_count": len(whipsaw_symbols),
                "total_round_trips": len(all_round_trips),
                "total_whipsaw_loss": sum(a["net_pnl"] for a in whipsaw_symbols if a["net_pnl"] < 0),
            }
        }

    def _analyze_symbol_sequence(self, symbol: str, trades: List[TradeRecord]) -> Dict:
        """单品种序列分析"""
        if not trades:
            return {"symbol": symbol, "direction_flips": 0, "round_trips": [],
                    "net_pnl": 0, "avg_hold_hours": 0, "sequence_str": "", "trade_count": 0}

        # 构建方向序列并统计翻转
        directions = [t.action for t in trades]
        flips = 0
        for i in range(1, len(directions)):
            if directions[i] != directions[i - 1]:
                flips += 1

        # 序列可视化
        seq_parts = []
        for d in directions:
            seq_parts.append("B" if d == "BUY" else "S")
        sequence_str = "→".join(seq_parts)

        # LIFO配对计算来回P&L
        round_trips = []
        stack = []  # [(trade, remaining_units)]
        for t in trades:
            if not stack or t.action == stack[-1][0].action:
                # 同方向，入栈
                stack.append((t, t.units))
            else:
                # 反方向，配对
                while stack and t.units > 0 and stack[-1][0].action != t.action:
                    entry_trade, entry_remaining = stack[-1]
                    matched_units = min(entry_remaining, t.units)

                    if entry_trade.action == "BUY":
                        pnl = (t.price - entry_trade.price) * matched_units
                    else:
                        pnl = (entry_trade.price - t.price) * matched_units

                    # 计算持仓时间
                    try:
                        dt_entry = datetime.strptime(entry_trade.ts, "%Y-%m-%d %H:%M:%S")
                        dt_exit = datetime.strptime(t.ts, "%Y-%m-%d %H:%M:%S")
                        hold_hours = (dt_exit - dt_entry).total_seconds() / 3600
                    except Exception:
                        hold_hours = 0

                    round_trips.append({
                        "symbol": symbol,
                        "entry_action": entry_trade.action,
                        "entry_price": entry_trade.price,
                        "entry_ts": entry_trade.ts,
                        "exit_price": t.price,
                        "exit_ts": t.ts,
                        "units": matched_units,
                        "pnl": round(pnl, 2),
                        "hold_hours": round(hold_hours, 1),
                    })

                    entry_remaining -= matched_units
                    t_units_left = t.units - matched_units
                    t = TradeRecord(ts=t.ts, symbol=t.symbol, action=t.action,
                                    price=t.price, units=t_units_left,
                                    timeframe=t.timeframe, source=t.source)

                    if entry_remaining <= 0:
                        stack.pop()
                    else:
                        stack[-1] = (entry_trade, entry_remaining)

                if t.units > 0:
                    stack.append((t, t.units))

        net_pnl = sum(rt["pnl"] for rt in round_trips)
        avg_hold = sum(rt["hold_hours"] for rt in round_trips) / len(round_trips) if round_trips else 0

        return {
            "symbol": symbol,
            "direction_flips": flips,
            "round_trips": round_trips,
            "net_pnl": round(net_pnl, 2),
            "avg_hold_hours": round(avg_hold, 1),
            "sequence_str": sequence_str,
            "trade_count": len(trades),
        }


# ============================================================
# 2b. PluginSignalTracker - 外挂信号追踪 (v3.3)
# ============================================================

class PluginSignalTracker:
    """
    v3.3: 外挂信号全生命周期追踪

    追踪所有外挂(6+1)产生的BUY/SELL信号及其执行结果:
    - 信号触发 (scan_engine.log)
    - 执行成功/失败 (scan_engine.log + server.log)
    - 阻止原因 (x4过滤/L2空间/P0保护/配额限制/仓位限制/Position Control)

    数据源:
    1. scan_engine.log — 外挂信号触发 + 执行结果 + 阻止原因
    2. server.log — /p0_signal端点执行结果
    3. signal_decisions.jsonl — Position Control决策 (结构化)
    4. plugin_profit_state.json — 外挂利润追踪 (汇总验证)
    """

    # 外挂名映射 (日志中的名称 → 标准名)
    PLUGIN_NAMES = [
        "SuperTrend", "SuperTrend+AV2", "Rob Hoffman", "RobHoffman",
        "VisionPattern", "DoublePattern", "飞云", "MACD背离",
        "缠论BS",
        "移动止损", "移动止盈", "TRAILING_STOP", "TRAILING_BUY",
        "P0-Tracking", "P0-Open", "Chandelier+ZLSMA",
    ]

    # 标准化名称映射
    NAME_MAP = {
        "Rob Hoffman": "RobHoffman",
        "TRAILING_STOP": "移动止损",
        "TRAILING_BUY": "移动止盈",
        "DoublePattern": "VisionPattern",
    }

    # === 信号触发模式 (scan_engine.log) ===
    TRIGGER_PATTERNS = [
        # SuperTrend: [v19] {symbol} SuperTrend触发{action}!
        re.compile(r'\[v19\]\s+(\S+)\s+SuperTrend触发(BUY|SELL)'),
        # SuperTrend+AV2: [v3.550] {symbol} SuperTrend+AV2触发{action}!
        re.compile(r'\[v3\.550\]\s+(\S+)\s+SuperTrend\+AV2触发(BUY|SELL)'),
        # RobHoffman: [v19] {symbol} Rob Hoffman触发{action}!
        re.compile(r'\[v19\]\s+(\S+)\s+Rob Hoffman触发(BUY|SELL)'),
        # VisionPattern: [VisionPattern] {symbol} 形态触发{action}!
        re.compile(r'\[VisionPattern\]\s+(\S+)\s+形态触发(BUY|SELL)'),
        # 飞云: [v19] {symbol} 飞云双突破触发{action}!
        re.compile(r'\[v19\]\s+(\S+)\s+飞云双突破触发(BUY|SELL)'),
        # 缠论BS: [缠论BS] {symbol} {bs_type}触发{action}!
        re.compile(r'\[缠论BS\]\s+(\S+)\s+\S+触发(BUY|SELL)'),
        # MACD-L2 (server.log): [MACD-L2] {symbol} MACD背离 {action} 触发
        re.compile(r'\[MACD-L2\]\s+(\S+)\s+MACD背离\s+(BUY|SELL)\s+触发'),
    ]

    # === 执行成功模式 (scan_engine.log) ===
    EXEC_SUCCESS_PATTERNS = [
        re.compile(r'(\S+)\s+(SuperTrend)\s+执行成功'),
        re.compile(r'(\S+)\s+(SuperTrend\+AV2)\s+执行成功'),
        re.compile(r'(\S+)\s+(RobHoffman)\s+执行成功'),
        re.compile(r'\[(VisionPattern)\]\s+(\S+)\s+执行成功'),
        re.compile(r'(\S+)\s+(飞云)\s+执行成功'),
        re.compile(r'(\S+)\s+(MACD背离)\s+执行成功'),
        re.compile(r'(\S+)\s+(缠论BS)\s+执行成功'),
        # MACD-L2 (server.log): [MACD-L2] {symbol} MACD背离 {action} 执行成功
        re.compile(r'\[MACD-L2\]\s+(\S+)\s+(MACD背离)\s+(?:BUY|SELL)\s+执行成功'),
    ]

    # === 执行失败模式 (scan_engine.log) ===
    EXEC_FAIL_PATTERN = re.compile(
        r'(?:\[(\S+?)\])?\s*(\S+?)[\s:]+未执行\(([^)]*)\)'
    )

    # === 阻止原因模式 (scan_engine.log) ===
    BLOCK_PATTERNS = [
        # x4趋势过滤
        ("x4过滤", re.compile(
            r'(\S+)\s+(SuperTrend|SuperTrend\+AV2|RobHoffman|Rob Hoffman|飞云|MACD背离|缠论BS)\s+(BUY|SELL)\s+被x4过滤'
        )),
        # L2空间阻止
        ("L2阻止", re.compile(
            r'(\S+)\s+(SuperTrend|SuperTrend\+AV2|RobHoffman|Rob Hoffman|双底双顶|VisionPattern|飞云|MACD背离|缠论BS)\s+(BUY|SELL)\s+L2空间阻止'
        )),
        # P0保护
        ("P0保护", re.compile(
            r'(\S+)\s+(SuperTrend|SuperTrend\+AV2|RobHoffman|Rob Hoffman|双底双顶|VisionPattern|飞云|MACD背离|缠论BS)\s+(BUY|SELL)\s+被P0保护'
        )),
        # 配额限制
        ("配额限制", re.compile(
            r'(\S+)\s+(SuperTrend|SuperTrend\+AV2|RobHoffman|Rob Hoffman|双底双顶|VisionPattern|飞云|MACD背离|缠论BS)\s+(BUY|SELL)\s+被限制'
        )),
        # 满仓/空仓 (scan engine level)
        ("仓位限制", re.compile(
            r'\[(\S+)\]\s+(SuperTrend|SuperTrend\+AV2|RobHoffman|Rob Hoffman|双底双顶|VisionPattern|飞云|MACD背离|缠论BS)[：:]\s+(?:满仓|无仓位)'
        )),
        # Position Control拒绝
        ("PC拒绝", re.compile(
            r'\[v(?:19|21\.1)\]\s+(\S+)\s+(SuperTrend|SuperTrend\+AV2|Rob Hoffman|RobHoffman|飞云|MACD背离|缠论BS)\s+(BUY|SELL)\s+→\s+HOLD'
        )),
        # 仓位区间不匹配
        ("仓位区间", re.compile(
            r'(\S+)\s+(SuperTrend|SuperTrend\+AV2|RobHoffman|Rob Hoffman|飞云|MACD背离)\s+(BUY|SELL)[：:]\s+仓位\d+不在激活区间'
        )),
        # MACD-L2 仓位限制 (server.log): [MACD-L2] {symbol} MACD背离 BUY 仓位已满 / SELL 无持仓
        ("MACD-L2仓位", re.compile(
            r'\[MACD-L2\]\s+(\S+)\s+(MACD背离)\s+(BUY|SELL)\s+(?:仓位已满|无持仓)'
        )),
        # MACD-L2 订单失败 (server.log): [MACD-L2] {symbol} MACD背离 {action} 订单发送失败
        ("MACD-L2订单失败", re.compile(
            r'\[MACD-L2\]\s+(\S+)\s+(MACD背离)\s+(BUY|SELL)\s+订单发送失败'
        )),
        # MACD-L2 信号被过滤 (server.log): [MACD-L2] {symbol} MACD背离 被过滤: {reason}
        ("MACD-L2过滤", re.compile(
            r'\[MACD-L2\]\s+(\S+)\s+(MACD背离)\s+被过滤'
        )),
    ]

    # === P0端点结果模式 (server.log) ===
    # v21.18: 兼容新旧格式
    P0_RESULT_PATTERN = re.compile(
        r'(?:\[P0\]\s+处理完成:\s+executed=(True|False),\s+reason=(.*)|\[P0完成\]\s+(\S+)\s+(BUY|SELL)\s+executed=(True|False)\s+reason=(.*))'
    )
    P0_DEDUP_PATTERN = re.compile(
        r'\[P0\]\s+去重:\s+(\S+)\s+(BUY|SELL)'
    )
    P0_FULL_PATTERN = re.compile(
        r'\[P0\]\s+(?:加密货币|美股|)(\S*)\s*满仓\((\d)/\d\).*跳过(买入|卖出)'
    )
    # v21.18: 新增P0检测模式
    P0_RECEIVE_PATTERN = re.compile(
        r'\[P0收到\]\s+(\S+)\s+(BUY|SELL)\s+(\S+)'
    )
    P0_DAILY_LIMIT_PATTERN = re.compile(
        r'\[P0限次\]\s+(\S+)\s+(BUY|SELL)\s+今日已发送(\d+)次'
    )
    P0_POS_MISMATCH_PATTERN = re.compile(
        r'\[v21\.18\]\[仓位偏差\]\s+(\S+)\s+(BUY|SELL):\s+scan=(\d+)\s+server=(\d+)'
    )
    P0_COOLDOWN_PATTERN = re.compile(
        r'\[v21\.18\]\s+(\S+)\s+(?:移动止损|移动止盈)\s+(BUY|SELL)\s+→\s+冷却中'
    )

    def __init__(self):
        # {plugin: {symbol: {"triggered": n, "executed": n, "failed": n, "blocked": {reason: n}}}}
        self.stats: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(lambda: {
            "triggered": 0, "executed": 0, "failed": 0,
            "blocked": defaultdict(int),
            "details": [],
        }))
        # P0端点级别统计
        self.p0_stats = {
            "dedup": 0, "full_position": 0, "executed": 0, "failed": 0,
            "received": 0, "daily_limit": 0, "pos_mismatch": 0, "cooldown": 0,  # v21.18
        }

    def _normalize_plugin(self, name: str) -> str:
        """标准化外挂名"""
        return self.NAME_MAP.get(name, name)

    def _normalize_symbol(self, sym: str) -> str:
        """标准化品种名 (去除-USD后缀等)"""
        return sym.replace("-USD", "USDC") if "-USD" in sym else sym

    def parse(self, log_lines: List[str]) -> Dict:
        """解析所有日志行, 提取外挂信号数据"""

        for line in log_lines:
            # 1. 信号触发
            for pat in self.TRIGGER_PATTERNS:
                m = pat.search(line)
                if m:
                    groups = m.groups()
                    if "[VisionPattern]" in line:
                        symbol, action = groups[0], groups[1]
                        plugin = "VisionPattern"
                    else:
                        symbol, action = groups[0], groups[1]
                        # 从pattern推断plugin名
                        if "SuperTrend+AV2" in line:
                            plugin = "SuperTrend+AV2"
                        elif "SuperTrend" in line:
                            plugin = "SuperTrend"
                        elif "Rob Hoffman" in line:
                            plugin = "RobHoffman"
                        elif "飞云" in line:
                            plugin = "飞云"
                        elif "MACD-L2" in line or "MACD背离" in line:
                            plugin = "MACD背离"
                        elif "缠论BS" in line:
                            plugin = "缠论BS"
                        else:
                            plugin = "未知"

                    plugin = self._normalize_plugin(plugin)
                    symbol = self._normalize_symbol(symbol)
                    self.stats[plugin][symbol]["triggered"] += 1

                    ts_m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', line)
                    ts = ts_m.group(1) if ts_m else ""
                    self.stats[plugin][symbol]["details"].append({
                        "time": ts, "action": action, "event": "triggered",
                    })
                    break  # 一行只匹配一个trigger pattern

            # 2. 执行成功
            for pat in self.EXEC_SUCCESS_PATTERNS:
                m = pat.search(line)
                if m:
                    groups = m.groups()
                    if "VisionPattern" in line:
                        plugin, symbol = groups[0], groups[1]
                    else:
                        symbol, plugin = groups[0], groups[1]
                    plugin = self._normalize_plugin(plugin)
                    symbol = self._normalize_symbol(symbol)
                    self.stats[plugin][symbol]["executed"] += 1
                    break

            # 3. 执行失败 (未执行)
            m = self.EXEC_FAIL_PATTERN.search(line)
            if m:
                bracket_name, sym_or_plugin, reason = m.groups()
                # 识别plugin和symbol
                plugin = bracket_name or sym_or_plugin
                symbol = sym_or_plugin if bracket_name else extract_symbol(line)
                plugin = self._normalize_plugin(plugin)
                symbol = self._normalize_symbol(symbol)
                self.stats[plugin][symbol]["failed"] += 1
                self.stats[plugin][symbol]["blocked"]["执行失败"] += 1

            # 4. 阻止原因
            for reason_name, pat in self.BLOCK_PATTERNS:
                m = pat.search(line)
                if m:
                    groups = m.groups()
                    if len(groups) >= 3:
                        symbol, plugin, action = groups[0], groups[1], groups[2]
                    else:
                        symbol, plugin = groups[0], groups[1]
                    plugin = self._normalize_plugin(plugin)
                    symbol = self._normalize_symbol(symbol)
                    self.stats[plugin][symbol]["blocked"][reason_name] += 1
                    break

            # 5. P0端点去重
            m = self.P0_DEDUP_PATTERN.search(line)
            if m:
                self.p0_stats["dedup"] += 1

            # 6. P0满仓
            m = self.P0_FULL_PATTERN.search(line)
            if m:
                self.p0_stats["full_position"] += 1

            # 7. P0端点结果 (v21.18: 兼容新旧格式)
            m = self.P0_RESULT_PATTERN.search(line)
            if m:
                # 旧格式: group(1)=True/False; 新格式: group(5)=True/False
                _exec_str = m.group(1) or m.group(5)
                executed = _exec_str == "True"
                if executed:
                    self.p0_stats["executed"] += 1
                else:
                    self.p0_stats["failed"] += 1

            # 8-11. v21.18: 新增P0检测模式
            if self.P0_RECEIVE_PATTERN.search(line):
                self.p0_stats["received"] += 1
            if self.P0_DAILY_LIMIT_PATTERN.search(line):
                self.p0_stats["daily_limit"] += 1
            if self.P0_POS_MISMATCH_PATTERN.search(line):
                self.p0_stats["pos_mismatch"] += 1
            if self.P0_COOLDOWN_PATTERN.search(line):
                self.p0_stats["cooldown"] += 1

        return self._build_summary()

    def _build_summary(self) -> Dict:
        """构建汇总数据"""
        summary = {
            "plugins": {},
            "p0_stats": dict(self.p0_stats),
            "total_triggered": 0,
            "total_executed": 0,
            "total_blocked": 0,
        }

        for plugin, symbols in self.stats.items():
            p_data = {"triggered": 0, "executed": 0, "blocked": 0, "by_symbol": {}, "block_reasons": defaultdict(int)}
            for sym, data in symbols.items():
                triggered = data["triggered"]
                executed = data["executed"]
                blocked_total = sum(data["blocked"].values())
                p_data["triggered"] += triggered
                p_data["executed"] += executed
                p_data["blocked"] += blocked_total
                p_data["by_symbol"][sym] = {
                    "triggered": triggered,
                    "executed": executed,
                    "blocked": blocked_total,
                    "block_reasons": dict(data["blocked"]),
                }
                for reason, count in data["blocked"].items():
                    p_data["block_reasons"][reason] += count

            p_data["block_reasons"] = dict(p_data["block_reasons"])
            summary["plugins"][plugin] = p_data
            summary["total_triggered"] += p_data["triggered"]
            summary["total_executed"] += p_data["executed"]
            summary["total_blocked"] += p_data["blocked"]

        return summary

    def parse_signal_decisions(self, filepath: str = "logs/signal_decisions.jsonl", date_str: str = None) -> Dict:
        """解析signal_decisions.jsonl结构化数据 (补充PC决策)"""
        result = {"total": 0, "allowed": 0, "rejected": 0, "by_plugin": defaultdict(lambda: {"allowed": 0, "rejected": 0})}
        if not os.path.exists(filepath):
            return dict(result)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if date_str and date_str not in entry.get("ts", ""):
                        continue
                    result["total"] += 1
                    plugin = entry.get("signal_source", "未知")
                    if entry.get("allowed"):
                        result["allowed"] += 1
                        result["by_plugin"][plugin]["allowed"] += 1
                    else:
                        result["rejected"] += 1
                        result["by_plugin"][plugin]["rejected"] += 1
        except Exception:
            pass
        result["by_plugin"] = dict(result["by_plugin"])
        return dict(result)

    def load_profit_state(self, filepath: str = "plugin_profit_state.json", date_str: str = None) -> Dict:
        """加载plugin_profit_state.json作为交叉验证"""
        data = safe_json_read(filepath)
        if not data:
            return {}
        daily = data.get("daily_stats", {})
        if date_str and date_str in daily:
            return daily[date_str]
        return {}

    @staticmethod
    def compute_plugin_pnl(trades: list) -> Dict:
        """P0-3: 计算每个外挂/来源的入场和出场盈亏贡献

        入场归因: 当plugin X触发BUY后, 后续SELL是否盈利 → X的入场能力
        出场归因: 当plugin X触发SELL时, 这笔交易是否盈利 → X的出场能力

        Returns:
            {"entries": {source: {count, wins, losses, win_rate, avg_pnl_pct, total_pnl_pct}},
             "exits":   {source: {...}},
             "pairs":   [{symbol, buy_ts, sell_ts, buy_price, sell_price, pnl_pct, buy_source, sell_source}]}
        """
        by_symbol: Dict[str, list] = defaultdict(list)
        for t in trades:
            by_symbol[t.symbol].append(t)

        entry_stats: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})
        exit_stats: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "total_pnl": 0.0})
        all_pairs: list = []

        for symbol, sym_trades in by_symbol.items():
            buy_stack: list = []
            for trade in sym_trades:
                if trade.action == "BUY":
                    buy_stack.append(trade)
                elif trade.action == "SELL" and buy_stack:
                    buy_trade = buy_stack.pop()
                    if buy_trade.price <= 0:
                        continue
                    pnl_pct = (trade.price - buy_trade.price) / buy_trade.price * 100

                    buy_src = buy_trade.source or "L2"
                    sell_src = trade.source or "L2"

                    # 入场归因
                    entry_stats[buy_src]["count"] += 1
                    entry_stats[buy_src]["total_pnl"] += pnl_pct
                    if pnl_pct > 0:
                        entry_stats[buy_src]["wins"] += 1
                    else:
                        entry_stats[buy_src]["losses"] += 1

                    # 出场归因
                    exit_stats[sell_src]["count"] += 1
                    exit_stats[sell_src]["total_pnl"] += pnl_pct
                    if pnl_pct > 0:
                        exit_stats[sell_src]["wins"] += 1
                    else:
                        exit_stats[sell_src]["losses"] += 1

                    all_pairs.append({
                        "symbol": symbol,
                        "buy_ts": buy_trade.ts, "sell_ts": trade.ts,
                        "buy_price": round(buy_trade.price, 4),
                        "sell_price": round(trade.price, 4),
                        "pnl_pct": round(pnl_pct, 2),
                        "buy_source": buy_src, "sell_source": sell_src,
                    })

        def _summarize(stats_dict):
            out = {}
            for src, d in stats_dict.items():
                wr = d["wins"] / d["count"] * 100 if d["count"] else 0
                avg = d["total_pnl"] / d["count"] if d["count"] else 0
                out[src] = {
                    "count": d["count"], "wins": d["wins"], "losses": d["losses"],
                    "win_rate": round(wr, 1),
                    "avg_pnl_pct": round(avg, 2),
                    "total_pnl_pct": round(d["total_pnl"], 2),
                }
            return out

        return {
            "entries": _summarize(entry_stats),
            "exits": _summarize(exit_stats),
            "pairs": all_pairs,
        }


# ============================================================
# 2c-1. DataQualityChecker - 数据质量/API/指标/校准器检测 (v3.4)
# ============================================================

class DataQualityChecker:
    """
    v3.4: 数据质量与系统健康检测器

    检测5大类问题:
    1. 数据质量 - K线不足/缓存过期/无效K线/无历史数据
    2. API故障 - yfinance超时/Coinbase错误/后台更新失败
    3. 指标计算失败 - Vegas/MACD/Donchian/形态/位置/量能 各自异常
    4. Vision数据质量 - 文件缺失/结果过期/读取失败/时间戳解析失败
    5. 校准器异常 - 加载失败/保存失败/验证器异常
    """

    PATTERNS = {
        # === 1. 数据质量 ===
        "kline_insufficient": re.compile(
            r"K线不足|数据不足|只有\d+根.*不够|lookback.*不足"
        ),
        "no_history_data": re.compile(
            r"无历史数据|no historical data|yfinance\s*无.*数据|返回空"
        ),
        "invalid_candle": re.compile(
            r"无效K线|跳过.*无效|invalid.*candle|无效价格|price.*[<=]\s*0"
        ),
        "cache_expired": re.compile(
            r"OHLCV缓存过期|缓存过期.*\d+\s*小时|缓存过期.*[2-9]\d{2,}min"
        ),
        "cache_parse_error": re.compile(
            r"缓存时间解析失败|cache.*parse.*fail"
        ),

        # === 2. API/数据源故障 ===
        "yfinance_timeout": re.compile(
            r"yfinance超时|yfinance.*timeout|yfinance.*(\d+)\s*[sS秒]"
        ),
        "yfinance_error": re.compile(
            r"yfinance异常|yfinance获取失败|yfinance.*(?:error|exception|Error)"
        ),
        "coinbase_error": re.compile(
            r"Coinbase\s*API\s*(?:HTTP|错误|error|异常)|Coinbase.*(?:fail|超时)"
        ),
        "bg_updater_fail": re.compile(
            r"后台更新失败|后台更新器错误|后台.*OHLCV.*(?:失败|错误|异常)"
        ),
        "preload_fail": re.compile(
            r"预加载失败|预加载异常|预加载.*只有\d+根"
        ),

        # === 3. 指标计算失败 ===
        "indicator_fail_vegas": re.compile(
            r"Vegas\s*EMA.*(?:计算失败|异常|error)"
        ),
        "indicator_fail_macd": re.compile(
            r"MACD.*(?:预加载失败|计算失败|异常)"
        ),
        "indicator_fail_donchian": re.compile(
            r"Donchian.*(?:计算失败|异常)"
        ),
        "indicator_fail_pattern": re.compile(
            r"形态.*(?:计算失败|分计算失败)"
        ),
        "indicator_fail_position": re.compile(
            r"位置.*(?:计算失败|分计算失败)"
        ),
        "indicator_fail_generic": re.compile(
            r"技术指标计算失败|预计算异常|Choppiness.*计算异常"
        ),
        "indicator_fail_cnn": re.compile(
            r"CNN预测失败|CNN预测错误|CNN模型加载失败"
        ),

        # === 4. Vision数据质量 ===
        "vision_file_missing": re.compile(
            r"Vision结果文件不存在|Vision结果不存在"
        ),
        "vision_read_fail": re.compile(
            r"Vision读取失败|Vision读取异常|Vision覆盖检查异常"
        ),
        "vision_ts_parse_fail": re.compile(
            r"Vision时间戳解析失败|Vision.*timestamp.*fail"
        ),
        "vision_stale": re.compile(
            r"Vision\s*results?过期[：:]\s*(\d+)\s*秒前"
        ),

        # === 5. 校准器/验证器异常 ===
        "calibrator_load_fail": re.compile(
            r"(?:HumanDualTrackCalibrator|HUMAN_CALIBRATOR).*加载.*失败"
        ),
        "calibrator_save_fail": re.compile(
            r"(?:HumanDualTrackCalibrator|HUMAN_CALIBRATOR).*保存失败"
        ),
        "validator_fail": re.compile(
            r"REGIME_VALIDATOR.*(?:加载失败|保存失败)|"
            r"V2905_VALIDATOR.*(?:加载失败|保存失败)|"
            r"V2930.*VALIDATOR.*(?:加载失败|保存失败)"
        ),
        "calibrator_low_accuracy": re.compile(
            r"P3_CALIBRATOR.*准确率仅\s*(\d+)%"
        ),

        # === 6. v3.5: P0/P1修复检测 ===
        "current_price_guard": re.compile(
            r'\[v21\.\d+\]\s+\S+\s+current_price无效'
        ),
        "stock_price_fallback": re.compile(
            r'\[v21\.\d+\]\s+\S+\s+获取价格失败\(1m\+current\)'
        ),
        "kline_insufficient_trailing": re.compile(
            r'\[v21\.\d+\]\s+\S+\s+移动止损K线不足'
        ),
        "hard_floor_block": re.compile(
            r'硬底保护:\s+通道位置'
        ),

        # === 7. v21.8: 共识度评分检测 ===
        "consensus_low": re.compile(
            r'\[v21\.8\]\s+\S+\s+\S+\s+共识度.*低共识'
        ),
        "consensus_high": re.compile(
            r'\[v21\.8\]\s+\S+\s+\S+\s+共识度.*高共识'
        ),
        "consensus_contrary": re.compile(
            r'\[v21\.8\]\s+\S+\s+\S+\s+共识度.*逆向'
        ),

        # === 8. v3.653: 论文驱动改善检测 ===
        "tau_filter": re.compile(
            r'\[HUMAN_CALIBRATOR\]\s+(\S+)\s+τ过滤'
        ),
        "view_divergence_raise": re.compile(
            r'\[v3\.653\]\s+视角分歧度=\S+>0\.15'
        ),
        "ema_differentiated": re.compile(
            r'EMA[85]逆势.*(?:加密|美股|crypto|stock)'
        ),

        # === 9. v3.653: OrderFlow 量价分析检测 ===
        "sqs_blocked": re.compile(
            r'\[SQS\].*WOULD_BLOCK'
        ),
        "sqs_passed": re.compile(
            r'\[SQS\].*WOULD_PASS'
        ),
        "sqs_low_quality": re.compile(
            r'\[SQS\].*sqs=0\.0'
        ),
        "vf_reject": re.compile(
            r'\[VF\].*REJECT'
        ),
        "vf_downgrade": re.compile(
            r'\[VF\].*DOWNGRADE'
        ),
        "vf_upgrade": re.compile(
            r'\[VF\].*UPGRADE'
        ),
        "vf_pass": re.compile(
            r'\[VF\].*filter=PASS'
        ),
        "volume_dry": re.compile(
            r'rel_vol=0\.[0-4]'
        ),

        # === 10. v3.654→v3.656: 系统改善观察检测 ===
        "trend_phase_obs": re.compile(
            r'\[v21\.1[02]\]\s+\S+\s+趋势阶段:\s+(INITIAL|MAIN|FINAL)'
        ),
        "time_decay_obs": re.compile(
            r'\[v21\.1[02]\]\s+时间衰减\[观察\]'
        ),
        "regime_window_obs": re.compile(
            r'\[v21\.10\]\s+Regime窗口\[观察\]'
        ),
        "confidence_gate_obs": re.compile(
            r'\[v21\.10\]\s+置信度门控\[观察\]'
        ),
        "phase_rhythm_obs": re.compile(
            r'\[v21\.1[02]\]\s+阶段风险\[观察\]'
        ),
        "data_stale": re.compile(
            r'\[v3\.654\]\s+\S+\s+数据陈旧'
        ),
        "slippage_alert": re.compile(
            r'\[v3\.654\]\s+滑点告警'
        ),
        "breaker_obs": re.compile(
            r'\[v3\.654\]\s+熔断'
        ),
        "n_pattern_exempt": re.compile(
            r'N字豁免'
        ),
        "regime_weight_obs": re.compile(
            r'\[v3\.654\]\s+Regime权重\[观察\]'
        ),

        # === 11. v3.655: 量价增强观察检测 (SYS-025~028) ===
        "trend_health_obs": re.compile(
            r'\[v21\.11\]\s+趋势健康度\[观察\]'
        ),
        "donchian_vol_obs": re.compile(
            r'\[v21\.11\]\s+Donchian量价\[观察\]'
        ),
        "vp_l2_obs": re.compile(
            r'\[v21\.11\]\s+VP\+L2\[观察\]'
        ),
        "vp_stop_anchor_obs": re.compile(
            r'\[v21\.11\]\s+VP止损锚定\[观察\]'
        ),

        # === 12. v3.656: Anti-Whipsaw HOLD带 ===
        "hold_band_suppress": re.compile(
            r'\[v3\.656\]\[(\S+)\]\s+HOLD带降频'
        ),
        "hold_band_info": re.compile(
            r'\[v3\.656\]\[(\S+)\]\s+HOLD带:\s+pos=(\S+)\s+'
        ),
        "hold_band_breakout": re.compile(
            r'\[v3\.656\]\[(\S+)\]\s+唐纳奇中线移动'
        ),
        "hold_band_block": re.compile(
            r'\[v3\.656\]\s+⛔\s+HOLD带拦截\s+\[(\S+)\]'
        ),

        # === 13. v3.657: Vision N字结构 ===
        "vision_n_pattern": re.compile(
            r'\[v3\.657\]\[(\S+)\]\s+Vision N字结构:\s+(UP_N|DOWN_N)'
        ),

        # === 14. KEY-001: N字结构门控 (Phase 3观察) ===
        "n_struct_state": re.compile(
            r'\[N_STRUCT\]\[(\S+)\]\s+state=(\S+)\s+dir=(\S+)'
        ),
        "n_gate_pass": re.compile(
            r'\[N_GATE\]\[(\S+)\]\s+(\w+)\s+.*?→\s+PASS'
        ),
        "n_gate_block": re.compile(
            r'\[N_GATE\]\[(\S+)\]\s+(\w+)\s+.*?→\s+BLOCK'
        ),
        "l1_fractal": re.compile(
            r'\[L1_FRACTAL\]\[(\S+)\]\s+4H:\s+(\d+)个分型'
        ),
        "n_struct_empty": re.compile(
            r'\[N_STRUCT\]\[(\S+)\]\s+4H分型为空'
        ),
        "n_struct_error": re.compile(
            r'\[N_STRUCT\]\[(\S+)\]\s+N字门控记录异常'
        ),
        # === 15. v3.658: 低准确率品种降权 ===
        "low_acc_guard": re.compile(
            r'\[LOW_ACC_GUARD\]\[(\S+)\]\s+缠论准确率=(\S+)<'
        ),
        # === 16. v3.660 KEY-002: 品种自适应数据收集 ===
        "key002_diff": re.compile(
            r'\[KEY-002\]\[(\S+)\]\s+DIFF\s+original=(\S+)\s+actual=(\S+)'
        ),
        "key002_same": re.compile(
            r'\[KEY-002\]\[(\S+)\]\s+SAME\s+original=(\S+)\s+actual=(\S+)'
        ),
        # === 17. v3.660: N字门控实际拦截 (全品种) ===
        "n_gate_block_active": re.compile(
            r'\[N_GATE拦截\]\s+(\S+)\s+.*?src=(\S+)'
        ),
        # === 18. v3.660: Vision N字冲突 (Vision覆盖被N字阻止) ===
        "vision_n_conflict": re.compile(
            r'\[VISION_OVERRIDE\]\[(\S+)\]\s+N字冲突:\s+Vision=(\w+)'
        ),
        # === 19. KEY-002: 外挂智能进化建议 ===
        "plugin_evolve": re.compile(
            r'\[EVOLVE\]\[(\S+)\]\s+(\S+):\s+(TIGHTEN|LOOSEN|HOLD)\s+-\s+(.+)'
        ),
        # === 20. KEY-003: 价值分析模块验证流水 ===
        "key003_validation_module": re.compile(
            r'\[KEY-003\]\[VALIDATION\]\[MODULE\]\s+(T\d{2})\s+(PASS|FAIL)'
        ),
        "key003_validation_summary": re.compile(
            r'\[KEY-003\]\[VALIDATION\]\[SUMMARY\]\s+passed=(\d+)/(\d+)\s+overall=(PASS|FAIL)'
        ),
        "key003_validation_fail": re.compile(
            r'\[KEY-003\]\[VALIDATION\]\[FAIL\]\s+(T\d{2})'
        ),
        # === 21. v3.663: KEY-003 价值分析BUY拦截 ===
        "key003_value_guard": re.compile(
            r'\[KEY-003\]\[VALUE-GUARD\]\[拦截\]\s+(\S+)\s+BUY被拦截'
        ),
        # === 22. KEY-004: 外挂品质事件 ===
        "key004_plugin_event": re.compile(
            r'\[KEY-004\]\[PLUGIN_EVENT\]\s+phase=(\w+)\s+symbol=(\S+)\s+source=(\S+)\s+action=(\w+)\s+executed=(\S+)\s+reason=(.*)'
        ),
        # === 23. KEY-004 T06: 外挂品质治理决策 ===
        "key004_governance": re.compile(
            r'\[KEY-004\]\[GOVERNANCE\]\s+(\S+)\s+外挂(\S+)\s+score=(\S+)\s+→\s*(\S+)'
        ),
        # === 24. KEY-004 T06: N字状态转换事件 ===
        "key004_n_transition": re.compile(
            r'\[KEY-004\]\[N_TRANSITION\]\s+(\S+)\s+(\S+)/(\S+)\s+→\s+(\S+)/(\S+)\s+price=(\S+)'
        ),
        # === 25. KEY-004 T06: N字转换回填评估 ===
        "key004_n_eval": re.compile(
            r'\[KEY-004\]\[N_EVAL\]\s+(\S+)\s+.*outcome=(\w+)'
        ),
        # === 26. KEY-005: 行为金融增强层 ===
        "key005_bfi": re.compile(
            r'\[KEY-005\]\[BFI\]\s+(\S+)\s+action=(\w+)\s+CSI=(\S+)\((\w+)\)\s+HII=(\S+)\((\w+)\)\s+DQS=(\S+)'
        ),
        "key005_dqs_block": re.compile(
            r'\[KEY-005\]\[DQS\]\[BLOCK\]\s+(\S+)\s+(BUY|SELL)'
        ),
        "key005_anchor": re.compile(
            r'\[KEY-005\]\[ANCHOR\]\s+(\S+)\s+nearest=(\S+)\s+dist=(\S+)%\s+strength=(\S+)'
        ),
        "key005_mod": re.compile(
            r'\[KEY-005\]\[MOD\]\s+(\S+)\s+risk=(\S+)\s+conf_mul=(\S+)\s+cap=(\S+)'
        ),
        "key005_debias": re.compile(
            r'\[KEY-005\]\[DEBIAS\]\s+(\S+)\s+score=(\S+)\s+streak=(\S+)\s+anti_cheat=(\S+)'
        ),
        "key005_anticheat_block": re.compile(
            r'\[KEY-005\]\[ANTI-CHEAT\]\[BLOCK\]\s+(\S+)\s+(BUY|SELL)'
        ),
        # === 27. v3.662: N字门控崩盘放行 ===
        "n_gate_pass_crash": re.compile(
            r'\[N_GATE放行\]\s+(\S+)\s+(\w+)\s+src=(\S+):\s+崩盘保护优先'
        ),
        # === 28. v21.17: K线冻结事件 ===
        "bar_freeze_event": re.compile(
            r'\[v21\.\d+\]\s+K线冻结:\s+(BUY|SELL)\s+x(\d+)\s+bar=(\S+)'
        ),
        # === 29. v21.17: N字门控扫描引擎过滤 ===
        "n_gate_scan_filter": re.compile(
            r'\[N_GATE过滤\]\s+(\S+)\s+(BUY|SELL)\s+移动(止盈|止损)\s+跳过'
        ),
        # === 30. v3.660: Signal Gate 微观结构过滤 ===
        "signal_gate_go":    re.compile(r'\[SIGNAL_GATE\](?:\[LAST\])?\s+(\S+)\s+(BUY|SELL)\s+go=True'),
        "signal_gate_nogo":  re.compile(r'\[SIGNAL_GATE\](?:\[LAST\])?\s+(\S+)\s+(BUY|SELL)\s+go=False'),
        "signal_gate_block": re.compile(r'\[SIGNAL_GATE\]\[LAST\]\[拦截\]\s+(\S+)\s+(BUY|SELL)'),
        # === 31. v3.671: FilterChain 三道闸门统计 ===
        # 注: v3.671新格式在passed=False后有struct/size字段，用.*?跳过
        "filter_chain_pass":         re.compile(r'\[FILTER_CHAIN\]\s+(\S+)\s+(BUY|SELL)\s+passed=True'),
        "filter_chain_block_vision": re.compile(r'\[FILTER_CHAIN\]\s+(\S+)\s+(BUY|SELL)\s+passed=False\b.*?\bblocked=vision\b'),
        "filter_chain_block_volume": re.compile(r'\[FILTER_CHAIN\]\s+(\S+)\s+(BUY|SELL)\s+passed=False\b.*?\bblocked=volume\b'),
        "filter_chain_block_micro":  re.compile(r'\[FILTER_CHAIN\]\s+(\S+)\s+(BUY|SELL)\s+passed=False\b.*?\bblocked=micro\b'),
        "filter_chain_block_weight": re.compile(r'\[FILTER_CHAIN\]\s+(\S+)\s+(BUY|SELL)\s+passed=False\b.*?\bblocked=weight\b'),
        "filter_chain_intercept":    re.compile(r'\[FILTER_CHAIN拦截\]\s+(\S+)\s+(BUY|SELL)'),
        "filter_chain_warn":         re.compile(r'\[FILTER_CHAIN\]\[WARN\]'),
        # === 32. v3.671: N字结构外挂信号 ===
        "n_struct_buy":    re.compile(r'\[NStructPlugin\]\s+(\S+)\s+BUY\s+触发'),
        "n_struct_sell":   re.compile(r'\[NStructPlugin\]\s+(\S+)\s+SELL\s+触发'),
        "n_gate_obs":      re.compile(r'\[N_GATE\]\[观察\]\s+(\S+)'),
        # === 33. KEY-007: Vision KNN过滤 ===
        "vision_filter_block": re.compile(
            r'\[VISION_FILTER\]\[拦截\]\s+(\S+)\s+(BUY|SELL):\s+(.*)'
        ),
        "vision_filter_error": re.compile(
            r'\[VISION_FILTER\]\[ERROR\]\s+(\S+):\s+(.*)'
        ),
        "vision_filter_load": re.compile(
            r'\[VISION_FILTER\]\s+模块加载(成功|失败)'
        ),
        # === 34. KEY-007: Plugin KNN查询+抑制 ===
        "plugin_knn_query": re.compile(
            r'\[PLUGIN_KNN\]\s+(\S+)\s+(\S+)\s+(BUY|SELL)\s+→\s+历史胜率([\d.]+)%\s+均收益([\S]+)\s+bias=(\w+)\s+conf=([\d.]+)'
        ),
        "plugin_knn_suppress": re.compile(
            r'\[PLUGIN_KNN\]\[抑制\]\s+(\S+)\s+(\S+)\s+(BUY|SELL)\s+←\s+KNN反向(\w+)'
        ),
        "plugin_knn_bypass": re.compile(
            r'\[PLUGIN_KNN\]\s+(\S+)\s+(\S+)\s+KNN bypass \(低准确率\)'
        ),
        "plugin_knn_knowledge": re.compile(
            r'\[PLUGIN_KNN\]\[知识卡\]\s+(\S+)\s+匹配(\d+)条规则'
        ),
        "plugin_knn_error": re.compile(
            r'\[PLUGIN_KNN\]\s+(?:加载|保存)历史库失败'
        ),
        # === 35. KEY-007: Vision KNN增量更新 ===
        "knn_bootstrap": re.compile(
            r'\[KNN\]\s+(历史库不存在.*bootstrap|bootstrap完成|bootstrap失败|历史库已存在)'
        ),
        "knn_incremental": re.compile(
            r'\[KNN\]\s+(增量更新完成|增量更新失败)'
        ),
        # === 36. GCC-0171: Vision拦截准确率审计 ===
        "vf_eval": re.compile(
            r'\[GCC-0171\]\[VF_EVAL\]\s+(\S+)\s+BLOCK\s+(\w+)\s+→\s+(CORRECT|INCORRECT)'
        ),
        "vf_acc": re.compile(
            r'\[GCC-0171\]\[VF_ACC\]\s+准确率:\s+(.*)'
        ),
        "vf_promote": re.compile(
            r'\[GCC-0171\]\[PROMOTE\]\s+(\S+)\s+Phase(\d)→Phase(\d)'
        ),
        "vf_demote": re.compile(
            r'\[GCC-0171\]\[DEMOTE\]\s+(\S+)\s+Phase(\d)→Phase(\d)'
        ),
        "vf_3day_review": re.compile(
            r'\[GCC-0171\]\[3DAY_REVIEW\]\s+切换:\s+(.*)'
        ),
        # === 37. GCC-0172: BrooksVision形态准确率审计 ===
        "bv_eval": re.compile(
            r'\[GCC-0172\]\[BV_EVAL\]\s+(\S+)\s+(\w+)\s+(\w+)\s+→\s+(CORRECT|INCORRECT|NEUTRAL)'
        ),
        "bv_acc": re.compile(
            r'\[GCC-0172\]\[BV_ACC\]\s+回测完成:\s+(.*)'
        ),
        "bv_gate": re.compile(
            r'\[GCC-0172\]\[BV_GATE\]\s+(\S+)\s+\[(\w+)\]\s+Phase1观察'
        ),
        # === 38. GCC-0173: MACD背离准确率审计 ===
        "macd_acc": re.compile(
            r'\[GCC-0173\]\[MACD_ACC\]\s+回测完成:\s+(.*)'
        ),
        "macd_gate": re.compile(
            r'\[GCC-0173\]\[MACD_GATE\]\s+(\S+)\s+(底背离|顶背离)\s+Phase1收紧'
        ),
        # === 39. GCC-0174: 知识卡活化 CardBridge ===
        "card_match": re.compile(
            r'\[CARD-BRIDGE\]\[(\S+)\]\s+因果匹配:\s+(\S+)'
        ),
        "card_distill": re.compile(
            r'\[CARD-BRIDGE\]\[DISTILL\]\s+每日蒸馏完成:\s+(\d+)卡\s+validated=(\d+)\s+flagged=(\d+)'
        ),
        "card_error": re.compile(
            r'\[CARD-BRIDGE\].*(?:异常|调度异常)'
        ),
        "card_phase_gate": re.compile(
            r'\[CARD-BRIDGE\]\[PHASE\]\s+(\S+)\s+(\S+)\s+Phase1收紧'
        ),
        "card_acc_backfill": re.compile(
            r'\[GCC-0174\]\[CARD_ACC\]\s+回填完成:\s+\+(\d+)条'
        ),
        "card_knn_evolve": re.compile(
            r'\[GCC-0174\]\[KNN\]\s+每日知识卡进化完成:\s+(\d+)卡\s+promote=(\d+)\s+demote=(\d+)\s+archive=(\d+)'
        ),
    }

    # v3.5: 提取品种的辅助正则 (含yfinance符号格式)
    _SYMBOL_RE = re.compile(
        r"\b(BTCUSDC|ETHUSDC|SOLUSDC|ZECUSDC|BTC-USD|ETH-USD|SOL-USD|ZEC-USD|TSLA|COIN|AMD|RDDT|RKLB|NBIS|CRWV|HIMS|OPEN|ONDS|PLTR)\b"
    )
    _YF_TO_MAIN = {
        "BTC-USD": "BTCUSDC", "ETH-USD": "ETHUSDC",
        "SOL-USD": "SOLUSDC", "ZEC-USD": "ZECUSDC",
    }

    def check(self, log_lines: List[str], detector: IssueDetector) -> Dict:
        """检查数据质量与系统健康"""
        results = {
            # 1. 数据质量
            "kline_insufficient": 0,
            "no_history_data": 0,
            "invalid_candle": 0,
            "cache_expired": 0,
            "cache_parse_error": 0,
            # 2. API故障
            "yfinance_timeout": 0,
            "yfinance_error": 0,
            "coinbase_error": 0,
            "bg_updater_fail": 0,
            "preload_fail": 0,
            # 3. 指标计算失败
            "indicator_failures": 0,
            "indicator_by_type": defaultdict(int),
            # 4. Vision数据质量
            "vision_file_missing": 0,
            "vision_read_fail": 0,
            "vision_ts_parse_fail": 0,
            "vision_stale": 0,
            "vision_stale_max_age": 0,
            # 5. 校准器异常
            "calibrator_load_fail": 0,
            "calibrator_save_fail": 0,
            "validator_fail": 0,
            "calibrator_low_accuracy": 0,
            # 6. v3.5 P0/P1修复检测
            "current_price_guard": 0,
            "stock_price_fallback": 0,
            "kline_insufficient_trailing": 0,
            "hard_floor_block": 0,
            # 7. v21.8 跨周期共识度
            "consensus_low": 0,
            "consensus_high": 0,
            "consensus_contrary": 0,
            # 8. v3.653 论文驱动改善
            "tau_filter": 0,
            "view_divergence_raise": 0,
            # 9. v3.653 OrderFlow 量价分析
            "sqs_blocked": 0,
            "sqs_passed": 0,
            "sqs_low_quality": 0,
            "vf_reject": 0,
            "vf_downgrade": 0,
            "vf_upgrade": 0,
            "vf_pass": 0,
            "volume_dry": 0,
            # 10. v3.654 系统改善观察
            "trend_phase_obs": 0,
            "trend_phase_by_type": defaultdict(int),  # INITIAL/MAIN/FINAL分计
            "time_decay_obs": 0,
            "regime_window_obs": 0,
            "confidence_gate_obs": 0,
            "phase_rhythm_obs": 0,
            "data_stale": 0,
            "slippage_alert": 0,
            "breaker_obs": 0,
            "n_pattern_exempt": 0,
            "regime_weight_obs": 0,
            # 11. v3.655 量价增强 (SYS-025~028)
            "trend_health_obs": 0,
            "donchian_vol_obs": 0,
            "vp_l2_obs": 0,
            "vp_stop_anchor_obs": 0,
            # 12. v3.656 Anti-Whipsaw HOLD带
            "hold_band_suppress": 0,
            "hold_band_breakout": 0,
            "hold_band_block": 0,  # 发单层拦截次数
            "hold_band_by_pos": defaultdict(int),  # HOLD/ABOVE/BELOW/BREAKOUT
            # 13. v3.657 Vision N字结构
            "vision_n_pattern": 0,
            "vision_n_by_type": defaultdict(int),  # UP_N/DOWN_N
            # 14. KEY-001 N字结构门控
            "n_struct_count": 0,
            "n_struct_by_state": defaultdict(int),  # SIDE/PERFECT_N/UP_BREAK/DOWN_BREAK/PULLBACK/DEEP_PULLBACK
            "n_gate_allowed": 0,
            "n_gate_blocked": 0,
            "n_gate_by_dir": defaultdict(lambda: {"allowed": 0, "blocked": 0}),
            "l1_fractal_count": 0,
            "n_struct_empty": 0,
            "n_struct_error": 0,
            # v3.658: 低准确率品种降权
            "low_acc_guard_count": 0,
            "low_acc_guard_symbols": defaultdict(int),
            # 16. v3.660 KEY-002 品种自适应
            "key002_diff": 0,
            "key002_same": 0,
            "key002_by_symbol": defaultdict(lambda: {"diff": 0, "same": 0}),
            # 17. v3.660 N字门控实际拦截
            "n_gate_block_active": 0,
            "n_gate_block_active_by_symbol": defaultdict(int),
            # 18. v3.660 Vision N字冲突
            "vision_n_conflict": 0,
            "vision_n_conflict_by_symbol": defaultdict(int),
            # 19. KEY-002 外挂智能进化
            "plugin_evolve": 0,
            "plugin_evolve_details": [],
            # 20. KEY-003 价值分析验证
            "key003_validation_module": 0,
            "key003_validation_pass": 0,
            "key003_validation_fail": 0,
            "key003_validation_summary": 0,
            "key003_validation_last": {},
            # 21. KEY-003 价值分析BUY拦截
            "key003_value_guard_block": 0,
            "key003_value_guard_by_symbol": defaultdict(int),
            # 22. KEY-004 外挂品质事件
            "key004_plugin_event": 0,
            "key004_plugin_by_source": defaultdict(lambda: {"dispatch": 0, "response": 0, "error": 0, "executed": 0, "failed": 0}),
            # 23. KEY-004 T06 外挂品质治理
            "key004_governance": 0,
            "key004_gov_decisions": defaultdict(int),  # {DISABLE_CANDIDATE: n, OBSERVE: n, KEEP: n}
            # 24. KEY-004 T06 N字状态转换
            "key004_n_transition": 0,
            "key004_n_transition_by_symbol": defaultdict(int),
            # 25. KEY-004 T06 N字转换评估
            "key004_n_eval": 0,
            "key004_n_eval_outcomes": defaultdict(int),  # {CORRECT: n, INCORRECT: n, NEUTRAL: n}
            # 26. KEY-005 行为金融增强层
            "key005_bfi": 0,
            "key005_dqs_block": 0,
            "key005_by_symbol": defaultdict(lambda: {"bfi": 0, "dqs_block": 0}),
            "key005_csi_state": defaultdict(int),
            "key005_hii_state": defaultdict(int),
            "key005_dqs_sum": 0.0,
            "key005_anchor": 0,
            "key005_anchor_by_symbol": defaultdict(int),
            "key005_mod": 0,
            "key005_mod_by_risk": defaultdict(int),
            "key005_debias": 0,
            "key005_anticheat_block": 0,
            # 27. N字门控崩盘放行
            "n_gate_pass_crash": 0,
            "n_gate_pass_crash_by_symbol": defaultdict(int),
            # 28. K线冻结事件
            "bar_freeze_event": 0,
            "bar_freeze_by_dir": defaultdict(int),
            # 29. N字门控扫描引擎过滤
            "n_gate_scan_filter": 0,
            "n_gate_scan_filter_by_symbol": defaultdict(int),
            # 30. Signal Gate 微观结构过滤
            "signal_gate_go": 0,
            "signal_gate_nogo": 0,
            "signal_gate_block": 0,
            "signal_gate_by_symbol": defaultdict(lambda: {"go": 0, "nogo": 0}),
            # 31. FilterChain 三道闸门 (v3.671: 补weight/warn)
            "filter_chain_pass": 0,
            "filter_chain_block_vision": 0,
            "filter_chain_block_volume": 0,
            "filter_chain_block_micro": 0,
            "filter_chain_block_weight": 0,
            "filter_chain_intercept": 0,
            "filter_chain_warn": 0,
            "filter_chain_by_symbol": defaultdict(lambda: {"pass": 0, "vision": 0, "volume": 0, "micro": 0, "weight": 0}),
            # 32. N字外挂信号 (v3.671)
            "n_struct_buy": 0,
            "n_struct_sell": 0,
            "n_gate_obs": 0,
            # 33. KEY-007: Vision KNN过滤 (S7)
            "vision_filter_block": 0,
            "vision_filter_block_by_symbol": defaultdict(int),
            "vision_filter_error": 0,
            "vision_filter_load_ok": 0,
            "vision_filter_load_fail": 0,
            # 34. KEY-007: Plugin KNN查询+抑制 (S8)
            "plugin_knn_query": 0,
            "plugin_knn_query_by_plugin": defaultdict(lambda: {"total": 0, "buy_agree": 0, "sell_agree": 0, "contrary": 0}),
            "plugin_knn_suppress": 0,
            "plugin_knn_suppress_by_plugin": defaultdict(int),
            "plugin_knn_bypass": 0,
            "plugin_knn_bypass_by_plugin": defaultdict(int),
            "plugin_knn_knowledge": 0,
            "plugin_knn_knowledge_rules_total": 0,
            "plugin_knn_error": 0,
            "plugin_knn_wr_sum": 0.0,
            "plugin_knn_conf_sum": 0.0,
            # 35. KEY-007: Vision KNN维护 (S7)
            "knn_bootstrap": 0,
            "knn_bootstrap_status": "",
            "knn_incremental_ok": 0,
            "knn_incremental_fail": 0,
            # 36. GCC-0171: Vision拦截准确率审计
            "vf_eval_correct": 0,
            "vf_eval_incorrect": 0,
            "vf_eval_by_symbol": defaultdict(lambda: {"correct": 0, "incorrect": 0}),
            "vf_acc_snapshot": "",
            "vf_promote": 0,
            "vf_demote": 0,
            "vf_phase_transitions": [],
            "vf_3day_review": 0,
            # 37. GCC-0172: BrooksVision形态准确率审计
            "bv_eval_correct": 0,
            "bv_eval_incorrect": 0,
            "bv_eval_neutral": 0,
            "bv_eval_by_pattern": defaultdict(lambda: {"correct": 0, "incorrect": 0, "neutral": 0}),
            "bv_gate_blocked": 0,
            "bv_gate_by_pattern": defaultdict(int),
            "bv_acc_snapshot": "",
            # 38. GCC-0173: MACD背离准确率审计
            "macd_gate_blocked": 0,
            "macd_gate_by_type": defaultdict(int),
            "macd_acc_snapshot": "",
            # 39. GCC-0174: 知识卡活化 CardBridge
            "card_match_count": 0,
            "card_match_by_symbol": defaultdict(int),
            "card_match_cards": set(),
            "card_distill_count": 0,
            "card_distill_snapshot": "",
            "card_error_count": 0,
            "card_phase_gate_count": 0,
            "card_phase_gate_by_symbol": defaultdict(int),
            "card_acc_backfill_count": 0,
            "card_acc_backfill_total": 0,
            "card_knn_evolve_count": 0,
            "card_knn_evolve_snapshot": "",
            # 汇总
            "by_symbol": defaultdict(lambda: defaultdict(int)),
            "total_issues": 0,
            "details": [],
        }

        for line in log_lines:
            sym_m = self._SYMBOL_RE.search(line)
            symbol = sym_m.group(1) if sym_m else "UNKNOWN"
            symbol = self._YF_TO_MAIN.get(symbol, symbol)  # v3.5: yfinance→主程序符号

            # --- 1. 数据质量 ---
            if self.PATTERNS["kline_insufficient"].search(line):
                results["kline_insufficient"] += 1
                results["by_symbol"][symbol]["kline_insufficient"] += 1
                detector.add_issue(
                    "WARNING", "DQ_KLINE_INSUFFICIENT", symbol,
                    "K线数据不足: 计算所需K线不够，趋势判断可能不准",
                    line.strip()[:200],
                    "检查OHLCV预加载配置和yfinance连通性"
                )

            if self.PATTERNS["no_history_data"].search(line):
                results["no_history_data"] += 1
                results["by_symbol"][symbol]["no_history_data"] += 1
                detector.add_issue(
                    "CRITICAL", "DQ_NO_DATA", symbol,
                    "无历史数据: 数据源返回空，该品种本周期完全盲飞",
                    line.strip()[:200],
                    "检查yfinance/Coinbase连通性和品种代码"
                )

            if self.PATTERNS["invalid_candle"].search(line):
                results["invalid_candle"] += 1
                results["by_symbol"][symbol]["invalid_candle"] += 1

            if self.PATTERNS["cache_expired"].search(line):
                results["cache_expired"] += 1
                results["by_symbol"][symbol]["cache_expired"] += 1

            if self.PATTERNS["cache_parse_error"].search(line):
                results["cache_parse_error"] += 1

            # --- 2. API/数据源故障 ---
            if self.PATTERNS["yfinance_timeout"].search(line):
                results["yfinance_timeout"] += 1
                results["by_symbol"][symbol]["api_error"] += 1
                detector.add_issue(
                    "WARNING", "DQ_YFINANCE_TIMEOUT", symbol,
                    "yfinance超时: 数据获取延迟，可能使用过期缓存",
                    line.strip()[:200],
                    "检查网络连通性和yfinance服务状态"
                )

            if self.PATTERNS["yfinance_error"].search(line):
                results["yfinance_error"] += 1
                results["by_symbol"][symbol]["api_error"] += 1
                detector.add_issue(
                    "CRITICAL", "DQ_YFINANCE_ERROR", symbol,
                    "yfinance异常: 数据获取失败，该品种可能使用过期数据",
                    line.strip()[:200],
                    "检查yfinance版本和API限流"
                )

            if self.PATTERNS["coinbase_error"].search(line):
                results["coinbase_error"] += 1
                results["by_symbol"][symbol]["api_error"] += 1
                detector.add_issue(
                    "CRITICAL", "DQ_COINBASE_ERROR", symbol,
                    "Coinbase API错误: 加密货币数据获取失败",
                    line.strip()[:200],
                    "检查Coinbase API密钥和网络"
                )

            if self.PATTERNS["bg_updater_fail"].search(line):
                results["bg_updater_fail"] += 1
                results["by_symbol"][symbol]["bg_fail"] += 1
                detector.add_issue(
                    "WARNING", "DQ_BG_UPDATER_FAIL", symbol,
                    "后台OHLCV更新失败: 数据可能不是最新的",
                    line.strip()[:200],
                    "检查后台更新器线程健康状态"
                )

            if self.PATTERNS["preload_fail"].search(line):
                results["preload_fail"] += 1
                results["by_symbol"][symbol]["preload_fail"] += 1

            # --- 3. 指标计算失败 ---
            for ind_key in ("indicator_fail_vegas", "indicator_fail_macd",
                            "indicator_fail_donchian", "indicator_fail_pattern",
                            "indicator_fail_position", "indicator_fail_generic",
                            "indicator_fail_cnn"):
                if self.PATTERNS[ind_key].search(line):
                    ind_name = ind_key.replace("indicator_fail_", "")
                    results["indicator_failures"] += 1
                    results["indicator_by_type"][ind_name] += 1
                    results["by_symbol"][symbol]["indicator_fail"] += 1
                    detector.add_issue(
                        "WARNING", "DQ_INDICATOR_FAIL", symbol,
                        f"指标计算失败({ind_name}): 评分缺少该维度，决策可能偏差",
                        line.strip()[:200],
                        f"检查{ind_name}指标计算输入数据和边界条件"
                    )
                    break  # 一行只匹配一种指标失败

            # --- 4. Vision数据质量 ---
            if self.PATTERNS["vision_file_missing"].search(line):
                results["vision_file_missing"] += 1
                results["by_symbol"][symbol]["vision_issue"] += 1
                detector.add_issue(
                    "WARNING", "DQ_VISION_MISSING", symbol,
                    "Vision结果文件缺失: 无法使用Vision辅助判断",
                    line.strip()[:200],
                    "检查vision_analyzer.py是否正常运行并生成结果"
                )

            if self.PATTERNS["vision_read_fail"].search(line):
                results["vision_read_fail"] += 1
                results["by_symbol"][symbol]["vision_issue"] += 1

            if self.PATTERNS["vision_ts_parse_fail"].search(line):
                results["vision_ts_parse_fail"] += 1

            stale_m = self.PATTERNS["vision_stale"].search(line)
            if stale_m:
                results["vision_stale"] += 1
                results["by_symbol"][symbol]["vision_issue"] += 1
                try:
                    age = int(stale_m.group(1))
                    results["vision_stale_max_age"] = max(results["vision_stale_max_age"], age)
                except (ValueError, IndexError):
                    pass

            # --- 5. 校准器/验证器异常 ---
            if self.PATTERNS["calibrator_load_fail"].search(line):
                results["calibrator_load_fail"] += 1
                detector.add_issue(
                    "CRITICAL", "DQ_CALIBRATOR_FAIL", symbol,
                    "校准器加载失败: 准确率追踪中断，无法选择最佳算法",
                    line.strip()[:200],
                    "检查human_dual_track.json完整性"
                )

            if self.PATTERNS["calibrator_save_fail"].search(line):
                results["calibrator_save_fail"] += 1
                detector.add_issue(
                    "WARNING", "DQ_CALIBRATOR_SAVE", symbol,
                    "校准器保存失败: 准确率数据可能丢失",
                    line.strip()[:200],
                    "检查磁盘空间和文件权限"
                )

            if self.PATTERNS["validator_fail"].search(line):
                results["validator_fail"] += 1

            acc_m = self.PATTERNS["calibrator_low_accuracy"].search(line)
            if acc_m:
                results["calibrator_low_accuracy"] += 1
                try:
                    acc_val = int(acc_m.group(1))
                    detector.add_issue(
                        "WARNING", "DQ_LOW_ACCURACY", symbol,
                        f"校准器准确率过低({acc_val}%): 决策矩阵可能需要调整",
                        line.strip()[:200],
                        "检查P3决策矩阵对应条目的有效性"
                    )
                except (ValueError, IndexError):
                    pass

            # --- 6. v3.5 P0/P1修复检测 ---
            if self.PATTERNS["current_price_guard"].search(line):
                results["current_price_guard"] += 1
                results["by_symbol"][symbol]["current_price_guard"] += 1

            if self.PATTERNS["stock_price_fallback"].search(line):
                results["stock_price_fallback"] += 1
                results["by_symbol"][symbol]["stock_price_fallback"] += 1

            if self.PATTERNS["kline_insufficient_trailing"].search(line):
                results["kline_insufficient_trailing"] += 1
                results["by_symbol"][symbol]["kline_insufficient_trailing"] += 1

            if self.PATTERNS["hard_floor_block"].search(line):
                results["hard_floor_block"] += 1
                results["by_symbol"][symbol]["hard_floor_block"] += 1

            # --- 7. v21.8 跨周期共识度 ---
            if self.PATTERNS["consensus_low"].search(line):
                results["consensus_low"] += 1
                results["by_symbol"][symbol]["consensus_low"] += 1
            if self.PATTERNS["consensus_high"].search(line):
                results["consensus_high"] += 1
                results["by_symbol"][symbol]["consensus_high"] += 1
            if self.PATTERNS["consensus_contrary"].search(line):
                results["consensus_contrary"] += 1
                results["by_symbol"][symbol]["consensus_contrary"] += 1

            # --- 8. v3.653 论文驱动改善 ---
            if self.PATTERNS["tau_filter"].search(line):
                results["tau_filter"] += 1
                results["by_symbol"][symbol]["tau_filter"] += 1

            if self.PATTERNS["view_divergence_raise"].search(line):
                results["view_divergence_raise"] += 1
                results["by_symbol"][symbol]["view_divergence_raise"] += 1

            # --- 9. v3.653 OrderFlow 量价分析 ---
            if self.PATTERNS["sqs_blocked"].search(line):
                results["sqs_blocked"] += 1
                results["by_symbol"][symbol]["sqs_blocked"] += 1
            if self.PATTERNS["sqs_passed"].search(line):
                results["sqs_passed"] += 1
                results["by_symbol"][symbol]["sqs_passed"] += 1
            if self.PATTERNS["sqs_low_quality"].search(line):
                results["sqs_low_quality"] += 1
                results["by_symbol"][symbol]["sqs_low_quality"] += 1
            if self.PATTERNS["vf_reject"].search(line):
                results["vf_reject"] += 1
                results["by_symbol"][symbol]["vf_reject"] += 1
            if self.PATTERNS["vf_downgrade"].search(line):
                results["vf_downgrade"] += 1
                results["by_symbol"][symbol]["vf_downgrade"] += 1
            if self.PATTERNS["vf_upgrade"].search(line):
                results["vf_upgrade"] += 1
                results["by_symbol"][symbol]["vf_upgrade"] += 1
            if self.PATTERNS["vf_pass"].search(line):
                results["vf_pass"] += 1
                results["by_symbol"][symbol]["vf_pass"] += 1
            if self.PATTERNS["volume_dry"].search(line):
                results["volume_dry"] += 1
                results["by_symbol"][symbol]["volume_dry"] += 1

            # --- 10. v3.654 系统改善观察 ---
            tp_m = self.PATTERNS["trend_phase_obs"].search(line)
            if tp_m:
                results["trend_phase_obs"] += 1
                results["trend_phase_by_type"][tp_m.group(1)] += 1
            if self.PATTERNS["time_decay_obs"].search(line):
                results["time_decay_obs"] += 1
            if self.PATTERNS["regime_window_obs"].search(line):
                results["regime_window_obs"] += 1
            if self.PATTERNS["confidence_gate_obs"].search(line):
                results["confidence_gate_obs"] += 1
            if self.PATTERNS["phase_rhythm_obs"].search(line):
                results["phase_rhythm_obs"] += 1
            if self.PATTERNS["data_stale"].search(line):
                results["data_stale"] += 1
            if self.PATTERNS["slippage_alert"].search(line):
                results["slippage_alert"] += 1
            if self.PATTERNS["breaker_obs"].search(line):
                results["breaker_obs"] += 1
            if self.PATTERNS["n_pattern_exempt"].search(line):
                results["n_pattern_exempt"] += 1
            if self.PATTERNS["regime_weight_obs"].search(line):
                results["regime_weight_obs"] += 1

            # --- 11. v3.655 量价增强观察 (SYS-025~028) ---
            if self.PATTERNS["trend_health_obs"].search(line):
                results["trend_health_obs"] += 1
            if self.PATTERNS["donchian_vol_obs"].search(line):
                results["donchian_vol_obs"] += 1
            if self.PATTERNS["vp_l2_obs"].search(line):
                results["vp_l2_obs"] += 1
            if self.PATTERNS["vp_stop_anchor_obs"].search(line):
                results["vp_stop_anchor_obs"] += 1

            # --- 12. v3.656 Anti-Whipsaw HOLD带 ---
            if self.PATTERNS["hold_band_suppress"].search(line):
                results["hold_band_suppress"] += 1
                results["by_symbol"][symbol]["hold_band_suppress"] += 1
            hb_m = self.PATTERNS["hold_band_info"].search(line)
            if hb_m:
                results["hold_band_by_pos"][hb_m.group(2)] += 1
            if self.PATTERNS["hold_band_breakout"].search(line):
                results["hold_band_breakout"] += 1
                results["by_symbol"][symbol]["hold_band_breakout"] += 1
            if self.PATTERNS["hold_band_block"].search(line):
                results["hold_band_block"] += 1
                results["by_symbol"][symbol]["hold_band_block"] += 1

            # --- 13. v3.657 Vision N字结构 ---
            np_m = self.PATTERNS["vision_n_pattern"].search(line)
            if np_m:
                results["vision_n_pattern"] += 1
                results["vision_n_by_type"][np_m.group(2)] += 1
                results["by_symbol"][np_m.group(1)]["vision_n_pattern"] += 1

            # --- 14. KEY-001 N字结构门控 ---
            ns_m = self.PATTERNS["n_struct_state"].search(line)
            if ns_m:
                results["n_struct_count"] += 1
                results["n_struct_by_state"][ns_m.group(2)] += 1
                results["by_symbol"][ns_m.group(1)]["n_struct"] += 1

            ng_pass = self.PATTERNS["n_gate_pass"].search(line)
            if ng_pass:
                _ng_sym, _ng_dir = ng_pass.group(1), ng_pass.group(2)
                results["n_gate_allowed"] += 1
                results["n_gate_by_dir"][_ng_dir]["allowed"] += 1
                results["by_symbol"][_ng_sym]["n_gate_allowed"] += 1

            ng_block = self.PATTERNS["n_gate_block"].search(line)
            if ng_block:
                _ng_sym, _ng_dir = ng_block.group(1), ng_block.group(2)
                results["n_gate_blocked"] += 1
                results["n_gate_by_dir"][_ng_dir]["blocked"] += 1
                results["by_symbol"][_ng_sym]["n_gate_blocked"] += 1

            if self.PATTERNS["l1_fractal"].search(line):
                results["l1_fractal_count"] += 1

            if self.PATTERNS["n_struct_empty"].search(line):
                results["n_struct_empty"] += 1

            if self.PATTERNS["n_struct_error"].search(line):
                results["n_struct_error"] += 1

            # --- 15. v3.658 低准确率品种降权 ---
            lag_m = self.PATTERNS["low_acc_guard"].search(line)
            if lag_m:
                results["low_acc_guard_count"] += 1
                results["low_acc_guard_symbols"][lag_m.group(1)] += 1

            # --- 16. v3.660 KEY-002 品种自适应 ---
            k2d_m = self.PATTERNS["key002_diff"].search(line)
            if k2d_m:
                results["key002_diff"] += 1
                results["key002_by_symbol"][k2d_m.group(1)]["diff"] += 1
            k2s_m = self.PATTERNS["key002_same"].search(line)
            if k2s_m:
                results["key002_same"] += 1
                results["key002_by_symbol"][k2s_m.group(1)]["same"] += 1

            # --- 17. v3.660 N字门控实际拦截 ---
            ngba_m = self.PATTERNS["n_gate_block_active"].search(line)
            if ngba_m:
                results["n_gate_block_active"] += 1
                results["n_gate_block_active_by_symbol"][ngba_m.group(1)] += 1

            # --- 18. v3.660 Vision N字冲突 ---
            vnc_m = self.PATTERNS["vision_n_conflict"].search(line)
            if vnc_m:
                results["vision_n_conflict"] += 1
                results["vision_n_conflict_by_symbol"][vnc_m.group(1)] += 1

            # --- 19. KEY-002 外挂智能进化 ---
            evo_m = self.PATTERNS["plugin_evolve"].search(line)
            if evo_m:
                results["plugin_evolve"] += 1
                results["plugin_evolve_details"].append({
                    "symbol": evo_m.group(1),
                    "plugin": evo_m.group(2),
                    "action": evo_m.group(3),
                    "reason": evo_m.group(4)[:80],
                })

            # --- 20. KEY-003 验证流水 ---
            k3m = self.PATTERNS["key003_validation_module"].search(line)
            if k3m:
                task_id, status = k3m.group(1), k3m.group(2)
                results["key003_validation_module"] += 1
                if status == "PASS":
                    results["key003_validation_pass"] += 1
                else:
                    results["key003_validation_fail"] += 1
                results["key003_validation_last"][task_id] = status

            k3s = self.PATTERNS["key003_validation_summary"].search(line)
            if k3s:
                passed_count = int(k3s.group(1))
                total_count = int(k3s.group(2))
                overall = k3s.group(3)
                results["key003_validation_summary"] += 1
                results["key003_validation_last"]["summary"] = {
                    "passed": passed_count,
                    "total": total_count,
                    "overall": overall,
                }

            k3f = self.PATTERNS["key003_validation_fail"].search(line)
            if k3f:
                detector.add_issue(
                    "WARNING", "KEY003_VALIDATION_FAIL", "KEY-003",
                    f"KEY-003模块验证失败: {k3f.group(1)}",
                    line.strip()[:200],
                    "运行 value_analysis/main.py validate 定位失败模块并修复"
                )

            # --- 21. KEY-003 价值分析BUY拦截 ---
            k3vg = self.PATTERNS["key003_value_guard"].search(line)
            if k3vg:
                vg_sym = k3vg.group(1)
                results["key003_value_guard_block"] += 1
                results["key003_value_guard_by_symbol"][vg_sym] += 1

            # --- 22. KEY-004 外挂品质事件 ---
            k4e = self.PATTERNS["key004_plugin_event"].search(line)
            if k4e:
                _phase = k4e.group(1)
                _source = k4e.group(3)
                _executed = str(k4e.group(5)).lower()
                results["key004_plugin_event"] += 1
                bucket = results["key004_plugin_by_source"][_source]
                bucket[_phase] = bucket.get(_phase, 0) + 1
                if _executed in ("true", "1"):
                    bucket["executed"] += 1
                elif _executed in ("false", "0"):
                    bucket["failed"] += 1

            # --- 23. KEY-004 T06 外挂品质治理 ---
            k4g = self.PATTERNS["key004_governance"].search(line)
            if k4g:
                _k4g_decision = k4g.group(4)
                results["key004_governance"] += 1
                results["key004_gov_decisions"][_k4g_decision] += 1

            # --- 24. KEY-004 T06 N字状态转换 ---
            k4nt = self.PATTERNS["key004_n_transition"].search(line)
            if k4nt:
                _k4nt_sym = k4nt.group(1)
                results["key004_n_transition"] += 1
                results["key004_n_transition_by_symbol"][_k4nt_sym] += 1

            # --- 25. KEY-004 T06 N字转换评估 ---
            k4ne = self.PATTERNS["key004_n_eval"].search(line)
            if k4ne:
                _k4ne_outcome = k4ne.group(2)
                results["key004_n_eval"] += 1
                results["key004_n_eval_outcomes"][_k4ne_outcome] += 1

            # --- 26. KEY-005 行为金融增强层 ---
            k5b = self.PATTERNS["key005_bfi"].search(line)
            if k5b:
                _k5_sym = k5b.group(1)
                _k5_state = k5b.group(4)
                _k5_hii_state = k5b.group(6)
                try:
                    _k5_dqs = float(k5b.group(7))
                except Exception:
                    _k5_dqs = 0.0
                results["key005_bfi"] += 1
                results["key005_by_symbol"][_k5_sym]["bfi"] += 1
                results["key005_csi_state"][_k5_state] += 1
                results["key005_hii_state"][_k5_hii_state] += 1
                results["key005_dqs_sum"] += _k5_dqs

            k5blk = self.PATTERNS["key005_dqs_block"].search(line)
            if k5blk:
                _k5_sym = k5blk.group(1)
                results["key005_dqs_block"] += 1
                results["key005_by_symbol"][_k5_sym]["dqs_block"] += 1

            k5a = self.PATTERNS["key005_anchor"].search(line)
            if k5a:
                _k5_sym = k5a.group(1)
                results["key005_anchor"] += 1
                results["key005_anchor_by_symbol"][_k5_sym] += 1

            k5m = self.PATTERNS["key005_mod"].search(line)
            if k5m:
                _risk = k5m.group(2)
                results["key005_mod"] += 1
                results["key005_mod_by_risk"][_risk] += 1

            k5d = self.PATTERNS["key005_debias"].search(line)
            if k5d:
                results["key005_debias"] += 1

            k5ab = self.PATTERNS["key005_anticheat_block"].search(line)
            if k5ab:
                results["key005_anticheat_block"] += 1

            # --- 27. N字门控崩盘放行 ---
            _npc = self.PATTERNS["n_gate_pass_crash"].search(line)
            if _npc:
                results["n_gate_pass_crash"] += 1
                results["n_gate_pass_crash_by_symbol"][_npc.group(1)] += 1

            # --- 28. K线冻结事件 ---
            _bfe = self.PATTERNS["bar_freeze_event"].search(line)
            if _bfe:
                results["bar_freeze_event"] += 1
                results["bar_freeze_by_dir"][_bfe.group(1)] += 1

            # --- 29. N字门控扫描引擎过滤 ---
            _nsf = self.PATTERNS["n_gate_scan_filter"].search(line)
            if _nsf:
                results["n_gate_scan_filter"] += 1
                results["n_gate_scan_filter_by_symbol"][_nsf.group(1)] += 1

            # --- 30. Signal Gate 微观结构过滤 ---
            _sg_go = self.PATTERNS["signal_gate_go"].search(line)
            if _sg_go:
                results["signal_gate_go"] += 1
                results["signal_gate_by_symbol"][_sg_go.group(1)]["go"] += 1
            _sg_nogo = self.PATTERNS["signal_gate_nogo"].search(line)
            if _sg_nogo:
                results["signal_gate_nogo"] += 1
                results["signal_gate_by_symbol"][_sg_nogo.group(1)]["nogo"] += 1
            _sg_blk = self.PATTERNS["signal_gate_block"].search(line)
            if _sg_blk:
                results["signal_gate_block"] += 1

            # --- 31. FilterChain 三道闸门 (v3.671) ---
            _fc_pass = self.PATTERNS["filter_chain_pass"].search(line)
            if _fc_pass:
                results["filter_chain_pass"] += 1
                results["filter_chain_by_symbol"][_fc_pass.group(1)]["pass"] += 1
            _fc_bv = self.PATTERNS["filter_chain_block_vision"].search(line)
            if _fc_bv:
                results["filter_chain_block_vision"] += 1
                results["filter_chain_by_symbol"][_fc_bv.group(1)]["vision"] += 1
            _fc_bvol = self.PATTERNS["filter_chain_block_volume"].search(line)
            if _fc_bvol:
                results["filter_chain_block_volume"] += 1
                results["filter_chain_by_symbol"][_fc_bvol.group(1)]["volume"] += 1
            _fc_bm = self.PATTERNS["filter_chain_block_micro"].search(line)
            if _fc_bm:
                results["filter_chain_block_micro"] += 1
                results["filter_chain_by_symbol"][_fc_bm.group(1)]["micro"] += 1
            _fc_bw = self.PATTERNS["filter_chain_block_weight"].search(line)
            if _fc_bw:
                results["filter_chain_block_weight"] += 1
                results["filter_chain_by_symbol"][_fc_bw.group(1)]["weight"] += 1
            _fc_int = self.PATTERNS["filter_chain_intercept"].search(line)
            if _fc_int:
                results["filter_chain_intercept"] += 1
            if self.PATTERNS["filter_chain_warn"].search(line):
                results["filter_chain_warn"] += 1
            # --- 32. N字外挂信号 ---
            _ns_b = self.PATTERNS["n_struct_buy"].search(line)
            if _ns_b:
                results["n_struct_buy"] += 1
            _ns_s = self.PATTERNS["n_struct_sell"].search(line)
            if _ns_s:
                results["n_struct_sell"] += 1
            if self.PATTERNS["n_gate_obs"].search(line):
                results["n_gate_obs"] += 1

            # --- 33. KEY-007: Vision KNN过滤 ---
            _vfb = self.PATTERNS["vision_filter_block"].search(line)
            if _vfb:
                results["vision_filter_block"] += 1
                results["vision_filter_block_by_symbol"][_vfb.group(1)] += 1
            if self.PATTERNS["vision_filter_error"].search(line):
                results["vision_filter_error"] += 1
                detector.add_issue(
                    "WARNING", "KEY007_VISION_FILTER_ERROR", symbol,
                    "Vision过滤异常: KNN+形态过滤模块报错",
                    line.strip()[:200],
                    "检查vision_pre_filter.py模块健康状态和knn_history.npz完整性"
                )
            _vfl = self.PATTERNS["vision_filter_load"].search(line)
            if _vfl:
                if _vfl.group(1) == "成功":
                    results["vision_filter_load_ok"] += 1
                else:
                    results["vision_filter_load_fail"] += 1
                    detector.add_issue(
                        "CRITICAL", "KEY007_VISION_FILTER_LOAD_FAIL", "SYSTEM",
                        "Vision过滤模块加载失败: 全品种Vision KNN不可用",
                        line.strip()[:200],
                        "检查vision_pre_filter.py导入和knn_history.npz文件"
                    )

            # --- 34. KEY-007: Plugin KNN查询+抑制 ---
            _pkq = self.PATTERNS["plugin_knn_query"].search(line)
            if _pkq:
                _pk_sym, _pk_plugin, _pk_action, _pk_wr, _pk_ret, _pk_bias, _pk_conf = _pkq.groups()
                results["plugin_knn_query"] += 1
                _pk_bucket = results["plugin_knn_query_by_plugin"][_pk_plugin]
                _pk_bucket["total"] += 1
                # 判断KNN bias是否与action一致
                if (_pk_action == "BUY" and _pk_bias == "BUY") or \
                   (_pk_action == "SELL" and _pk_bias == "SELL"):
                    _pk_bucket["buy_agree" if _pk_action == "BUY" else "sell_agree"] += 1
                elif _pk_bias in ("BUY", "SELL") and _pk_bias != _pk_action:
                    _pk_bucket["contrary"] += 1
                try:
                    results["plugin_knn_wr_sum"] += float(_pk_wr)
                    results["plugin_knn_conf_sum"] += float(_pk_conf)
                except ValueError:
                    pass

            _pks = self.PATTERNS["plugin_knn_suppress"].search(line)
            if _pks:
                results["plugin_knn_suppress"] += 1
                results["plugin_knn_suppress_by_plugin"][_pks.group(2)] += 1

            _pkb = self.PATTERNS["plugin_knn_bypass"].search(line)
            if _pkb:
                results["plugin_knn_bypass"] += 1
                results["plugin_knn_bypass_by_plugin"][_pkb.group(2)] += 1

            _pkk = self.PATTERNS["plugin_knn_knowledge"].search(line)
            if _pkk:
                results["plugin_knn_knowledge"] += 1
                try:
                    results["plugin_knn_knowledge_rules_total"] += int(_pkk.group(2))
                except ValueError:
                    pass

            if self.PATTERNS["plugin_knn_error"].search(line):
                results["plugin_knn_error"] += 1
                detector.add_issue(
                    "CRITICAL", "KEY007_PLUGIN_KNN_ERROR", "SYSTEM",
                    "Plugin KNN历史库读写失败: 特征记录/查询可能丢失",
                    line.strip()[:200],
                    "检查state/plugin_knn_history.npz文件完整性和磁盘空间"
                )

            # --- 35. KEY-007: Vision KNN维护 ---
            _kbs = self.PATTERNS["knn_bootstrap"].search(line)
            if _kbs:
                results["knn_bootstrap"] += 1
                results["knn_bootstrap_status"] = _kbs.group(1)
            _kinc = self.PATTERNS["knn_incremental"].search(line)
            if _kinc:
                if "完成" in _kinc.group(1):
                    results["knn_incremental_ok"] += 1
                else:
                    results["knn_incremental_fail"] += 1
                    detector.add_issue(
                        "WARNING", "KEY007_KNN_UPDATE_FAIL", "SYSTEM",
                        "KNN增量更新失败: Vision KNN历史库未能刷新",
                        line.strip()[:200],
                        "检查yfinance连通性和knn_history.npz文件锁"
                    )

            # --- 36. GCC-0171: Vision拦截准确率审计 ---
            _vfe = self.PATTERNS["vf_eval"].search(line)
            if _vfe:
                _vfe_sym, _vfe_act, _vfe_result = _vfe.group(1), _vfe.group(2), _vfe.group(3)
                if _vfe_result == "CORRECT":
                    results["vf_eval_correct"] += 1
                    results["vf_eval_by_symbol"][_vfe_sym]["correct"] += 1
                else:
                    results["vf_eval_incorrect"] += 1
                    results["vf_eval_by_symbol"][_vfe_sym]["incorrect"] += 1

            _vfa = self.PATTERNS["vf_acc"].search(line)
            if _vfa:
                results["vf_acc_snapshot"] = _vfa.group(1)

            _vfp = self.PATTERNS["vf_promote"].search(line)
            if _vfp:
                results["vf_promote"] += 1
                results["vf_phase_transitions"].append(
                    f"{_vfp.group(1)} P{_vfp.group(2)}→P{_vfp.group(3)} PROMOTE")

            _vfd = self.PATTERNS["vf_demote"].search(line)
            if _vfd:
                results["vf_demote"] += 1
                results["vf_phase_transitions"].append(
                    f"{_vfd.group(1)} P{_vfd.group(2)}→P{_vfd.group(3)} DEMOTE")

            if self.PATTERNS["vf_3day_review"].search(line):
                results["vf_3day_review"] += 1

            # --- 37. GCC-0172: BrooksVision形态准确率审计 ---
            _bve = self.PATTERNS["bv_eval"].search(line)
            if _bve:
                _bve_sym, _bve_pat, _bve_sig, _bve_res = (
                    _bve.group(1), _bve.group(2), _bve.group(3), _bve.group(4))
                if _bve_res == "CORRECT":
                    results["bv_eval_correct"] += 1
                    results["bv_eval_by_pattern"][_bve_pat]["correct"] += 1
                elif _bve_res == "INCORRECT":
                    results["bv_eval_incorrect"] += 1
                    results["bv_eval_by_pattern"][_bve_pat]["incorrect"] += 1
                else:
                    results["bv_eval_neutral"] += 1
                    results["bv_eval_by_pattern"][_bve_pat]["neutral"] += 1

            _bva = self.PATTERNS["bv_acc"].search(line)
            if _bva:
                results["bv_acc_snapshot"] = _bva.group(1)

            _bvg = self.PATTERNS["bv_gate"].search(line)
            if _bvg:
                results["bv_gate_blocked"] += 1
                results["bv_gate_by_pattern"][_bvg.group(2)] += 1

            # --- 38. GCC-0173: MACD背离准确率审计 ---
            _mga = self.PATTERNS["macd_acc"].search(line)
            if _mga:
                results["macd_acc_snapshot"] = _mga.group(1)

            _mgg = self.PATTERNS["macd_gate"].search(line)
            if _mgg:
                results["macd_gate_blocked"] += 1
                results["macd_gate_by_type"][_mgg.group(2)] += 1

            # --- 39. GCC-0174: 知识卡活化 CardBridge ---
            _cbm = self.PATTERNS.get("card_match")
            if _cbm:
                _cbm_hit = _cbm.search(line)
                if _cbm_hit:
                    results["card_match_count"] += 1
                    results["card_match_by_symbol"][_cbm_hit.group(1)] += 1
                    results["card_match_cards"].add(_cbm_hit.group(2))

            _cbd = self.PATTERNS.get("card_distill")
            if _cbd and _cbd.search(line):
                results["card_distill_count"] += 1
                _cbd_m = _cbd.search(line)
                results["card_distill_snapshot"] = _cbd_m.group(0) if _cbd_m else ""

            _cbe = self.PATTERNS.get("card_error")
            if _cbe and _cbe.search(line):
                results["card_error_count"] += 1

            _cpg = self.PATTERNS.get("card_phase_gate")
            if _cpg:
                _cpg_hit = _cpg.search(line)
                if _cpg_hit:
                    results["card_phase_gate_count"] += 1
                    results["card_phase_gate_by_symbol"][_cpg_hit.group(1)] += 1

            _cab = self.PATTERNS.get("card_acc_backfill")
            if _cab:
                _cab_hit = _cab.search(line)
                if _cab_hit:
                    results["card_acc_backfill_count"] += 1
                    results["card_acc_backfill_total"] += int(_cab_hit.group(1))

            _cke = self.PATTERNS.get("card_knn_evolve")
            if _cke:
                _cke_hit = _cke.search(line)
                if _cke_hit:
                    results["card_knn_evolve_count"] += 1
                    results["card_knn_evolve_snapshot"] = f"total={_cke_hit.group(1)} promote={_cke_hit.group(2)} demote={_cke_hit.group(3)} archive={_cke_hit.group(4)}"

        # 汇总
        results["total_issues"] = (
            results["kline_insufficient"] + results["no_history_data"] +
            results["invalid_candle"] + results["cache_expired"] +
            results["yfinance_timeout"] + results["yfinance_error"] +
            results["coinbase_error"] + results["bg_updater_fail"] +
            results["preload_fail"] + results["indicator_failures"] +
            results["vision_file_missing"] + results["vision_read_fail"] +
            results["vision_stale"] + results["calibrator_load_fail"] +
            results["calibrator_save_fail"] + results["validator_fail"] +
            results["calibrator_low_accuracy"] +
            results["current_price_guard"] + results["stock_price_fallback"] +
            results["key003_validation_fail"]
        )

        # convert defaultdicts to regular dicts for JSON serialization
        results["card_match_cards"] = list(results.get("card_match_cards", set()))
        results["card_match_by_symbol"] = dict(results.get("card_match_by_symbol", {}))
        results["card_phase_gate_by_symbol"] = dict(results.get("card_phase_gate_by_symbol", {}))
        results["by_symbol"] = {k: dict(v) for k, v in results["by_symbol"].items()}
        results["indicator_by_type"] = dict(results["indicator_by_type"])
        results["bv_eval_by_pattern"] = {k: dict(v) for k, v in results["bv_eval_by_pattern"].items()}
        results["bv_gate_by_pattern"] = dict(results["bv_gate_by_pattern"])
        results["macd_gate_by_type"] = dict(results["macd_gate_by_type"])

        detector.stats["dq_total_issues"] = results["total_issues"]
        detector.stats["dq_api_errors"] = (
            results["yfinance_timeout"] + results["yfinance_error"] +
            results["coinbase_error"]
        )
        detector.stats["dq_data_issues"] = (
            results["kline_insufficient"] + results["no_history_data"] +
            results["invalid_candle"] + results["cache_expired"]
        )
        detector.stats["dq_indicator_failures"] = results["indicator_failures"]
        detector.stats["dq_vision_issues"] = (
            results["vision_file_missing"] + results["vision_read_fail"] +
            results["vision_stale"]
        )
        detector.stats["dq_calibrator_issues"] = (
            results["calibrator_load_fail"] + results["calibrator_save_fail"] +
            results["validator_fail"]
        )
        detector.stats["key003_validation_fail"] = results["key003_validation_fail"]
        detector.stats["key003_validation_pass"] = results["key003_validation_pass"]
        detector.stats["key003_value_guard_block"] = results["key003_value_guard_block"]
        detector.stats["key003_value_guard_by_symbol"] = dict(results["key003_value_guard_by_symbol"])
        detector.stats["key004_plugin_event"] = results["key004_plugin_event"]
        detector.stats["key004_governance"] = results["key004_governance"]
        detector.stats["key004_gov_decisions"] = dict(results["key004_gov_decisions"])
        detector.stats["key004_n_transition"] = results["key004_n_transition"]
        detector.stats["key004_n_transition_by_symbol"] = dict(results["key004_n_transition_by_symbol"])
        detector.stats["key004_n_eval"] = results["key004_n_eval"]
        detector.stats["key004_n_eval_outcomes"] = dict(results["key004_n_eval_outcomes"])
        detector.stats["key005_bfi"] = results["key005_bfi"]
        detector.stats["key005_dqs_block"] = results["key005_dqs_block"]
        detector.stats["key005_csi_state"] = dict(results["key005_csi_state"])
        detector.stats["key005_hii_state"] = dict(results["key005_hii_state"])
        detector.stats["key005_anchor"] = results["key005_anchor"]
        detector.stats["key005_mod"] = results["key005_mod"]
        detector.stats["key005_debias"] = results["key005_debias"]
        detector.stats["key005_anticheat_block"] = results["key005_anticheat_block"]
        # KEY-007: Vision KNN + Plugin KNN
        detector.stats["key007_vision_filter_block"] = results["vision_filter_block"]
        detector.stats["key007_vision_filter_error"] = results["vision_filter_error"]
        detector.stats["key007_plugin_knn_query"] = results["plugin_knn_query"]
        detector.stats["key007_plugin_knn_suppress"] = results["plugin_knn_suppress"]
        detector.stats["key007_plugin_knn_bypass"] = results["plugin_knn_bypass"]
        detector.stats["key007_plugin_knn_error"] = results["plugin_knn_error"]
        detector.stats["key007_knn_incremental_ok"] = results["knn_incremental_ok"]
        detector.stats["key007_knn_incremental_fail"] = results["knn_incremental_fail"]
        # GCC-0171: Vision拦截审计
        detector.stats["gcc0171_vf_eval_correct"] = results["vf_eval_correct"]
        detector.stats["gcc0171_vf_eval_incorrect"] = results["vf_eval_incorrect"]
        detector.stats["gcc0171_vf_promote"] = results["vf_promote"]
        detector.stats["gcc0171_vf_demote"] = results["vf_demote"]
        # GCC-0172
        detector.stats["gcc0172_bv_eval_correct"] = results["bv_eval_correct"]
        detector.stats["gcc0172_bv_eval_incorrect"] = results["bv_eval_incorrect"]
        detector.stats["gcc0172_bv_gate_blocked"] = results["bv_gate_blocked"]
        # GCC-0173
        detector.stats["gcc0173_macd_gate_blocked"] = results["macd_gate_blocked"]
        # GCC-0174: CardBridge
        detector.stats["gcc0174_card_match"] = results["card_match_count"]
        detector.stats["gcc0174_card_distill"] = results["card_distill_count"]
        detector.stats["gcc0174_card_error"] = results["card_error_count"]
        detector.stats["gcc0174_card_phase_gate"] = results["card_phase_gate_count"]
        detector.stats["gcc0174_card_knn_evolve"] = results["card_knn_evolve_count"]
        detector.stats["gcc0174_card_acc_backfill"] = results["card_acc_backfill_total"]

        return results


# ============================================================
# 2c. SignalValidator - 信号事后验证 + 被拒信号回测 (P1-1 + P1-2)
# ============================================================

class SignalValidator:
    """
    P1-1: 趋势预测事后验证 — L1说UP之后价格实际涨了吗?
    P1-2: 被拒信号回测 — 如果没拒绝, 现在是赚还是亏?

    数据源: yfinance 1小时K线 (批量获取, 缓存复用)
    """

    # 趋势切换事件模式 (current_trend或big_trend发生方向变化)
    TREND_CHANGE_PATTERN = re.compile(
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}).*?'
        r'(\w+(?:USDC)?)\s+.*?'
        r'(?:current_trend|趋势)[=:→]\s*'
        r'(UP|DOWN)\s*→\s*(UP|DOWN|SIDE)'
    )

    # 备用: 直接读取趋势判断结果
    TREND_RESULT_PATTERN = re.compile(
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}).*?'
        r'\[(\w+(?:USDC)?)\].*?'
        r'current_trend[=:]\s*(UP|DOWN)'
    )

    LOOKAHEAD_HOURS = [4, 8]

    def __init__(self):
        self._price_cache: Dict[str, Any] = {}

    def _fetch_hourly_prices(self, symbol: str, date_str: str):
        """获取1小时OHLCV数据, 覆盖分析日±1天, 结果缓存"""
        cache_key = f"{symbol}_{date_str}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        try:
            import yfinance as yf
            yf_symbol = YFINANCE_SYMBOL_MAP.get(symbol, symbol)

            report_date = datetime.strptime(date_str, "%Y-%m-%d")
            start = (report_date - timedelta(days=2)).strftime('%Y-%m-%d')
            end = (report_date + timedelta(days=2)).strftime('%Y-%m-%d')

            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(start=start, end=end, interval="1h")
            if df.empty:
                self._price_cache[cache_key] = None
                return None

            if df.index.tz is not None:
                df.index = df.index.tz_convert('America/New_York').tz_localize(None)

            self._price_cache[cache_key] = df
            return df
        except Exception as e:
            logger.warning(f"[SignalValidator] 获取{symbol}价格失败: {e}")
            self._price_cache[cache_key] = None
            return None

    def _get_price_at(self, df, target_dt: datetime) -> Optional[float]:
        """获取最接近目标时间的收盘价 (2小时容差)"""
        if df is None or df.empty:
            return None
        try:
            diffs = abs(df.index - target_dt)
            nearest_idx = diffs.argmin()
            if diffs[nearest_idx].total_seconds() < 7200:
                return float(df.iloc[nearest_idx]['Close'])
        except Exception:
            pass
        return None

    def validate_trend_changes(self, log_lines: List[str], date_str: str,
                                detector: IssueDetector) -> Dict:
        """P1-1: 验证趋势切换预测的准确性

        对每个趋势切换事件, 检查后续4h/8h价格走势是否符合预测方向.
        """
        changes: List[Dict] = []

        for line in log_lines:
            if date_str and date_str not in line:
                continue
            m = self.TREND_CHANGE_PATTERN.search(line)
            if m:
                ts_str, symbol, old_trend, new_trend = m.groups()
                if old_trend != new_trend and new_trend in ("UP", "DOWN"):
                    changes.append({"ts": ts_str, "symbol": symbol, "old": old_trend, "new": new_trend})

        results = {
            "total_changes": len(changes),
            "validated": 0, "correct": 0, "incorrect": 0,
            "accuracy": None,
            "details": [],
        }

        for change in changes:
            symbol = change["symbol"]
            df = self._fetch_hourly_prices(symbol, date_str)
            if df is None:
                continue

            try:
                change_dt = datetime.strptime(change["ts"], "%Y-%m-%d %H:%M")
            except Exception:
                continue

            price_at = self._get_price_at(df, change_dt)
            if price_at is None or price_at <= 0:
                continue

            for hours in self.LOOKAHEAD_HOURS:
                future_dt = change_dt + timedelta(hours=hours)
                future_price = self._get_price_at(df, future_dt)
                if future_price is None:
                    continue

                pct = (future_price - price_at) / price_at * 100
                predicted_up = change["new"] == "UP"
                actual_up = pct > 0
                is_correct = (predicted_up == actual_up)

                results["validated"] += 1
                if is_correct:
                    results["correct"] += 1
                else:
                    results["incorrect"] += 1
                    detector.add_issue(
                        "WARNING", "TREND_PREDICTION_WRONG", symbol,
                        f"趋势切换{change['old']}→{change['new']}后{hours}h价格{'涨' if actual_up else '跌'}{abs(pct):.1f}% (预测错误)",
                        f"ts={change['ts']}",
                        "检查趋势切换灵敏度或确认条件"
                    )

                results["details"].append({
                    "ts": change["ts"], "symbol": symbol,
                    "prediction": change["new"],
                    "hours": hours,
                    "price_change_pct": round(pct, 2),
                    "correct": is_correct,
                })
                break  # 用第一个可用的lookahead

        if results["validated"] > 0:
            results["accuracy"] = round(results["correct"] / results["validated"] * 100, 1)

        return results

    def backtest_rejected_signals(self, rejected_signals: Dict[str, List[Dict]],
                                    date_str: str,
                                    detector: IssueDetector) -> Dict:
        """P1-2: 被拒信号回测 — 计算如果执行了的假设盈亏

        对每个被拒信号:
        1. 获取拒绝时刻价格
        2. 获取4h后价格
        3. 计算假设盈亏
        4. 分类: 错过盈利 / 成功避损 / 影响微小
        """
        results = {
            "total_backtested": 0,
            "would_profit": 0, "would_loss": 0,
            "missed_profit_pct": 0.0,
            "avoided_loss_pct": 0.0,
            "profit_rate": None,
            "by_reason": defaultdict(lambda: {"count": 0, "profit": 0, "loss": 0}),
            "details": [],
        }

        for symbol, signals in rejected_signals.items():
            df = self._fetch_hourly_prices(symbol, date_str)
            if df is None:
                continue

            for sig in signals:
                ts_str = sig.get("time", "")
                if not ts_str or len(ts_str) < 10:
                    continue

                try:
                    sig_dt = datetime.strptime(ts_str[:16], "%Y-%m-%d %H:%M")
                except Exception:
                    continue

                entry_price = self._get_price_at(df, sig_dt)
                if entry_price is None or entry_price <= 0:
                    continue

                exit_dt = sig_dt + timedelta(hours=4)
                exit_price = self._get_price_at(df, exit_dt)
                if exit_price is None:
                    continue

                original = sig.get("original_signal", "")
                if original == "BUY":
                    hyp_pnl = (exit_price - entry_price) / entry_price * 100
                elif original == "SELL":
                    hyp_pnl = (entry_price - exit_price) / entry_price * 100
                else:
                    continue

                results["total_backtested"] += 1
                reason = sig.get("reason", "未知")

                if hyp_pnl > 0.3:
                    results["would_profit"] += 1
                    results["missed_profit_pct"] += hyp_pnl
                    results["by_reason"][reason]["profit"] += 1
                elif hyp_pnl < -0.3:
                    results["would_loss"] += 1
                    results["avoided_loss_pct"] += abs(hyp_pnl)
                    results["by_reason"][reason]["loss"] += 1
                results["by_reason"][reason]["count"] += 1

                verdict = "错过盈利" if hyp_pnl > 0.5 else "避免亏损" if hyp_pnl < -0.5 else "影响微小"
                results["details"].append({
                    "symbol": symbol, "ts": ts_str,
                    "signal": original, "reason": reason,
                    "entry": round(entry_price, 2),
                    "exit_4h": round(exit_price, 2),
                    "hyp_pnl_pct": round(hyp_pnl, 2),
                    "verdict": verdict,
                })

                if hyp_pnl > 1.5:
                    detector.add_issue(
                        "WARNING", "MISSED_PROFIT", symbol,
                        f"被拒{original}错过+{hyp_pnl:.1f}% (原因:{reason})",
                        f"ts={ts_str}, 入场{entry_price:.2f}→4h后{exit_price:.2f}",
                        "检查过滤条件是否过严"
                    )
                elif hyp_pnl < -2.0:
                    detector.add_issue(
                        "INFO", "AVOIDED_LOSS", symbol,
                        f"被拒{original}避免{abs(hyp_pnl):.1f}%亏损 (原因:{reason})",
                        f"ts={ts_str}",
                        "过滤条件有效"
                    )

        if results["total_backtested"] > 0:
            results["profit_rate"] = round(
                results["would_profit"] / results["total_backtested"] * 100, 1
            )

        results["by_reason"] = dict(results["by_reason"])
        return results


# ============================================================
# 3. RhythmAnalyzer - 买卖节奏分析
# ============================================================

class RhythmAnalyzer:
    """
    买卖节奏分析器 - 基于pos_in_channel评估交易质量

    核心原则:
    1. 底部买入: pos_in_channel < 0.2 时的BUY才是好买点
    2. 顶部卖出: pos_in_channel > 0.8 时的SELL才是好卖点
    3. x4大周期方向确认

    评分标准:
    - BUY: EXCELLENT(<0.2), GOOD(0.2-0.4), NEUTRAL(0.4-0.6), POOR(0.6-0.8), TERRIBLE(>0.8)
    - SELL: EXCELLENT(>0.8), GOOD(0.6-0.8), NEUTRAL(0.4-0.6), POOR(0.2-0.4), TERRIBLE(<0.2)
    """

    QUALITY_SCORES = {
        TradeQuality.EXCELLENT: 100,
        TradeQuality.GOOD: 75,
        TradeQuality.NEUTRAL: 50,
        TradeQuality.POOR: 25,
        TradeQuality.TERRIBLE: 0,
    }

    def __init__(self):
        self.state_data: Dict = {}

    def load_state(self, filepath: str) -> Dict:
        """加载state.json"""
        self.state_data = safe_json_read(filepath) or {}
        return self.state_data

    def enrich_trades_with_position(self, trades: List[TradeRecord], log_lines: List[str] = None) -> List[TradeRecord]:
        """为交易记录添加pos_in_channel信息
        v3.5: 优先用trade JSON中的值, 日志/state仅作回退"""
        # 从日志中提取pos_in_channel
        pos_cache = {}
        if log_lines:
            for line in log_lines:
                # v3.5: 放宽regex — 匹配所有symbol(含股票TSLA等)
                match = re.search(r'(\S+).*pos_in_channel[=:]\s*([\d.]+)', line)
                if match:
                    symbol, pos = match.groups()
                    try:
                        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', line)
                        if ts_match:
                            key = f"{symbol}_{ts_match.group(1)}"
                            pos_cache[key] = float(pos)
                    except:
                        pass

        for trade in trades:
            # v3.5: 已从trade JSON读取的值优先 (v3.652主程序写入)
            if trade.pos_in_channel is not None:
                continue
            # 回退: 尝试从日志缓存匹配
            key = f"{trade.symbol}_{trade.ts[:16]}"
            if key in pos_cache:
                trade.pos_in_channel = pos_cache[key]
            # 回退: 尝试从state获取近似位置
            elif trade.symbol in self.state_data:
                symbol_state = self.state_data[trade.symbol]
                if "prev_sr" in symbol_state and symbol_state["prev_sr"]:
                    sr = symbol_state["prev_sr"]
                    support = sr.get("support", 0)
                    resistance = sr.get("resistance", 0)
                    if resistance > support:
                        trade.pos_in_channel = (trade.price - support) / (resistance - support)
                        trade.pos_in_channel = max(0, min(1, trade.pos_in_channel))

        return trades

    def evaluate_trade_quality(self, trade: TradeRecord) -> TradeQuality:
        """评估单笔交易质量"""
        pos = trade.pos_in_channel
        if pos is None:
            return TradeQuality.NEUTRAL

        if trade.action == "BUY":
            if pos < 0.2:
                return TradeQuality.EXCELLENT
            elif pos < 0.4:
                return TradeQuality.GOOD
            elif pos < 0.6:
                return TradeQuality.NEUTRAL
            elif pos < 0.8:
                return TradeQuality.POOR
            else:
                return TradeQuality.TERRIBLE

        elif trade.action == "SELL":
            if pos > 0.8:
                return TradeQuality.EXCELLENT
            elif pos > 0.6:
                return TradeQuality.GOOD
            elif pos >= 0.4:
                return TradeQuality.NEUTRAL
            elif pos > 0.2:
                return TradeQuality.POOR
            else:
                return TradeQuality.TERRIBLE

        return TradeQuality.NEUTRAL

    def analyze_rhythm(self, trades: List[TradeRecord], detector: IssueDetector, log_lines: List[str] = None) -> Dict:
        """分析买卖节奏质量"""
        enriched_trades = self.enrich_trades_with_position(trades, log_lines)

        quality_counts = {q: {"buy": 0, "sell": 0} for q in TradeQuality}
        total_buy_score = 0
        total_sell_score = 0
        buy_count = 0
        sell_count = 0
        bad_buys = []
        bad_sells = []

        for trade in enriched_trades:
            quality = self.evaluate_trade_quality(trade)
            trade.quality = quality

            if trade.action == "BUY":
                quality_counts[quality]["buy"] += 1
                total_buy_score += self.QUALITY_SCORES[quality]
                buy_count += 1

                if quality == TradeQuality.TERRIBLE:
                    bad_buys.append(trade)
                    detector.add_issue(
                        "WARNING", "RHYTHM_BAD_BUY", trade.symbol,
                        f"高位买入: BUY@{trade.price:.2f} pos={trade.pos_in_channel:.1%}",
                        f"ts={trade.ts}",
                        "pos > 0.8时买入风险极高，应等待回调"
                    )
                elif quality == TradeQuality.POOR:
                    bad_buys.append(trade)

            elif trade.action == "SELL":
                quality_counts[quality]["sell"] += 1
                total_sell_score += self.QUALITY_SCORES[quality]
                sell_count += 1

                if quality == TradeQuality.TERRIBLE:
                    bad_sells.append(trade)
                    detector.add_issue(
                        "WARNING", "RHYTHM_BAD_SELL", trade.symbol,
                        f"低位卖出: SELL@{trade.price:.2f} pos={trade.pos_in_channel:.1%}",
                        f"ts={trade.ts}",
                        "pos < 0.2时卖出可能过早，应等待反弹"
                    )
                elif quality == TradeQuality.POOR:
                    bad_sells.append(trade)

        avg_buy_score = total_buy_score / buy_count if buy_count else 0
        avg_sell_score = total_sell_score / sell_count if sell_count else 0
        # v3.5: 加权平均 — 按实际交易数量加权, 消除单向日惩罚
        # 旧公式: (avg_buy + avg_sell) / 2 — 只有BUY没SELL时被除以2变成一半分
        total_count = buy_count + sell_count
        overall_score = (total_buy_score + total_sell_score) / total_count if total_count else 0

        # 计算优质交易比例
        excellent_buy = quality_counts[TradeQuality.EXCELLENT]["buy"] + quality_counts[TradeQuality.GOOD]["buy"]
        excellent_sell = quality_counts[TradeQuality.EXCELLENT]["sell"] + quality_counts[TradeQuality.GOOD]["sell"]
        excellent_buy_ratio = excellent_buy / buy_count * 100 if buy_count else 0
        excellent_sell_ratio = excellent_sell / sell_count * 100 if sell_count else 0

        result = {
            "overall_score": round(overall_score, 1),
            "buy_score": round(avg_buy_score, 1),
            "sell_score": round(avg_sell_score, 1),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "excellent_buy_ratio": round(excellent_buy_ratio, 1),
            "excellent_sell_ratio": round(excellent_sell_ratio, 1),
            "quality_breakdown": {
                q.value: {"buy": quality_counts[q]["buy"], "sell": quality_counts[q]["sell"]}
                for q in TradeQuality
            },
            "bad_buys": len(bad_buys),
            "bad_sells": len(bad_sells),
            "trades": enriched_trades,
        }

        # 记录到stats
        detector.stats["rhythm_overall_score"] = result["overall_score"]
        detector.stats["rhythm_excellent_buy_ratio"] = result["excellent_buy_ratio"]
        detector.stats["rhythm_excellent_sell_ratio"] = result["excellent_sell_ratio"]
        detector.stats["rhythm_bad_buys"] = len(bad_buys)
        detector.stats["rhythm_bad_sells"] = len(bad_sells)

        return result


# ============================================================
# 3b. TestingVerifier — TESTING项自动验证闭环 (v3.653)
# ============================================================

class TestingVerifier:
    """
    v3.653: 从improvements.json读取TESTING项, 对照当日日志数据自动判定:
      - PASS: 有明确数值标准且达标
      - FAIL: 有明确数值标准但未达标
      - ACTIVE: 代码在运行(有触发记录), 效果待多天观察
      - INACTIVE: 无触发记录, 可能代码未生效或条件未满足
      - NEED_DATA: 数据不足, 无法判定
    """

    # 验证规则: {improvement_id: {type, check_func_name, target, description}}
    # type: "metric" (有明确数值标准) | "activity" (检测是否活跃)
    VERIFY_RULES = {
        # --- AUDIT层 (有明确PASS/FAIL标准) ---
        "AUD-012": {
            "type": "metric",
            "metric": "current_price_error",
            "op": "<=",
            "target": 5,
            "description": "current_price ERROR应<5次/天(原74次)",
        },
        "AUD-011": {
            "type": "metric",
            "metric": "rhythm_overall_score",
            "op": ">=",
            "target": 50,
            "description": "节奏评分应>50(原42)",
        },
        "AUD-034": {
            "type": "metric",
            "metric": "kline_insufficient_trailing",
            "op": "<=",
            "target": 5,
            "description": "移动止损K线不足应<5次/天(原10次)",
        },
        # --- RESEARCH层 (活跃度检测) ---
        "RES-001": {
            "type": "activity",
            "pattern": "节奏过滤",
            "description": "品种分化阈值: 加密/美股分别拦截",
        },
        "RES-002": {
            "type": "activity",
            "pattern": "Vision过度自信降权",
            "description": "Vision>95%且逆大趋势时降权",
        },
        "RES-003": {
            "type": "activity",
            "pattern": "late_fusion_score|view_divergence",
            "description": "融合诊断数据出现在monitor/日志",
        },
        "RES-004": {
            "type": "activity",
            "pattern": "τ过滤",
            "description": "校准器排除|change|<1%噪声样本",
        },
        "RES-005": {
            "type": "activity",
            "pattern": "视角分歧度=.*>0\\.15",
            "description": "分歧度高时Vision覆盖阈值提高至90%",
        },
        "RES-006": {
            "type": "activity",
            "pattern": "EMA[85]逆势",
            "description": "加密EMA8/美股EMA5品种分化",
        },
        # --- AUDIT层 (活跃度) ---
        "AUD-035": {
            "type": "activity",
            "pattern": "硬底保护",
            "description": "pos<20% SELL绝对拦截",
        },
        "AUD-036": {
            "type": "activity",
            "pattern": "震荡|突破|跌破",
            "description": "唐纳奇自适应阈值(震荡/突破/跌破标签)",
        },
        "AUD-038": {
            "type": "activity",
            "pattern": "EMA\\d+.*观察",
            "description": "EMA顺势过滤Phase3观察记录",
        },
        # --- SYSTEM层 (OrderFlow) ---
        "SYS-015": {
            "type": "activity",
            "pattern": r"\[SQS\]",
            "description": "SQS计算应每次BUY时触发",
        },
        "SYS-016": {
            "type": "activity",
            "pattern": r"\[VF\]",
            "description": "VF过滤应每次外挂信号时触发",
        },
    }

    def __init__(self):
        self.improvements_path = "state/improvements.json"

    def _load_testing_items(self) -> list:
        """读取所有TESTING状态的改善项"""
        data = safe_json_read(self.improvements_path)
        if not data:
            return []
        items = data.get("improvements", [])
        return [i for i in items if i.get("status") == "TESTING"]

    def verify(self, log_lines: list, dq_result: dict, rhythm_result: dict,
               rejected_signals: dict) -> list:
        """
        对每个TESTING项执行验证

        Returns:
            [{id, title, verdict, detail, description}, ...]
            verdict: PASS / FAIL / ACTIVE / INACTIVE / NEED_DATA
        """
        testing_items = self._load_testing_items()
        results = []

        # 预计算: 将所有rejected_signals展平为reason列表
        all_reasons = []
        for sym, signals in rejected_signals.items():
            for s in signals:
                all_reasons.append(s.get("reason", ""))

        # 预计算: 全文搜索用的日志文本
        log_text = "\n".join(log_lines)

        for item in testing_items:
            item_id = item.get("id", "")
            title = item.get("title", "")
            rule = self.VERIFY_RULES.get(item_id)

            if not rule:
                # 没有验证规则的TESTING项, 标记NEED_DATA
                results.append({
                    "id": item_id, "title": title[:30],
                    "verdict": "NEED_DATA", "detail": "无验证规则",
                    "description": "",
                })
                continue

            if rule["type"] == "metric":
                verdict, detail = self._check_metric(
                    rule, dq_result, rhythm_result, log_lines
                )
            else:  # activity
                verdict, detail = self._check_activity(
                    rule, log_text, all_reasons
                )

            results.append({
                "id": item_id, "title": title[:30],
                "verdict": verdict, "detail": detail,
                "description": rule.get("description", ""),
            })

        return results

    def _check_metric(self, rule: dict, dq_result: dict,
                      rhythm_result: dict, log_lines: list) -> tuple:
        """检查数值指标型规则"""
        metric = rule["metric"]
        op = rule["op"]
        target = rule["target"]

        # 从不同数据源获取实际值
        actual = None
        if metric == "current_price_error":
            # 统计UnboundLocalError/cannot access local variable
            count = sum(1 for l in log_lines
                       if "UnboundLocalError" in l or "cannot access local variable" in l)
            actual = count
        elif metric == "rhythm_overall_score":
            actual = rhythm_result.get("overall_score") if rhythm_result else None
        elif metric == "kline_insufficient_trailing":
            actual = dq_result.get("kline_insufficient_trailing", 0)
        else:
            return ("NEED_DATA", f"未知指标: {metric}")

        if actual is None:
            return ("NEED_DATA", "无数据")

        # 比较
        if op == "<=" and actual <= target:
            return ("PASS", f"{actual} <= {target}")
        elif op == ">=" and actual >= target:
            return ("PASS", f"{actual} >= {target}")
        elif op == "<=" and actual > target:
            return ("FAIL", f"{actual} > {target}")
        elif op == ">=" and actual < target:
            return ("FAIL", f"{actual} < {target}")
        else:
            return ("NEED_DATA", f"actual={actual}")

    def _check_activity(self, rule: dict, log_text: str,
                        all_reasons: list) -> tuple:
        """检查活跃度型规则"""
        pattern = rule["pattern"]
        count = len(re.findall(pattern, log_text))

        # 也检查rejected_signals的reason
        reason_count = sum(1 for r in all_reasons if re.search(pattern, r))
        total = count + reason_count

        if total > 0:
            return ("ACTIVE", f"{total}次触发")
        else:
            return ("INACTIVE", "0次触发")

    def format_report(self, results: list) -> list:
        """生成报告文本行"""
        if not results:
            return []

        lines = [
            "",
            "## TESTING项自动验证 (v3.653闭环)",
            "",
            "| ID | 标题 | 判定 | 数据 | 标准 |",
            "|-----|------|------|------|------|",
        ]

        # 排序: FAIL > INACTIVE > ACTIVE > PASS > NEED_DATA
        order = {"FAIL": 0, "INACTIVE": 1, "ACTIVE": 2, "PASS": 3, "NEED_DATA": 4}
        results.sort(key=lambda r: order.get(r["verdict"], 5))

        for r in results:
            v = r["verdict"]
            icon = {"PASS": "PASS", "FAIL": "FAIL", "ACTIVE": "ACTIVE",
                    "INACTIVE": "INACTIVE", "NEED_DATA": "---"}[v]
            lines.append(
                f"| {r['id']} | {r['title']} | {icon} | {r['detail']} | {r['description']} |"
            )

        # 汇总
        pass_count = sum(1 for r in results if r["verdict"] == "PASS")
        fail_count = sum(1 for r in results if r["verdict"] == "FAIL")
        active_count = sum(1 for r in results if r["verdict"] == "ACTIVE")
        inactive_count = sum(1 for r in results if r["verdict"] == "INACTIVE")
        lines.append("")
        lines.append(f"**汇总**: {pass_count} PASS / {fail_count} FAIL / "
                     f"{active_count} ACTIVE / {inactive_count} INACTIVE / "
                     f"{len(results) - pass_count - fail_count - active_count - inactive_count} 待定")
        lines.append("")

        return lines


# ============================================================
# 4. ImprovementAdvisor - 改善建议系统
# ============================================================

class ImprovementAdvisor:
    """
    改善建议系统 - 生成每日/每周/每月的改善建议

    分析维度:
    1. 逻辑问题 → 代码修复建议
    2. 多余交易 → 交易规则调整
    3. 买卖节奏 → 入场时机优化
    4. 盈亏趋势 → 策略调整
    """

    def __init__(self):
        self.history = self._load_history()

    def _load_history(self) -> Dict:
        """加载历史改善记录"""
        return safe_json_read(CONFIG["improvement_history_file"]) or {
            "daily": {},
            "weekly": {},
            "monthly": {},
        }

    def _save_history(self):
        """保存历史改善记录"""
        safe_json_write(CONFIG["improvement_history_file"], self.history)

    def generate_daily_suggestions(self, detector: IssueDetector,
                                    rhythm_result: Dict,
                                    redundant_result: Dict,
                                    cumulative_whipsaw: Dict = None) -> List[ImprovementSuggestion]:
        """生成每日改善建议"""
        suggestions = []
        stats = detector.stats

        # === 1. 逻辑问题建议 ===
        logic_conflicts = stats.get("WARNING_LOGIC_TREND_CONFLICT", 0)
        if logic_conflicts >= 3:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="逻辑修复",
                title=f"趋势判断逻辑冲突 ({logic_conflicts}次)",
                detail="big_trend与current_trend判断不一致，可能导致交易方向错误",
                action="检查Human模块道氏理论判断和Vision覆盖条件",
                metrics={"conflict_count": logic_conflicts}
            ))

        vision_errors = stats.get("CRITICAL_LOGIC_VISION_ERROR", 0)
        if vision_errors > 0:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="逻辑修复",
                title=f"Vision覆盖执行错误 ({vision_errors}次)",
                detail="Vision覆盖逻辑存在bug，可能覆盖了错误的趋势",
                action="检查llm_server vision_override_to函数",
                metrics={"error_count": vision_errors}
            ))

        # === 2. 多余交易建议 ===
        same_bar = stats.get("same_bar_trade_count", 0)
        if same_bar >= 3:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="交易规则",
                title=f"同K线反复交易 ({same_bar}组)",
                detail="震荡市场信号频繁切换导致同一K线内买卖反复",
                action="增加K线内冻结时间 (v20.1) 或增大信号确认窗口",
                metrics={"same_bar_count": same_bar}
            ))

        loss_amount = stats.get("loss_trade_amount", 0)
        if loss_amount > 50:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="止损策略",
                title=f"亏损交易累计 ${loss_amount:.2f}",
                detail="买高卖低模式导致显著亏损",
                action="收紧止损阈值或检查入场时机判断",
                metrics={"loss_amount": loss_amount}
            ))

        churn_count = stats.get("churn_trade_count", 0)
        if churn_count >= 5:
            suggestions.append(ImprovementSuggestion(
                priority="MEDIUM",
                category="交易频率",
                title=f"无效交易过多 ({churn_count}次)",
                detail="小盈小亏反复进出，手续费侵蚀利润",
                action="增大止盈阈值或减少外挂触发频率",
                metrics={"churn_count": churn_count}
            ))

        # === 3. 买卖节奏建议 ===
        if rhythm_result:
            overall_score = rhythm_result.get("overall_score", 100)
            if overall_score < 50:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="入场时机",
                    title=f"买卖节奏评分过低 ({overall_score}/100)",
                    detail="大部分交易不在理想位置(底部买/顶部卖)",
                    action="等待pos_in_channel < 0.3时买入，> 0.7时卖出",
                    metrics={"score": overall_score}
                ))

            buy_ratio = rhythm_result.get("excellent_buy_ratio", 100)
            if buy_ratio < 40:
                suggestions.append(ImprovementSuggestion(
                    priority="MEDIUM",
                    category="买入时机",
                    title=f"优质买入比例过低 ({buy_ratio}%)",
                    detail=f"只有{buy_ratio}%的买入在底部区域(pos < 0.4)",
                    action="增加回调等待条件，避免追高买入",
                    metrics={"excellent_buy_ratio": buy_ratio}
                ))

            sell_ratio = rhythm_result.get("excellent_sell_ratio", 100)
            if sell_ratio < 40:
                suggestions.append(ImprovementSuggestion(
                    priority="MEDIUM",
                    category="卖出时机",
                    title=f"优质卖出比例过低 ({sell_ratio}%)",
                    detail=f"只有{sell_ratio}%的卖出在顶部区域(pos > 0.6)",
                    action="增加冲高等待条件，避免过早卖出",
                    metrics={"excellent_sell_ratio": sell_ratio}
                ))

            bad_buys = rhythm_result.get("bad_buys", 0)
            if bad_buys >= 3:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="高位追买",
                    title=f"高位买入 ({bad_buys}次)",
                    detail="在pos > 0.6时买入，风险极高",
                    action="添加pos_in_channel < 0.5的买入限制条件",
                    metrics={"bad_buys": bad_buys}
                ))

        # === 4. 数据质量建议 (v3.4) ===
        dq_api = stats.get("dq_api_errors", 0)
        if dq_api >= 3:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="数据源",
                title=f"API故障频繁 ({dq_api}次)",
                detail="yfinance/Coinbase数据获取频繁失败，系统可能使用过期数据做决策",
                action="检查网络连通性、yfinance版本、Coinbase API密钥。考虑增加备用数据源",
                metrics={"api_errors": dq_api}
            ))

        dq_data = stats.get("dq_data_issues", 0)
        if dq_data >= 5:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="数据质量",
                title=f"数据质量问题 ({dq_data}次)",
                detail="K线不足/无历史数据/无效K线/缓存过期，垃圾数据进=垃圾决策出",
                action="增加OHLCV预加载lookback_bars，检查后台更新器频率",
                metrics={"data_issues": dq_data}
            ))

        dq_ind = stats.get("dq_indicator_failures", 0)
        if dq_ind >= 3:
            suggestions.append(ImprovementSuggestion(
                priority="MEDIUM",
                category="指标健康",
                title=f"指标计算失败 ({dq_ind}次)",
                detail="部分技术指标静默失败，L2评分缺少维度导致决策偏差",
                action="检查失败指标的输入数据边界条件，添加fallback默认值",
                metrics={"indicator_failures": dq_ind}
            ))

        dq_vision = stats.get("dq_vision_issues", 0)
        if dq_vision >= 3:
            suggestions.append(ImprovementSuggestion(
                priority="MEDIUM",
                category="Vision健康",
                title=f"Vision数据问题 ({dq_vision}次)",
                detail="Vision结果缺失/过期/读取失败，L1覆盖决策缺少辅助判断",
                action="检查vision_analyzer.py运行状态和结果文件生成",
                metrics={"vision_issues": dq_vision}
            ))

        dq_cal = stats.get("dq_calibrator_issues", 0)
        if dq_cal >= 1:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="校准器",
                title=f"校准器异常 ({dq_cal}次)",
                detail="校准器加载/保存失败，准确率追踪中断，无法选择最佳算法",
                action="检查human_dual_track.json文件完整性和磁盘空间",
                metrics={"calibrator_issues": dq_cal}
            ))

        # === 本周累计Whipsaw建议 ===
        if cumulative_whipsaw:
            ws_summary = cumulative_whipsaw.get("summary", {})
            ws_symbols = cumulative_whipsaw.get("whipsaw_symbols", [])
            ws_count = ws_summary.get("whipsaw_count", 0)
            ws_loss = ws_summary.get("total_whipsaw_loss", 0)

            if ws_count >= 2:
                sym_names = ", ".join(s["symbol"] for s in ws_symbols[:3])
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="累计来回",
                    title=f"本周累计{ws_count}品种来回翻转",
                    detail=f"本周至今{ws_count}个品种来回翻转>=3次: {sym_names}",
                    action="检查这些品种的L1趋势判断稳定性，考虑降低交易频率",
                    metrics={"whipsaw_count": ws_count, "symbols": sym_names}
                ))
            elif ws_count == 1:
                sym = ws_symbols[0]
                suggestions.append(ImprovementSuggestion(
                    priority="MEDIUM",
                    category="累计来回",
                    title=f"{sym['symbol']} 本周来回翻转 ({sym['direction_flips']}次)",
                    detail=f"{sym['symbol']} 本周至今{sym['direction_flips']}次方向翻转, 序列: {sym['sequence_str']}",
                    action=f"观察{sym['symbol']}方向稳定性，持续翻转则降低仓位",
                    metrics={"symbol": sym["symbol"], "flips": sym["direction_flips"]}
                ))

            if ws_loss < -50:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="累计来回",
                    title=f"本周来回亏损累计 ${ws_loss:.2f}",
                    detail=f"来回翻转品种本周累计净亏损${ws_loss:.2f}",
                    action="降低来回品种的交易频率或暂停交易",
                    metrics={"total_loss": ws_loss}
                ))

        # 按优先级排序
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        suggestions.sort(key=lambda x: priority_order.get(x.priority, 99))

        return suggestions

    def generate_weekly_suggestions(self, daily_summaries: List[Dict],
                                     whipsaw_result: Dict = None) -> List[ImprovementSuggestion]:
        """生成每周改善建议"""
        suggestions = []

        if not daily_summaries:
            return suggestions

        # 计算周统计
        total_loss = sum(d.get("loss_amount", 0) for d in daily_summaries)
        total_same_bar = sum(d.get("same_bar_count", 0) for d in daily_summaries)
        avg_rhythm_score = sum(d.get("rhythm_score", 50) for d in daily_summaries) / len(daily_summaries)
        total_logic_errors = sum(d.get("logic_errors", 0) for d in daily_summaries)

        # 周趋势分析
        rhythm_scores = [d.get("rhythm_score", 50) for d in daily_summaries]
        if len(rhythm_scores) >= 3:
            trend = rhythm_scores[-1] - rhythm_scores[0]
            if trend < -10:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="周趋势",
                    title=f"买卖节奏评分下降 ({trend:+.1f})",
                    detail=f"本周节奏评分从{rhythm_scores[0]:.1f}降至{rhythm_scores[-1]:.1f}",
                    action="复盘本周交易，找出入场时机恶化原因",
                    metrics={"trend": trend, "scores": rhythm_scores}
                ))
            elif trend > 10:
                suggestions.append(ImprovementSuggestion(
                    priority="LOW",
                    category="周趋势",
                    title=f"买卖节奏评分提升 ({trend:+.1f})",
                    detail=f"本周节奏评分从{rhythm_scores[0]:.1f}升至{rhythm_scores[-1]:.1f}",
                    action="保持当前策略，记录有效的改善措施",
                    metrics={"trend": trend, "scores": rhythm_scores}
                ))

        # 周累计问题
        if total_loss > 200:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="周亏损",
                title=f"周累计亏损 ${total_loss:.2f}",
                detail="本周亏损交易累计金额过高",
                action="收紧止损策略，检查亏损交易的共同特征",
                metrics={"total_loss": total_loss}
            ))

        if total_same_bar >= 10:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="周震荡",
                title=f"周同K线交易 {total_same_bar}组",
                detail="本周频繁出现同K线反复交易",
                action="增加K线冻结时间或调整震荡市场检测",
                metrics={"total_same_bar": total_same_bar}
            ))

        if avg_rhythm_score < 50:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="周节奏",
                title=f"周平均节奏评分 {avg_rhythm_score:.1f}/100",
                detail="整周交易时机把握较差",
                action="增加pos_in_channel阈值限制条件",
                metrics={"avg_score": avg_rhythm_score}
            ))

        if total_logic_errors >= 5:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="周逻辑",
                title=f"周逻辑错误 {total_logic_errors}次",
                detail="本周检测到多次逻辑判断错误",
                action="优先修复主程序逻辑bug",
                metrics={"total_errors": total_logic_errors}
            ))

        # Whipsaw来回买卖建议
        if whipsaw_result:
            ws_summary = whipsaw_result.get("summary", {})
            ws_symbols = whipsaw_result.get("whipsaw_symbols", [])
            ws_count = ws_summary.get("whipsaw_count", 0)
            ws_loss = ws_summary.get("total_whipsaw_loss", 0)

            if ws_count >= 3:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="来回买卖",
                    title=f"多品种来回买卖 ({ws_count}个品种)",
                    detail=f"本周{ws_count}个品种出现>=3次方向翻转，系统方向判断不稳定",
                    action="检查L1趋势判断是否频繁翻转，考虑增加方向确认延迟或hysteresis",
                    metrics={"whipsaw_count": ws_count}
                ))

            # 单品种翻转>=5次
            for sym in ws_symbols:
                if sym["direction_flips"] >= 5:
                    suggestions.append(ImprovementSuggestion(
                        priority="HIGH",
                        category="来回买卖",
                        title=f"{sym['symbol']} 方向不确定 ({sym['direction_flips']}次翻转)",
                        detail=f"{sym['symbol']}本周{sym['direction_flips']}次方向翻转, 净盈亏${sym['net_pnl']:+.2f}",
                        action=f"考虑将{sym['symbol']}加入观察名单或降低仓位",
                        metrics={"symbol": sym["symbol"], "flips": sym["direction_flips"], "pnl": sym["net_pnl"]}
                    ))

            if ws_loss < -100:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="来回买卖",
                    title=f"来回交易成本过高 ${ws_loss:.2f}",
                    detail=f"来回翻转品种累计净亏损${ws_loss:.2f}",
                    action="降低来回品种的交易频率，增加方向确认信号强度",
                    metrics={"total_loss": ws_loss}
                ))

        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        suggestions.sort(key=lambda x: priority_order.get(x.priority, 99))

        return suggestions

    def generate_monthly_suggestions(self, weekly_summaries: List[Dict],
                                      whipsaw_result: Dict = None) -> List[ImprovementSuggestion]:
        """生成每月改善建议"""
        suggestions = []

        if not weekly_summaries:
            return suggestions

        # 计算月统计
        total_loss = sum(w.get("total_loss", 0) for w in weekly_summaries)
        avg_rhythm_score = sum(w.get("avg_rhythm_score", 50) for w in weekly_summaries) / len(weekly_summaries)
        total_trades = sum(w.get("total_trades", 0) for w in weekly_summaries)

        # 月度趋势
        weekly_scores = [w.get("avg_rhythm_score", 50) for w in weekly_summaries]
        if len(weekly_scores) >= 2:
            month_trend = weekly_scores[-1] - weekly_scores[0]
            if month_trend < -15:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="月趋势",
                    title=f"月度节奏评分大幅下降 ({month_trend:+.1f})",
                    detail=f"本月节奏评分从{weekly_scores[0]:.1f}降至{weekly_scores[-1]:.1f}",
                    action="进行系统性策略复盘，考虑调整核心交易逻辑",
                    metrics={"trend": month_trend, "scores": weekly_scores}
                ))

        # 月度建议
        if total_loss > 500:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="月亏损",
                title=f"月累计亏损 ${total_loss:.2f}",
                detail="本月亏损交易累计金额过高",
                action="全面复盘止损策略，考虑降低仓位或暂停高风险品种",
                metrics={"total_loss": total_loss}
            ))

        if avg_rhythm_score < 45:
            suggestions.append(ImprovementSuggestion(
                priority="HIGH",
                category="月策略",
                title=f"月平均节奏评分 {avg_rhythm_score:.1f}/100",
                detail="整月交易时机把握较差",
                action="考虑调整pos_in_channel入场阈值或增加趋势确认条件",
                metrics={"avg_score": avg_rhythm_score}
            ))
        elif avg_rhythm_score >= 70:
            suggestions.append(ImprovementSuggestion(
                priority="LOW",
                category="月策略",
                title=f"月平均节奏评分优秀 {avg_rhythm_score:.1f}/100",
                detail="整月交易时机把握良好",
                action="保持当前策略，可考虑适度增加仓位",
                metrics={"avg_score": avg_rhythm_score}
            ))

        # 交易频率分析
        if total_trades > 0:
            avg_trades_per_week = total_trades / len(weekly_summaries)
            if avg_trades_per_week > 50:
                suggestions.append(ImprovementSuggestion(
                    priority="MEDIUM",
                    category="交易频率",
                    title=f"交易频率过高 ({avg_trades_per_week:.1f}笔/周)",
                    detail="高频交易增加手续费成本和情绪消耗",
                    action="考虑提高信号确认阈值，减少低质量交易",
                    metrics={"avg_trades": avg_trades_per_week}
                ))

        # Whipsaw来回买卖建议 (月度阈值更高)
        if whipsaw_result:
            ws_summary = whipsaw_result.get("summary", {})
            ws_symbols = whipsaw_result.get("whipsaw_symbols", [])
            ws_count = ws_summary.get("whipsaw_count", 0)
            ws_loss = ws_summary.get("total_whipsaw_loss", 0)

            if ws_count >= 3:
                sym_names = ", ".join(s["symbol"] for s in ws_symbols[:5])
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="来回买卖",
                    title=f"月度多品种来回买卖 ({ws_count}个品种)",
                    detail=f"本月{ws_count}个品种频繁翻转: {sym_names}",
                    action="系统性检查趋势判断稳定性，考虑增加方向锁定机制",
                    metrics={"whipsaw_count": ws_count}
                ))

            if ws_loss < -300:
                suggestions.append(ImprovementSuggestion(
                    priority="HIGH",
                    category="来回买卖",
                    title=f"月度来回交易成本过高 ${ws_loss:.2f}",
                    detail=f"来回翻转品种累计净亏损${ws_loss:.2f}，远超$300阈值",
                    action="暂停高频翻转品种交易，或将其降级为观察模式",
                    metrics={"total_loss": ws_loss}
                ))

            # 慢性来回品种 (整月持续翻转)
            chronic = [s for s in ws_symbols if s["direction_flips"] >= 5]
            if chronic:
                for sym in chronic:
                    suggestions.append(ImprovementSuggestion(
                        priority="HIGH",
                        category="来回买卖",
                        title=f"{sym['symbol']} 慢性来回 ({sym['direction_flips']}次/月)",
                        detail=f"{sym['symbol']}整月翻转{sym['direction_flips']}次, 净盈亏${sym['net_pnl']:+.2f}",
                        action=f"将{sym['symbol']}移出交易列表或切换为长周期策略",
                        metrics={"symbol": sym["symbol"], "flips": sym["direction_flips"]}
                    ))

        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        suggestions.sort(key=lambda x: priority_order.get(x.priority, 99))

        return suggestions


# ============================================================
# 5. ReportGenerator - 报告生成器
# ============================================================

class ReportGenerator:
    """报告生成器"""

    def generate_daily_report(self, date: str, detector: IssueDetector,
                               logic_result: Dict, redundant_result: Dict,
                               rhythm_result: Dict,
                               suggestions: List[ImprovementSuggestion],
                               plugin_result: Dict = None,
                               plugin_pnl: Dict = None,
                               trend_validation: Dict = None,
                               rejected_backtest: Dict = None,
                               dq_result: Dict = None,
                               testing_results: list = None,
                               cumulative_whipsaw: Dict = None) -> str:
        """生成每日分析报告"""
        lines = [
            "=" * 70,
            f"📊 每日交易分析报告 - {date}",
            "=" * 70,
            f"🕐 生成时间: {get_ny_now().strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)",
            "",
        ]

        # === 1. 问题摘要 ===
        summary = detector.get_summary()
        lines.extend([
            "## 1. 问题摘要",
            "",
            f"- 严重问题 (CRITICAL): {summary['critical']}",
            f"- 警告问题 (WARNING): {summary['warning']}",
            f"- 信息提示 (INFO): {summary['info']}",
            "",
        ])

        # === 1a. KEY-000 改善指标面板 ===
        if dq_result is not None:
            _imp_k0 = safe_json_read(IMPROVEMENTS_FILE) or {}
            _k0_items = {}
            _k0_dups = {}
            _k0_res = []
            for _it in _imp_k0.get("items", []):
                _kid = str(_it.get("id", ""))
                if _kid.startswith("KEY-") and _kid != "KEY-000":
                    _prev = _k0_items.get(_kid)
                    if _prev is None:
                        _k0_items[_kid] = _it
                    else:
                        _k0_dups[_kid] = _k0_dups.get(_kid, 1) + 1
                        _prev_date = str(_prev.get("updated_date", ""))
                        _curr_date = str(_it.get("updated_date", ""))
                        if _curr_date >= _prev_date:
                            _k0_items[_kid] = _it
                elif _kid.startswith("RES-"):
                    _k0_res.append(_it)

            if _k0_items:
                # --- 可观测指标提取 ---
                _ng_a = dq_result.get("n_gate_allowed", 0)
                _ng_b = dq_result.get("n_gate_blocked", 0)
                _ng_t = _ng_a + _ng_b
                _ns_st = dq_result.get("n_struct_by_state", {})
                _ns_tot = sum(_ns_st.values()) if _ns_st else 0
                _side_n = _ns_st.get("SIDE", 0)

                # KEY-001补充: 从state文件读N字门控实时状态 (补足日志稀疏时的盲区)
                # v3.9修复: 直接用项目根目录相对路径, 原路径 logs/analyzer/../state/ 解析错误
                _ns_file_path = os.path.join("state", "n_structure_state.json")
                _ns_from_state = {}
                try:
                    if os.path.exists(_ns_file_path):
                        with open(_ns_file_path, "r", encoding="utf-8") as _f:
                            _ns_from_state = json.load(_f)
                except Exception:
                    pass
                _ns_active_count = sum(1 for v in _ns_from_state.values() if v.get("mode") == "ACTIVE")
                _ns_block_count = sum(1 for v in _ns_from_state.values() if v.get("buy_block") or v.get("sell_block"))
                # 若日志计数为0但state文件有数据，用state文件补充
                if _ng_t == 0 and _ns_active_count > 0:
                    _ng_t = _ns_active_count  # 用ACTIVE品种数代替日志计数
                    _ng_b = _ns_block_count
                    _ng_a = _ns_active_count - _ns_block_count
                if _ns_tot == 0 and _ns_active_count > 0:
                    _ns_tot = _ns_active_count

                _k2d = dq_result.get("key002_diff", 0)
                _k2s = dq_result.get("key002_same", 0)
                _k2t = _k2d + _k2s
                _k2sym = len(dq_result.get("key002_by_symbol", {}))

                _k3b = dq_result.get("key003_value_guard_block", 0)

                _k4e = dq_result.get("key004_plugin_event", 0)
                _k4g = dq_result.get("key004_governance", 0)
                _k4ne = dq_result.get("key004_n_eval", 0)
                _k4nc = dq_result.get("key004_n_eval_outcomes", {}).get("CORRECT", 0)

                _k5b = dq_result.get("key005_bfi", 0)
                _k5d = dq_result.get("key005_dqs_block", 0)
                _k5ds = float(dq_result.get("key005_dqs_sum", 0.0))

                # --- 每个KEY的日指标+KPI对照 ---
                _src_tag = "(state)" if (_ng_t > 0 and dq_result.get("n_gate_allowed", 0) + dq_result.get("n_gate_blocked", 0) == 0) else "(log)"
                _k0_data = {
                    "KEY-001": (
                        f"ACTIVE={_ns_active_count}品种 block={_ng_b}{_src_tag}" if _ng_t > 0 else "拦截率=N/A",
                        f"今日拦截={dq_result.get('n_gate_blocked',0)} PASS={dq_result.get('n_gate_allowed',0)}",
                        "拦截70-85% SIDE 50-70%",
                    ),
                    "KEY-002": (
                        f"品种={_k2sym}个 样本={_k2t}",
                        f"差异率={_k2d/_k2t:.0%}" if _k2t > 0 else "差异率=N/A",
                        "全品种写入+7天稳定",
                    ),
                    "KEY-003": (
                        f"BUY拦截={_k3b}次",
                        "",
                        "API完整+批量>=95%",
                    ),
                    "KEY-004": (
                        f"事件={_k4e} 治理={_k4g}",
                        f"评估正确率={_k4nc}/{_k4ne}={_k4nc/_k4ne:.0%}" if _k4ne > 0 else "评估=N/A",
                        "按日输出+排名+降权",
                    ),
                    "KEY-005": (
                        f"BFI={_k5b} DQS禁仓={_k5d}",
                        f"平均DQS={_k5ds/_k5b:.1f}" if _k5b > 0 else "平均DQS=N/A",
                        "DQS<60半仓 <40禁仓",
                    ),
                    "KEY-006": (
                        "Phase 1 建档",
                        "",
                        "边界文档+schema版本化",
                    ),
                    "KEY-007": (
                        f"VF拦截={dq_result.get('vision_filter_block',0)} PK查询={dq_result.get('plugin_knn_query',0)}",
                        f"PK抑制={dq_result.get('plugin_knn_suppress',0)} bypass={dq_result.get('plugin_knn_bypass',0)}",
                        "Phase1日志 Phase2抑制",
                    ),
                }

                lines.extend([
                    "---",
                    "",
                    "## KEY-000 改善指标面板",
                    "",
                    "| KEY | 标题 | 状态 | 今日指标 | KPI目标 |",
                    "|-----|------|------|----------|---------|",
                ])
                for _kid in ["KEY-001", "KEY-002", "KEY-003", "KEY-004", "KEY-005", "KEY-006", "KEY-007"]:
                    _it = _k0_items.get(_kid)
                    if not _it:
                        continue
                    _title = str(_it.get("title", ""))[:20]
                    _status = str(_it.get("status", ""))
                    _d = _k0_data.get(_kid, ("", "", ""))
                    _metrics = f"{_d[0]} {_d[1]}".strip()
                    lines.append(f"| {_kid} | {_title} | {_status} | {_metrics} | {_d[2]} |")

                # KEY执行复查(与RES同逻辑): 台账状态 + 观测状态 + 证据
                _key_review_rows = []

                # KEY-001: N字门控是否有可观测样本 (优先state文件，日志为辅)
                _k1_ledger = _k0_items.get("KEY-001", {}).get("status", "")
                _k1_log_ng = dq_result.get("n_gate_allowed", 0) + dq_result.get("n_gate_blocked", 0)
                if _ns_active_count > 0:
                    _k1_obs = "ACTIVE"
                    _k1_ev = f"active={_ns_active_count}品种 block={_ns_block_count}(state) log_gate={_k1_log_ng}"
                elif _k1_log_ng > 0:
                    _k1_obs = "ACTIVE"
                    _k1_ev = f"n_gate={_k1_log_ng}(log) state=无数据"
                else:
                    _k1_obs = "PENDING"
                    _k1_ev = "n_gate=0 state=无数据"
                _key_review_rows.append(("KEY-001", _k1_ledger, _k1_obs, _k1_ev))

                # KEY-002: 重复ID与样本落盘一致性
                # v3.9修复: 日志稀疏时从state文件补充 (与n_gate同一模式)
                _k2_ledger = _k0_items.get("KEY-002", {}).get("status", "")
                _k2_dup = _k0_dups.get("KEY-002", 0)
                _k2_from_state_total, _k2_from_state_diff, _k2_from_state_sym = 0, 0, 0
                try:
                    _k2_state_path = os.path.join("state", "key002_adaptive.json")
                    if os.path.exists(_k2_state_path):
                        with open(_k2_state_path, "r", encoding="utf-8") as _f:
                            _k2_state = json.load(_f)
                        for _sv in _k2_state.values():
                            if isinstance(_sv, dict):
                                _tc = _sv.get("total_count", 0)
                                _dc = _sv.get("diff_count", 0)
                                if _tc > 0:
                                    _k2_from_state_total += _tc
                                    _k2_from_state_diff  += _dc
                                    _k2_from_state_sym   += 1
                except Exception:
                    pass
                # 日志为主，state为补
                if _k2t == 0 and _k2_from_state_total > 0:
                    _k2t   = _k2_from_state_total
                    _k2d   = _k2_from_state_diff
                    _k2s   = _k2t - _k2d
                    _k2sym = _k2_from_state_sym
                _k2_src = "(state)" if (_k2_from_state_total > 0 and dq_result.get("key002_diff",0) + dq_result.get("key002_same",0) == 0) else "(log)"
                if _k2t > 0 and _k2sym > 0 and _k2_dup <= 1:
                    _k2_obs = "ACTIVE"
                    _k2_diff_rate = f"{_k2d/_k2t:.0%}" if _k2t > 0 else "N/A"
                    _k2_ev = f"total={_k2t} diff={_k2d}({_k2_diff_rate}) symbols={_k2sym}{_k2_src}"
                elif _k2_dup > 1:
                    _k2_obs = "MISMATCH"
                    _k2_ev = f"sample={_k2t} symbols={_k2sym} dup={_k2_dup}"
                else:
                    _k2_obs = "PENDING"
                    _k2_ev = f"sample={_k2t} symbols={_k2sym} dup={_k2_dup}"
                _key_review_rows.append(("KEY-002", _k2_ledger, _k2_obs, _k2_ev))

                # KEY-003: 价值守卫触发活跃度
                _k3_ledger = _k0_items.get("KEY-003", {}).get("status", "")
                if _k3b > 0:
                    _k3_obs = "ACTIVE"
                elif _k3_ledger in ("TESTING", "IN_PROGRESS"):
                    _k3_obs = "PENDING"
                else:
                    _k3_obs = "NO_DATA"
                _k3_ev = f"value_guard_block={_k3b}"
                _key_review_rows.append(("KEY-003", _k3_ledger, _k3_obs, _k3_ev))

                # KEY-004: 外挂治理活跃度 (v3.9: 补充从state文件读取)
                _k4_ledger = _k0_items.get("KEY-004", {}).get("status", "")
                _k4_gov_state_count, _k4_gov_disable = 0, 0
                try:
                    _k4_gov_path = os.path.join("state", "plugin_governance_actions.json")
                    if os.path.exists(_k4_gov_path):
                        with open(_k4_gov_path, "r", encoding="utf-8") as _f:
                            _k4_gov_file = json.load(_f)
                        for _at in ("crypto", "stock"):
                            for _row in _k4_gov_file.get("by_asset", {}).get(_at, []):
                                if isinstance(_row, dict):
                                    _k4_gov_state_count += 1
                                    if _row.get("decision", "") in ("DISABLE", "DISABLE_CANDIDATE"):
                                        _k4_gov_disable += 1
                except Exception:
                    pass
                _k4g_eff = _k4g if _k4g > 0 else _k4_gov_state_count
                _k4_src = "(state)" if (_k4_gov_state_count > 0 and _k4g == 0) else "(log)"
                if _k4e > 0 and _k4g_eff > 0:
                    _k4_obs = "ACTIVE"
                elif _k4e > 0 or _k4_gov_state_count > 0:
                    _k4_obs = "PENDING"
                else:
                    _k4_obs = "NO_DATA"
                _k4_ev = f"events={_k4e} governance={_k4g_eff}{_k4_src} disable_candidate={_k4_gov_disable}"
                _key_review_rows.append(("KEY-004", _k4_ledger, _k4_obs, _k4_ev))

                # KEY-005: 行为金融触发活跃度 (v3.9: 补充从orderflow_state.json读取)
                _k5_ledger = _k0_items.get("KEY-005", {}).get("status", "")
                _k5_state_syms, _k5_state_blocked = 0, 0
                try:
                    _k5_of_path = os.path.join("state", "orderflow_state.json")
                    if os.path.exists(_k5_of_path):
                        with open(_k5_of_path, "r", encoding="utf-8") as _f:
                            _k5_of = json.load(_f)
                        for _sv in _k5_of.values():
                            if isinstance(_sv, dict) and "sqs" in _sv:
                                _k5_state_syms += 1
                                _k5_state_blocked += _sv.get("blocked_count", 0)
                except Exception:
                    pass
                _k5_src = "(state)" if (_k5_state_syms > 0 and _k5b == 0) else "(log)"
                if _k5b > 0 or _k5d > 0:
                    _k5_obs = "ACTIVE"
                elif _k5_state_syms > 0:
                    _k5_obs = "ACTIVE"
                    _k5b = _k5_state_syms  # 用品种数代替
                elif _k5_ledger in ("TESTING", "IN_PROGRESS"):
                    _k5_obs = "PENDING"
                else:
                    _k5_obs = "NO_DATA"
                _k5_ev = f"bfi={_k5b} dqs_block={_k5d} of_syms={_k5_state_syms} blocked={_k5_state_blocked}{_k5_src}"
                _key_review_rows.append(("KEY-005", _k5_ledger, _k5_obs, _k5_ev))

                # KEY-006: 系统治理推进度
                _k6_item = _k0_items.get("KEY-006", {})
                _k6_ledger = _k6_item.get("status", "")
                _k6_open = int(_k6_item.get("open_sys_tracking", {}).get("open_count", 0) or 0)
                _k6_sub = len(_k6_item.get("sub_tasks", []))
                if _k6_ledger == "IN_PROGRESS" and (_k6_sub > 0 or _k6_open > 0):
                    _k6_obs = "ACTIVE"
                elif _k6_ledger in ("IN_PROGRESS", "TESTING"):
                    _k6_obs = "PENDING"
                else:
                    _k6_obs = "NO_DATA"
                _k6_ev = f"sub_tasks={_k6_sub} open_sys={_k6_open}"
                _key_review_rows.append(("KEY-006", _k6_ledger, _k6_obs, _k6_ev))

                # KEY-007: KNN进化 — Vision KNN + Plugin KNN
                _k7_item = _k0_items.get("KEY-007", {})
                _k7_ledger = _k7_item.get("status", "")
                _k7_vf = dq_result.get("vision_filter_block", 0)
                _k7_pk = dq_result.get("plugin_knn_query", 0)
                _k7_sup = dq_result.get("plugin_knn_suppress", 0)
                _k7_err = dq_result.get("plugin_knn_error", 0) + dq_result.get("vision_filter_error", 0)
                _k7_inc = dq_result.get("knn_incremental_ok", 0)
                if _k7_vf + _k7_pk + _k7_sup + _k7_inc > 0:
                    _k7_obs = "ACTIVE"
                    _k7_ev = f"VF拦截={_k7_vf} PK查询={_k7_pk} 抑制={_k7_sup} 增量={_k7_inc} err={_k7_err}"
                elif _k7_err > 0:
                    _k7_obs = "ERROR"
                    _k7_ev = f"KNN异常={_k7_err} (历史库读写失败)"
                else:
                    _k7_obs = "NO_DATA"
                    _k7_ev = "无KNN日志(外挂未触发或模块未加载)"
                _key_review_rows.append(("KEY-007", _k7_ledger, _k7_obs, _k7_ev))

                # KEY-009: 审计管线 — A:Vision + B:BrooksVision + C:MACD + D:CardBridge
                _k9_item = _k0_items.get("KEY-009", {})
                _k9_ledger = _k9_item.get("status", "")
                # 管线A
                _k9a_c = dq_result.get("vf_eval_correct", 0)
                _k9a_i = dq_result.get("vf_eval_incorrect", 0)
                _k9a_total = _k9a_c + _k9a_i
                _k9a_prom = dq_result.get("vf_promote", 0)
                _k9a_demo = dq_result.get("vf_demote", 0)
                # 管线B
                _k9b_c = dq_result.get("bv_eval_correct", 0)
                _k9b_i = dq_result.get("bv_eval_incorrect", 0)
                _k9b_gate = dq_result.get("bv_gate_blocked", 0)
                _k9b_total = _k9b_c + _k9b_i
                # 管线C
                _k9c_gate = dq_result.get("macd_gate_blocked", 0)
                # 知识卡D
                _k9d_match = dq_result.get("card_match_count", 0)
                _k9d_distill = dq_result.get("card_distill_count", 0)

                _k9_parts = []
                if _k9a_total > 0:
                    _k9a_rate = _k9a_c / _k9a_total * 100
                    _k9_parts.append(f"A:eval={_k9a_total}({_k9a_rate:.0f}%)")
                if _k9a_prom + _k9a_demo > 0:
                    _k9_parts.append(f"A:升={_k9a_prom}降={_k9a_demo}")
                if _k9b_total > 0:
                    _k9b_rate = _k9b_c / _k9b_total * 100
                    _k9_parts.append(f"B:eval={_k9b_total}({_k9b_rate:.0f}%)")
                if _k9b_gate > 0:
                    _k9_parts.append(f"B:gate={_k9b_gate}")
                if _k9c_gate > 0:
                    _k9_parts.append(f"C:gate={_k9c_gate}")
                if _k9d_match > 0:
                    _k9_parts.append(f"D:match={_k9d_match}")
                if _k9d_distill > 0:
                    _k9_parts.append(f"D:distill={_k9d_distill}")

                if _k9_parts:
                    _k9_obs = "ACTIVE"
                    _k9_ev = " | ".join(_k9_parts)
                else:
                    _k9_obs = "PENDING"
                    _k9_ev = "4管线等待首次数据(重启后生效)"
                _key_review_rows.append(("KEY-009", _k9_ledger, _k9_obs, _k9_ev))

                lines.extend([
                    "",
                    "| KEY复查 | 台账状态 | 观测状态 | 证据 |",
                    "|---------|----------|----------|------|",
                ])
                for _kid, _ledger, _obs, _ev in _key_review_rows:
                    lines.append(f"| {_kid} | {_ledger} | {_obs} | {_ev} |")

                # RES项概览
                if _k0_res:
                    _res_ev = {
                        "RES-001": dq_result.get("rhythm_block", 0),
                        "RES-002": dq_result.get("view_divergence_raise", 0),
                        "RES-003": 1 if safe_json_read("state/human_dual_track.json") else 0,
                        "RES-004": dq_result.get("tau_filter", 0),
                        "RES-005": dq_result.get("view_divergence_raise", 0),
                        "RES-006": dq_result.get("ema5_observe", 0),
                        "RES-007": dq_result.get("trend_phase_obs", 0),
                        "RES-008": dq_result.get("time_decay_obs", 0),
                    }
                    lines.extend([
                        "",
                        "| RES | 标题 | 状态 | 今日触发 |",
                        "|-----|------|------|----------|",
                    ])
                    for _rit in _k0_res:
                        _rid = str(_rit.get("id", ""))
                        _rtitle = str(_rit.get("title", ""))[:25]
                        _rstat = str(_rit.get("status", ""))
                        _cnt = _res_ev.get(_rid, 0)
                        _badge = "ACTIVE" if _cnt > 0 else "---"
                        lines.append(f"| {_rid} | {_rtitle} | {_rstat} | {_badge}({_cnt}) |")

                lines.extend(["", ""])

        # === 2. 逻辑问题检测 ===
        lines.extend([
            "---",
            "",
            "## 2. 主程序逻辑检测",
            "",
        ])
        if logic_result:
            lines.extend([
                f"- 趋势冲突: {logic_result.get('trend_conflicts', 0)}次",
                f"- Vision错误: {logic_result.get('vision_errors', 0)}次",
                f"- 道氏异常: {logic_result.get('dow_anomalies', 0)}次",
                f"- 趋势快速切换: {logic_result.get('trend_flips', 0)}次",
                f"- 仓位错误: {logic_result.get('position_errors', 0)}次",
                "",
                "### v3.640 事件统计",
                f"- CNN覆盖融合(L2): {logic_result.get('cnn_overrides', 0)}次",
                f"- Vision覆盖L1: {logic_result.get('accuracy_overrides', 0)}次",
                f"- x4缠论胜出: {logic_result.get('x4_chan_wins', 0)}次",
                f"- 双底双顶跳过x4: {logic_result.get('double_pattern_skip_x4', 0)}次",
            ])
        else:
            lines.append("无逻辑问题检测数据")
        lines.append("")

        # === 2a-1. 数据质量检测 (v3.4) ===
        if dq_result and dq_result.get("total_issues", 0) > 0:
            dq = dq_result
            lines.extend([
                "---",
                "",
                "## 2-1. 数据质量与系统健康 (v3.4: 垃圾进垃圾出检测)",
                "",
                f"**总问题数: {dq['total_issues']}**",
                "",
                "| 类别 | 问题数 | 明细 |",
                "|------|--------|------|",
            ])

            # 数据质量行
            data_total = dq["kline_insufficient"] + dq["no_history_data"] + dq["invalid_candle"] + dq["cache_expired"]
            data_detail = []
            if dq["kline_insufficient"]: data_detail.append(f"K线不足{dq['kline_insufficient']}")
            if dq["no_history_data"]: data_detail.append(f"无数据{dq['no_history_data']}")
            if dq["invalid_candle"]: data_detail.append(f"无效K线{dq['invalid_candle']}")
            if dq["cache_expired"]: data_detail.append(f"缓存过期{dq['cache_expired']}")
            if data_total:
                lines.append(f"| 数据质量 | {data_total} | {', '.join(data_detail)} |")

            # API故障行
            api_total = dq["yfinance_timeout"] + dq["yfinance_error"] + dq["coinbase_error"] + dq["bg_updater_fail"]
            api_detail = []
            if dq["yfinance_timeout"]: api_detail.append(f"yfinance超时{dq['yfinance_timeout']}")
            if dq["yfinance_error"]: api_detail.append(f"yfinance异常{dq['yfinance_error']}")
            if dq["coinbase_error"]: api_detail.append(f"Coinbase错误{dq['coinbase_error']}")
            if dq["bg_updater_fail"]: api_detail.append(f"后台更新失败{dq['bg_updater_fail']}")
            if api_total:
                lines.append(f"| API故障 | {api_total} | {', '.join(api_detail)} |")

            # 指标计算失败行
            if dq["indicator_failures"]:
                ind_detail = ", ".join(f"{k}{v}" for k, v in sorted(dq["indicator_by_type"].items(), key=lambda x: -x[1]))
                lines.append(f"| 指标计算 | {dq['indicator_failures']} | {ind_detail} |")

            # Vision数据质量行
            vis_total = dq["vision_file_missing"] + dq["vision_read_fail"] + dq["vision_stale"]
            vis_detail = []
            if dq["vision_file_missing"]: vis_detail.append(f"文件缺失{dq['vision_file_missing']}")
            if dq["vision_read_fail"]: vis_detail.append(f"读取失败{dq['vision_read_fail']}")
            if dq["vision_stale"]: vis_detail.append(f"过期{dq['vision_stale']}(最久{dq['vision_stale_max_age']}s)")
            if vis_total:
                lines.append(f"| Vision质量 | {vis_total} | {', '.join(vis_detail)} |")

            # 校准器异常行
            cal_total = dq["calibrator_load_fail"] + dq["calibrator_save_fail"] + dq["validator_fail"] + dq["calibrator_low_accuracy"]
            cal_detail = []
            if dq["calibrator_load_fail"]: cal_detail.append(f"加载失败{dq['calibrator_load_fail']}")
            if dq["calibrator_save_fail"]: cal_detail.append(f"保存失败{dq['calibrator_save_fail']}")
            if dq["validator_fail"]: cal_detail.append(f"验证器异常{dq['validator_fail']}")
            if dq["calibrator_low_accuracy"]: cal_detail.append(f"低准确率{dq['calibrator_low_accuracy']}")
            if cal_total:
                lines.append(f"| 校准器 | {cal_total} | {', '.join(cal_detail)} |")

            # v3.653: 论文驱动改善活跃度
            res_total = dq.get("tau_filter", 0) + dq.get("view_divergence_raise", 0)
            res_detail = []
            if dq.get("tau_filter"): res_detail.append(f"τ过滤{dq['tau_filter']}样本")
            if dq.get("view_divergence_raise"): res_detail.append(f"分歧度提阈{dq['view_divergence_raise']}次")
            if res_total:
                lines.append(f"| 论文改善(v3.653) | {res_total} | {', '.join(res_detail)} |")

            lines.append("")

            # 按品种统计 (只显示有问题的品种)
            problem_symbols = {s: v for s, v in dq["by_symbol"].items() if sum(v.values()) >= 2}
            if problem_symbols:
                lines.extend([
                    "**问题品种 (>=2次):**",
                    "",
                ])
                for sym, counts in sorted(problem_symbols.items(), key=lambda x: -sum(x[1].values())):
                    total = sum(counts.values())
                    detail_parts = ", ".join(f"{k}:{v}" for k, v in counts.items() if v > 0)
                    lines.append(f"- {sym}: {total}次 ({detail_parts})")
                lines.append("")
        lines.append("")

        # === 2a-2. OrderFlow 量价统计 (v3.653) ===
        if dq_result:
            _sqs_total = dq_result.get("sqs_passed", 0) + dq_result.get("sqs_blocked", 0)
            _vf_total = dq_result.get("vf_pass", 0) + dq_result.get("vf_upgrade", 0) + dq_result.get("vf_downgrade", 0) + dq_result.get("vf_reject", 0)
            if _sqs_total > 0 or _vf_total > 0:
                lines.extend([
                    "---",
                    "",
                    "## OrderFlow 统计 (v3.653 Phase 1 观察)",
                    "",
                    f"- SQS检查: {_sqs_total}次 | 通过: {dq_result.get('sqs_passed', 0)}次 | 拦截: {dq_result.get('sqs_blocked', 0)}次 (Phase1仅记录)",
                    f"- VF过滤: {_vf_total}次 | PASS:{dq_result.get('vf_pass', 0)} UPGRADE:{dq_result.get('vf_upgrade', 0)} DOWNGRADE:{dq_result.get('vf_downgrade', 0)} REJECT:{dq_result.get('vf_reject', 0)}",
                    f"- 缩量警告: {dq_result.get('volume_dry', 0)}次",
                    f"- 低质量信号(SQS<0.1): {dq_result.get('sqs_low_quality', 0)}次",
                    "",
                ])

        # === 2a-2b. v21.8 跨周期共识度 (SYS-011) ===
        if dq_result:
            _cons_low = dq_result.get("consensus_low", 0)
            _cons_high = dq_result.get("consensus_high", 0)
            _cons_contrary = dq_result.get("consensus_contrary", 0)
            _cons_total = _cons_low + _cons_high + _cons_contrary
            if _cons_total > 0:
                lines.extend([
                    "---",
                    "",
                    "## 跨周期共识度统计 (v21.8 / SYS-011)",
                    "",
                    f"- 共识评分日志: {_cons_total}次",
                    f"- 低共识: {_cons_low}次",
                    f"- 高共识: {_cons_high}次",
                    f"- 逆向共识: {_cons_contrary}次",
                    "",
                ])

        # === 2a-3. v3.654/v21.10 系统改善观察统计 ===
        if dq_result:
            _obs_total = (dq_result.get("trend_phase_obs", 0) + dq_result.get("time_decay_obs", 0) +
                          dq_result.get("regime_window_obs", 0) + dq_result.get("confidence_gate_obs", 0) +
                          dq_result.get("n_pattern_exempt", 0) + dq_result.get("regime_weight_obs", 0))
            if _obs_total > 0 or dq_result.get("data_stale", 0) > 0:
                _tp = dq_result.get("trend_phase_by_type", {})
                lines.extend([
                    "---",
                    "",
                    "## 系统改善观察 (v3.654/v21.10 Phase 1)",
                    "",
                    f"- 趋势阶段估计: {dq_result.get('trend_phase_obs', 0)}次 "
                    f"(初升:{_tp.get('INITIAL', 0)} 主升:{_tp.get('MAIN', 0)} 末升:{_tp.get('FINAL', 0)})",
                    f"- 持仓时间衰减: {dq_result.get('time_decay_obs', 0)}次观察",
                    f"- Regime窗口调整: {dq_result.get('regime_window_obs', 0)}次观察",
                    f"- 置信度门控: {dq_result.get('confidence_gate_obs', 0)}次会被拦截",
                    f"- 阶段节奏调整: {dq_result.get('phase_rhythm_obs', 0)}次会调整阈值",
                    f"- Regime权重调整: {dq_result.get('regime_weight_obs', 0)}次观察",
                    f"- N字豁免: {dq_result.get('n_pattern_exempt', 0)}次",
                    f"- 数据陈旧告警: {dq_result.get('data_stale', 0)}次",
                    f"- 滑点告警: {dq_result.get('slippage_alert', 0)}次",
                    f"- 熔断记录: {dq_result.get('breaker_obs', 0)}次",
                    "",
                ])

        # === 2a-3b. 非KEY P0状态快照 (SYS-011/015/016/017/018) ===
        if dq_result is not None:
            _of_state = safe_json_read("state/orderflow_state.json") or {}
            _pb_state = safe_json_read("state/portfolio_breaker.json") or {}
            _sm_state = safe_json_read("state/strategy_metrics.json") or {}

            _cons_total = dq_result.get("consensus_low", 0) + dq_result.get("consensus_high", 0) + dq_result.get("consensus_contrary", 0)
            _sqs_total = dq_result.get("sqs_passed", 0) + dq_result.get("sqs_blocked", 0)
            _vf_total = dq_result.get("vf_pass", 0) + dq_result.get("vf_upgrade", 0) + dq_result.get("vf_downgrade", 0) + dq_result.get("vf_reject", 0)

            _of_symbols = len(_of_state) if isinstance(_of_state, dict) else 0
            _pb_label = _pb_state.get("state", "NO_DATA") if isinstance(_pb_state, dict) else "NO_DATA"
            _sm_metrics = _sm_state.get("metrics", {}) if isinstance(_sm_state, dict) else {}
            _wr = _sm_metrics.get("win_rate") if isinstance(_sm_metrics, dict) else None
            _pf = _sm_metrics.get("profit_factor") if isinstance(_sm_metrics, dict) else None
            _wr_pf = f"WR={_wr:.1%} PF={_pf:.2f}" if isinstance(_wr, (int, float)) and isinstance(_pf, (int, float)) else "NO_DATA"

            lines.extend([
                "---",
                "",
                "## 非KEY P0可观测快照",
                "",
                f"- SYS-011 共识度: {_cons_total}次 (低:{dq_result.get('consensus_low', 0)} 高:{dq_result.get('consensus_high', 0)} 逆向:{dq_result.get('consensus_contrary', 0)})",
                f"- SYS-015 SQS: {_sqs_total}次 (PASS:{dq_result.get('sqs_passed', 0)} BLOCK:{dq_result.get('sqs_blocked', 0)}) | orderflow_state符号数:{_of_symbols}",
                f"- SYS-016 VF: {_vf_total}次 (PASS:{dq_result.get('vf_pass', 0)} UPGRADE:{dq_result.get('vf_upgrade', 0)} DOWNGRADE:{dq_result.get('vf_downgrade', 0)} REJECT:{dq_result.get('vf_reject', 0)})",
                f"- SYS-017 熔断状态: {_pb_label}",
                f"- SYS-018 策略评估: {_wr_pf}",
                "",
            ])

        # === 2a-3c. 非KEY开放项总览（日志+状态证据） ===
        if dq_result is not None:
            _imp = safe_json_read(IMPROVEMENTS_FILE) or {}
            _trade_freq = safe_json_read("state/trade_frequency.json") or {}
            _stock_sel = safe_json_read("state/stock_selection.json") or {}
            _corr_state = safe_json_read("state/correlation_state.json") or {}
            _human_dt = safe_json_read("state/human_dual_track.json") or {}
            _orderflow = safe_json_read("state/orderflow_state.json") or {}
            _breaker = safe_json_read("state/portfolio_breaker.json") or {}
            _strategy = safe_json_read("state/strategy_metrics.json") or {}

            _cons_total = dq_result.get("consensus_low", 0) + dq_result.get("consensus_high", 0) + dq_result.get("consensus_contrary", 0)
            _sqs_total = dq_result.get("sqs_passed", 0) + dq_result.get("sqs_blocked", 0)
            _vf_total = dq_result.get("vf_pass", 0) + dq_result.get("vf_upgrade", 0) + dq_result.get("vf_downgrade", 0) + dq_result.get("vf_reject", 0)

            _evidence = {
                "SYS-006": ("ACTIVE" if _trade_freq else "NO_DATA", f"trade_frequency mode={_trade_freq.get('mode', '?')} used={_trade_freq.get('global_used', 0)}" if _trade_freq else "missing state/trade_frequency.json"),
                "SYS-007": ("ACTIVE" if isinstance(_stock_sel.get("grades") if isinstance(_stock_sel, dict) else None, dict) and (_stock_sel.get("grades") or {}) else "PENDING", "stock_selection grades available" if isinstance(_stock_sel.get("grades") if isinstance(_stock_sel, dict) else None, dict) and (_stock_sel.get("grades") or {}) else "waiting stock_selection grades"),
                "SYS-011": ("ACTIVE" if _cons_total > 0 else "PENDING", f"consensus logs={_cons_total}"),
                "SYS-015": ("ACTIVE" if _sqs_total > 0 else ("DEPLOYED" if _orderflow else "NO_DATA"), f"SQS pass={dq_result.get('sqs_passed', 0)} block={dq_result.get('sqs_blocked', 0)}"),
                "SYS-016": ("ACTIVE" if _vf_total > 0 else ("DEPLOYED" if _orderflow else "NO_DATA"), f"VF pass={dq_result.get('vf_pass', 0)} reject={dq_result.get('vf_reject', 0)}"),
                "SYS-017": ("ACTIVE" if _breaker else ("DEPLOYED" if dq_result.get("breaker_obs", 0) > 0 else "PENDING"), f"breaker_state={_breaker.get('state', 'NO_DATA') if isinstance(_breaker, dict) else 'NO_DATA'} obs={dq_result.get('breaker_obs', 0)}"),
                "SYS-018": ("ACTIVE" if isinstance(_strategy.get("metrics") if isinstance(_strategy, dict) else None, dict) else "NO_DATA", "strategy_metrics available" if isinstance(_strategy.get("metrics") if isinstance(_strategy, dict) else None, dict) else "missing state/strategy_metrics.json"),
                "SYS-019": ("ACTIVE" if _corr_state else "NO_DATA", "correlation state available" if _corr_state else "missing state/correlation_state.json"),
                "SYS-020": ("ACTIVE" if dq_result.get("regime_weight_obs", 0) > 0 else "PENDING", f"regime_weight_obs={dq_result.get('regime_weight_obs', 0)}"),
                "SYS-022": ("ACTIVE" if dq_result.get("confidence_gate_obs", 0) > 0 else "PENDING", f"confidence_gate_obs={dq_result.get('confidence_gate_obs', 0)}"),
                "SYS-023": ("ACTIVE" if dq_result.get("regime_window_obs", 0) > 0 else "PENDING", f"regime_window_obs={dq_result.get('regime_window_obs', 0)}"),
                "SYS-025": ("ACTIVE" if dq_result.get("trend_health_obs", 0) > 0 else "PENDING", f"trend_health_obs={dq_result.get('trend_health_obs', 0)}"),
                "SYS-026": ("ACTIVE" if dq_result.get("donchian_vol_obs", 0) > 0 else "PENDING", f"donchian_vol_obs={dq_result.get('donchian_vol_obs', 0)}"),
                "SYS-027": ("ACTIVE" if dq_result.get("vp_l2_obs", 0) > 0 else "PENDING", f"vp_l2_obs={dq_result.get('vp_l2_obs', 0)}"),
                "SYS-028": ("ACTIVE" if dq_result.get("vp_stop_anchor_obs", 0) > 0 else "PENDING", f"vp_stop_anchor_obs={dq_result.get('vp_stop_anchor_obs', 0)}"),
                "SYS-029": ("ACTIVE" if isinstance(_strategy.get("metrics") if isinstance(_strategy, dict) else None, dict) else "NO_DATA", "using strategy_metrics as dashboard base" if isinstance(_strategy.get("metrics") if isinstance(_strategy, dict) else None, dict) else "missing strategy metrics"),
                "SYS-032": ("ACTIVE" if (dq_result.get("data_stale", 0) + dq_result.get("slippage_alert", 0)) > 0 else "PENDING", f"data_stale={dq_result.get('data_stale', 0)} slippage={dq_result.get('slippage_alert', 0)}"),
                "SYS-033": ("ACTIVE" if dq_result.get("tau_filter", 0) > 0 else "PENDING", f"tau_filter={dq_result.get('tau_filter', 0)}"),
                "SYS-034": ("ACTIVE" if (dq_result.get("regime_window_obs", 0) + dq_result.get("regime_weight_obs", 0)) > 0 else "PENDING", f"regime_window={dq_result.get('regime_window_obs', 0)} regime_weight={dq_result.get('regime_weight_obs', 0)}"),
                "RES-001": ("ACTIVE" if dq_result.get("rhythm_block", 0) > 0 else "PENDING", f"rhythm_block={dq_result.get('rhythm_block', 0)}"),
                "RES-002": ("ACTIVE" if dq_result.get("vision_errors", 0) > 0 else "DEPLOYED", f"vision_errors={dq_result.get('vision_errors', 0)}"),
                "RES-003": ("ACTIVE" if _human_dt else "PENDING", "human_dual_track available" if _human_dt else "missing state/human_dual_track.json"),
                "RES-004": ("ACTIVE" if dq_result.get("tau_filter", 0) > 0 else "PENDING", f"tau_filter={dq_result.get('tau_filter', 0)}"),
                "RES-005": ("ACTIVE" if dq_result.get("view_divergence_raise", 0) > 0 else "PENDING", f"view_divergence_raise={dq_result.get('view_divergence_raise', 0)}"),
                "RES-006": ("ACTIVE" if dq_result.get("ema5_observe", 0) > 0 else "PENDING", f"ema_observe={dq_result.get('ema5_observe', 0)}"),
                "RES-007": ("ACTIVE" if dq_result.get("trend_phase_obs", 0) > 0 else "PENDING", f"trend_phase_obs={dq_result.get('trend_phase_obs', 0)}"),
                "RES-008": ("ACTIVE" if dq_result.get("time_decay_obs", 0) > 0 else "PENDING", f"time_decay_obs={dq_result.get('time_decay_obs', 0)}"),
            }

            _open_non_key = []
            if isinstance(_imp, dict):
                for _item in _imp.get("items", []):
                    _id = str(_item.get("id", ""))
                    if _id.startswith("KEY-"):
                        continue
                    if str(_item.get("status", "")) == "CLOSED":
                        continue
                    _open_non_key.append(_item)

            if _open_non_key:
                _prio_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
                _open_non_key.sort(key=lambda x: (_prio_order.get(str(x.get("priority", "P3")), 9), str(x.get("id", ""))))
                lines.extend([
                    "---",
                    "",
                    "## 非KEY开放项追踪（日志+状态）",
                    "",
                    "| ID | Priority | 台账状态 | 观测状态 | 证据 |",
                    "|----|----------|----------|----------|------|",
                ])
                for _item in _open_non_key:
                    _id = str(_item.get("id", ""))
                    _prio = str(_item.get("priority", ""))
                    _ledger = str(_item.get("status", ""))
                    _obs, _detail = _evidence.get(_id, ("UNMAPPED", "no mapping yet"))
                    lines.append(f"| {_id} | {_prio} | {_ledger} | {_obs} | {_detail} |")
                lines.append("")

        # === 2a-4. v3.655/v21.11 量价增强观察 (SYS-025~028) ===
        if dq_result:
            _vp_total = (dq_result.get("trend_health_obs", 0) + dq_result.get("donchian_vol_obs", 0) +
                         dq_result.get("vp_l2_obs", 0) + dq_result.get("vp_stop_anchor_obs", 0))
            if _vp_total > 0:
                lines.extend([
                    "---",
                    "",
                    "## 量价增强观察 (v21.11 Phase 1)",
                    "",
                    f"- 趋势健康度(SYS-025): {dq_result.get('trend_health_obs', 0)}次记录",
                    f"- Donchian量价(SYS-026): {dq_result.get('donchian_vol_obs', 0)}次记录",
                    f"- VP+L2确认(SYS-027): {dq_result.get('vp_l2_obs', 0)}次记录",
                    f"- VP止损锚定(SYS-028): {dq_result.get('vp_stop_anchor_obs', 0)}次会调整止损",
                    "",
                ])

        # === 2a-5. v3.656 Anti-Whipsaw HOLD带统计 ===
        if dq_result:
            _hb_suppress = dq_result.get("hold_band_suppress", 0)
            _hb_breakout = dq_result.get("hold_band_breakout", 0)
            _hb_pos = dq_result.get("hold_band_by_pos", {})
            if _hb_suppress > 0 or _hb_breakout > 0 or sum(_hb_pos.values()) > 0:
                lines.extend([
                    "---",
                    "",
                    "## Anti-Whipsaw HOLD带 (v3.656)",
                    "",
                    f"- 降频拦截: {_hb_suppress}次 (缠论有方向但价格在HOLD带内→强制SIDE)",
                    f"- 发单拦截: {dq_result.get('hold_band_block', 0)}次 (L1/L2/外挂/P0全路径阻止)",
                    f"- 中线突破放行: {_hb_breakout}次 (唐纳奇中线移动>0.3%→趋势变化)",
                    f"- 位置分布: HOLD={_hb_pos.get('HOLD', 0)} ABOVE={_hb_pos.get('ABOVE', 0)} "
                    f"BELOW={_hb_pos.get('BELOW', 0)} BREAKOUT={_hb_pos.get('BREAKOUT', 0)}",
                    "",
                ])
                # 按品种统计降频次数
                _sym_hb = {s: v.get("hold_band_suppress", 0)
                           for s, v in dq_result.get("by_symbol", {}).items()
                           if v.get("hold_band_suppress", 0) > 0}
                if _sym_hb:
                    lines.append("| 品种 | 降频次数 | 发单拦截 | 中线突破 |")
                    lines.append("|------|---------|---------|---------|")
                    for _s, _cnt in sorted(_sym_hb.items(), key=lambda x: x[1], reverse=True):
                        _blk = dq_result.get("by_symbol", {}).get(_s, {}).get("hold_band_block", 0)
                        _bo = dq_result.get("by_symbol", {}).get(_s, {}).get("hold_band_breakout", 0)
                        lines.append(f"| {_s} | {_cnt} | {_blk} | {_bo} |")
                    lines.append("")

        # === 2a-6. v3.657 Vision N字结构统计 ===
        if dq_result:
            _np_total = dq_result.get("vision_n_pattern", 0)
            _np_by_type = dq_result.get("vision_n_by_type", {})
            if _np_total > 0:
                lines.extend([
                    "---",
                    "",
                    "## Vision N字结构 (v3.657)",
                    "",
                    f"- 检出: {_np_total}次 (UP_N={_np_by_type.get('UP_N', 0)} DOWN_N={_np_by_type.get('DOWN_N', 0)})",
                    "",
                ])

        # === 2a-7. KEY-001 N字结构门控统计 ===
        if dq_result:
            _ns_count = dq_result.get("n_struct_count", 0)
            _ng_allowed = dq_result.get("n_gate_allowed", 0)
            _ng_blocked = dq_result.get("n_gate_blocked", 0)
            _frac_count = dq_result.get("l1_fractal_count", 0)
            _ns_empty = dq_result.get("n_struct_empty", 0)
            _ns_error = dq_result.get("n_struct_error", 0)
            if _ns_count > 0 or _ng_allowed > 0 or _ng_blocked > 0 or _frac_count > 0:
                _ns_states = dq_result.get("n_struct_by_state", {})
                _ng_dirs = dq_result.get("n_gate_by_dir", {})
                _ng_total = _ng_allowed + _ng_blocked
                _ng_block_rate = f"{_ng_blocked/_ng_total:.0%}" if _ng_total > 0 else "N/A"
                lines.extend([
                    "---",
                    "",
                    "## KEY-001 N字结构门控 (v3.660 全品种ACTIVE)",
                    "",
                    f"- L1分型输出: {_frac_count}次 | N字状态: {_ns_count}次 | 空分型: {_ns_empty}次 | 异常: {_ns_error}次",
                    f"- N字门控判定: {_ng_total}次 (allowed={_ng_allowed} blocked={_ng_blocked} 拦截率={_ng_block_rate})",
                    f"  - BUY: allowed={_ng_dirs.get('BUY',{}).get('allowed',0)} blocked={_ng_dirs.get('BUY',{}).get('blocked',0)}",
                    f"  - SELL: allowed={_ng_dirs.get('SELL',{}).get('allowed',0)} blocked={_ng_dirs.get('SELL',{}).get('blocked',0)}",
                    f"- 状态分布: " + " ".join(f"{k}={v}" for k, v in sorted(_ns_states.items())),
                    "",
                ])
                # HOLD带 vs N字门控对比
                _hb_block = dq_result.get("hold_band_block", 0) + dq_result.get("hold_band_suppress", 0)
                if _hb_block > 0 or _ng_blocked > 0:
                    lines.extend([
                        f"**HOLD带 vs N字门控对比**: HOLD带拦截={_hb_block}次 vs N字blocked={_ng_blocked}次",
                        "",
                    ])

        # === 2a-8. v3.658 低准确率品种降权统计 ===
        if dq_result:
            _lag_count = dq_result.get("low_acc_guard_count", 0)
            _lag_syms = dq_result.get("low_acc_guard_symbols", {})
            if _lag_count > 0:
                _lag_list = ", ".join(f"{s}({n}次)" for s, n in sorted(_lag_syms.items(), key=lambda x: -x[1]))
                lines.extend([
                    "---",
                    "",
                    "## v3.658 低准确率品种降权 (Phase 1 观察)",
                    "",
                    f"- 触发次数: {_lag_count}次",
                    f"- 涉及品种: {_lag_list}",
                    f"- 状态: {'已降级为SIDE' if False else '仅记录(Phase 1)'}",
                    "",
                ])

        # === 2a-9. v3.660 KEY-002 品种自适应统计 ===
        if dq_result:
            _k2_diff = dq_result.get("key002_diff", 0)
            _k2_same = dq_result.get("key002_same", 0)
            _k2_total = _k2_diff + _k2_same
            _k2_syms = dq_result.get("key002_by_symbol", {})
            if _k2_total > 0:
                _k2_diff_rate = f"{_k2_diff/_k2_total:.0%}" if _k2_total > 0 else "N/A"
                lines.extend([
                    "---",
                    "",
                    "## KEY-002 品种自适应 (Phase 1 数据收集)",
                    "",
                    f"- 样本: {_k2_total}次 | 差异(DIFF): {_k2_diff}次 ({_k2_diff_rate}) | 一致(SAME): {_k2_same}次",
                    f"- 品种数: {len(_k2_syms)}个",
                    "",
                ])
                if _k2_syms:
                    lines.append("| 品种 | DIFF | SAME | 差异率 |")
                    lines.append("|------|------|------|--------|")
                    for _s, _v in sorted(_k2_syms.items()):
                        _d = _v.get("diff", 0)
                        _sm = _v.get("same", 0)
                        _t = _d + _sm
                        _r = f"{_d/_t:.0%}" if _t > 0 else "N/A"
                        lines.append(f"| {_s} | {_d} | {_sm} | {_r} |")
                    lines.append("")

        # === 2a-10. v3.660 N字门控实际拦截统计 ===
        if dq_result:
            _ngba = dq_result.get("n_gate_block_active", 0)
            _ngba_syms = dq_result.get("n_gate_block_active_by_symbol", {})
            if _ngba > 0:
                _ngba_list = ", ".join(f"{s}({n}次)" for s, n in sorted(_ngba_syms.items(), key=lambda x: -x[1]))
                lines.extend([
                    "---",
                    "",
                    "## N字门控实际拦截 (v3.660 全品种)",
                    "",
                    f"- 拦截次数: {_ngba}次",
                    f"- 涉及品种: {_ngba_list}",
                    "",
                ])

        # === 2a-11. v3.660 Vision N字冲突统计 ===
        if dq_result:
            _vnc = dq_result.get("vision_n_conflict", 0)
            _vnc_syms = dq_result.get("vision_n_conflict_by_symbol", {})
            if _vnc > 0:
                _vnc_list = ", ".join(f"{s}({n}次)" for s, n in sorted(_vnc_syms.items(), key=lambda x: -x[1]))
                lines.extend([
                    "---",
                    "",
                    "## Vision N字冲突 (v3.660)",
                    "",
                    f"- Vision覆盖被N字阻止: {_vnc}次",
                    f"- 涉及品种: {_vnc_list}",
                    "",
                ])

        # === 2a-12. KEY-002 外挂智能进化 ===
        if dq_result:
            _evo = dq_result.get("plugin_evolve", 0)
            _evo_details = dq_result.get("plugin_evolve_details", [])
            if _evo > 0:
                lines.extend([
                    "---",
                    "",
                    "## 外挂智能进化 (KEY-002)",
                    "",
                    f"- 进化建议: {_evo}条",
                    "",
                    "| 品种 | 外挂 | 建议 | 原因 |",
                    "|------|------|------|------|",
                ])
                for _ed in _evo_details:
                    lines.append(f"| {_ed['symbol']} | {_ed['plugin']} | {_ed['action']} | {_ed['reason']} |")
                lines.append("")

        # === 2a-13. KEY-003 价值分析BUY拦截 ===
        if dq_result:
            _vg = dq_result.get("key003_value_guard_block", 0)
            _vg_syms = dq_result.get("key003_value_guard_by_symbol", {})
            if _vg > 0:
                _vg_list = ", ".join(f"{s}({n}次)" for s, n in sorted(_vg_syms.items(), key=lambda x: -x[1]))
                lines.extend([
                    "---",
                    "",
                    "## KEY-003 价值分析BUY拦截 (v3.663)",
                    "",
                    f"- 拦截次数: {_vg}次",
                    f"- 涉及品种: {_vg_list}",
                    "",
                ])

        # === 2a-14. KEY-004 外挂品质与排名 ===
        if dq_result:
            _k4_evt = dq_result.get("key004_plugin_event", 0)
            _k4_src = dq_result.get("key004_plugin_by_source", {})
            _k4_state = safe_json_read("state/plugin_profit_state.json")
            if not _k4_state:
                _k4_state = safe_json_read("plugin_profit_state.json")
            _k4_quality = {}
            if _k4_state and isinstance(_k4_state, dict):
                _k4_quality = _k4_state.get("quality_snapshot", {}) if isinstance(_k4_state.get("quality_snapshot", {}), dict) else {}

            if _k4_evt > 0 or _k4_quality:
                lines.extend([
                    "---",
                    "",
                    "## KEY-004 外挂品质治理",
                    "",
                    f"- 外挂事件总数: {_k4_evt}",
                    "",
                ])
                if _k4_src:
                    lines.append("| 外挂source | dispatch | response | error | executed | failed |")
                    lines.append("|------------|----------|----------|-------|----------|--------|")
                    for _src, _v in sorted(_k4_src.items()):
                        lines.append(
                            f"| {_src} | {_v.get('dispatch', 0)} | {_v.get('response', 0)} | {_v.get('error', 0)} | {_v.get('executed', 0)} | {_v.get('failed', 0)} |"
                        )
                    lines.append("")

                for _atype, _label in (("crypto", "加密货币"), ("stock", "美股")):
                    _rows = _k4_quality.get(_atype, []) if isinstance(_k4_quality, dict) else []
                    if _rows:
                        lines.append(f"- {_label} 外挂质量Top3:")
                        for _r in _rows[:3]:
                            lines.append(f"  - {_r.get('plugin', '?')}: {_r.get('quality_score', 0):.1f} ({_r.get('quality_band', 'N/A')})")
                        lines.append("")

        # === 2a-14b. KEY-004 T06 治理+N字转换 ===
        if dq_result:
            _k4_gov = dq_result.get("key004_governance", 0)
            _k4_gov_dec = dq_result.get("key004_gov_decisions", {})
            _k4_nt = dq_result.get("key004_n_transition", 0)
            _k4_nt_sym = dq_result.get("key004_n_transition_by_symbol", {})
            _k4_ne = dq_result.get("key004_n_eval", 0)
            _k4_ne_out = dq_result.get("key004_n_eval_outcomes", {})
            if _k4_gov > 0 or _k4_nt > 0 or _k4_ne > 0:
                lines.extend([
                    "---",
                    "",
                    "## KEY-004 T06 治理过滤+N字转换追踪",
                    "",
                ])
                if _k4_gov > 0:
                    _dec_str = ", ".join(f"{k}:{v}" for k, v in sorted(_k4_gov_dec.items()))
                    lines.append(f"- 治理决策: {_k4_gov}次 ({_dec_str})")
                if _k4_nt > 0:
                    _nt_list = ", ".join(f"{k}:{v}" for k, v in sorted(_k4_nt_sym.items()))
                    lines.append(f"- N字转换事件: {_k4_nt}次 ({_nt_list})")
                if _k4_ne > 0:
                    _ne_str = ", ".join(f"{k}:{v}" for k, v in sorted(_k4_ne_out.items()))
                    _ne_correct = _k4_ne_out.get("CORRECT", 0)
                    _ne_rate = _ne_correct / _k4_ne * 100 if _k4_ne > 0 else 0
                    lines.append(f"- 转换评估: {_k4_ne}次 正确率={_ne_rate:.1f}% ({_ne_str})")
                lines.append("")

        # === 2a-15. KEY-005 行为金融增强层 ===
        if dq_result:
            _k5_bfi = dq_result.get("key005_bfi", 0)
            _k5_blk = dq_result.get("key005_dqs_block", 0)
            _k5_state = dq_result.get("key005_csi_state", {})
            _k5_hii_state = dq_result.get("key005_hii_state", {})
            _k5_by_symbol = dq_result.get("key005_by_symbol", {})
            _k5_dqs_sum = float(dq_result.get("key005_dqs_sum", 0.0))
            _k5_anchor = dq_result.get("key005_anchor", 0)
            _k5_mod = dq_result.get("key005_mod", 0)
            _k5_mod_risk = dq_result.get("key005_mod_by_risk", {})
            _k5_debias = dq_result.get("key005_debias", 0)
            _k5_anticheat = dq_result.get("key005_anticheat_block", 0)
            if _k5_bfi > 0:
                _k5_avg_dqs = _k5_dqs_sum / _k5_bfi
                _k5_state_str = ", ".join(f"{k}:{v}" for k, v in sorted(_k5_state.items()))
                _k5_hii_state_str = ", ".join(f"{k}:{v}" for k, v in sorted(_k5_hii_state.items()))
                lines.extend([
                    "---",
                    "",
                    "## KEY-005 行为金融增强层 (CSI/DQS)",
                    "",
                    f"- BFI评估次数: {_k5_bfi}",
                    f"- DQS禁止新开仓: {_k5_blk}次",
                    f"- Anchor观察记录: {_k5_anchor}次",
                    f"- 信号调节记录: {_k5_mod}次 ({', '.join(f'{k}:{v}' for k, v in sorted(_k5_mod_risk.items())) if _k5_mod_risk else 'N/A'})",
                    f"- 自我纠偏记录: {_k5_debias}次 | Anti-Cheat拦截: {_k5_anticheat}次",
                    f"- 平均DQS: {_k5_avg_dqs:.1f}",
                    f"- CSI状态分布: {_k5_state_str}",
                    f"- HII状态分布: {_k5_hii_state_str}",
                    "",
                ])
                if _k5_by_symbol:
                    lines.append("| 品种 | BFI评估 | DQS禁开仓 |")
                    lines.append("|------|---------|-----------|")
                    for _s, _v in sorted(_k5_by_symbol.items()):
                        lines.append(f"| {_s} | {_v.get('bfi', 0)} | {_v.get('dqs_block', 0)} |")
                    lines.append("")

        # === 2a-16. Signal Gate 微观结构过滤统计 ===
        if dq_result:
            _sg_go = dq_result.get("signal_gate_go", 0)
            _sg_nogo = dq_result.get("signal_gate_nogo", 0)
            _sg_blk = dq_result.get("signal_gate_block", 0)
            _sg_total = _sg_go + _sg_nogo
            _sg_syms = dq_result.get("signal_gate_by_symbol", {})
            if _sg_total > 0:
                _sg_rate = _sg_nogo / _sg_total * 100 if _sg_total > 0 else 0
                lines.extend([
                    "---",
                    "",
                    "## Signal Gate 微观结构过滤 (v3.660 Phase1观察)",
                    "",
                    f"- go={_sg_go} nogo={_sg_nogo} 拦截率={_sg_rate:.1f}% (Phase2实际拦截={_sg_blk}次)",
                    f"- 覆盖范围: 扫描引擎出口(所有外挂) + 主程序下单最后防线",
                    f"- 绿色通道豁免: 移动止损/移动止盈/暴跌平仓",
                    "",
                ])
                if _sg_syms:
                    lines.append("| 品种 | go | nogo |")
                    lines.append("|------|----|------|")
                    for _s, _v in sorted(_sg_syms.items()):
                        lines.append(f"| {_s} | {_v.get('go', 0)} | {_v.get('nogo', 0)} |")
                    lines.append("")

        # === 2a-17. FilterChain 三道闸门统计 (v3.671 Phase2主门控) ===
        if dq_result:
            _fc_pass_cnt = dq_result.get("filter_chain_pass", 0)
            _fc_bv   = dq_result.get("filter_chain_block_vision", 0)
            _fc_bvol = dq_result.get("filter_chain_block_volume", 0)
            _fc_bm   = dq_result.get("filter_chain_block_micro", 0)
            _fc_bw   = dq_result.get("filter_chain_block_weight", 0)
            _fc_int  = dq_result.get("filter_chain_intercept", 0)
            _fc_warn = dq_result.get("filter_chain_warn", 0)
            _fc_total = _fc_pass_cnt + _fc_bv + _fc_bvol + _fc_bm + _fc_bw
            _fc_syms = dq_result.get("filter_chain_by_symbol", {})
            # N字外挂
            _ns_buy  = dq_result.get("n_struct_buy", 0)
            _ns_sell = dq_result.get("n_struct_sell", 0)
            _ng_obs  = dq_result.get("n_gate_obs", 0)
            if _fc_total > 0 or _fc_int > 0 or _fc_warn > 0 or _ns_buy + _ns_sell > 0:
                _fc_pass_rate = _fc_pass_cnt / _fc_total * 100 if _fc_total > 0 else 0
                lines.extend([
                    "---",
                    "",
                    "## FilterChain 三道闸门 (v3.671 Phase2 Vision主门控)",
                    "",
                    f"- PASS={_fc_pass_cnt} BLOCK(vision={_fc_bv} vol={_fc_bvol} micro={_fc_bm} weight={_fc_bw}) 通过率={_fc_pass_rate:.1f}%",
                    f"- 实际拦截={_fc_int}次 | 数据告警={_fc_warn}次(过期/缺失→fail-open)",
                    f"- 覆盖路径: 扫描引擎 + P0 + 3Commas + SignalStack + L1L2",
                    f"- N字外挂: BUY={_ns_buy} SELL={_ns_sell} | N字观察(不拦截)={_ng_obs}次",
                    "",
                ])
                if _fc_syms:
                    lines.append("| 品种 | PASS | Vision拦 | Volume拦 | Micro拦 | Weight拦 |")
                    lines.append("|------|------|----------|----------|---------|----------|")
                    for _s, _v in sorted(_fc_syms.items()):
                        lines.append(f"| {_s} | {_v.get('pass',0)} | {_v.get('vision',0)} | {_v.get('volume',0)} | {_v.get('micro',0)} | {_v.get('weight',0)} |")
                    lines.append("")

        # === 2a-18. KEY-007 KNN进化双引擎 (Vision KNN + Plugin KNN) ===
        if dq_result:
            # Vision KNN 过滤统计
            _vf_blk = dq_result.get("vision_filter_block", 0)
            _vf_err = dq_result.get("vision_filter_error", 0)
            _vf_load_ok = dq_result.get("vision_filter_load_ok", 0)
            _vf_load_fail = dq_result.get("vision_filter_load_fail", 0)
            _vf_blk_sym = dq_result.get("vision_filter_block_by_symbol", {})
            # Plugin KNN 查询统计
            _pk_query = dq_result.get("plugin_knn_query", 0)
            _pk_suppress = dq_result.get("plugin_knn_suppress", 0)
            _pk_bypass = dq_result.get("plugin_knn_bypass", 0)
            _pk_knowledge = dq_result.get("plugin_knn_knowledge", 0)
            _pk_kb_rules = dq_result.get("plugin_knn_knowledge_rules_total", 0)
            _pk_error = dq_result.get("plugin_knn_error", 0)
            _pk_by_plugin = dq_result.get("plugin_knn_query_by_plugin", {})
            _pk_sup_by = dq_result.get("plugin_knn_suppress_by_plugin", {})
            _pk_byp_by = dq_result.get("plugin_knn_bypass_by_plugin", {})
            _pk_wr_sum = float(dq_result.get("plugin_knn_wr_sum", 0.0))
            _pk_conf_sum = float(dq_result.get("plugin_knn_conf_sum", 0.0))
            # KNN维护
            _knn_bs = dq_result.get("knn_bootstrap", 0)
            _knn_bs_st = dq_result.get("knn_bootstrap_status", "")
            _knn_inc_ok = dq_result.get("knn_incremental_ok", 0)
            _knn_inc_fail = dq_result.get("knn_incremental_fail", 0)

            _has_knn_data = (_vf_blk + _vf_err + _vf_load_ok + _vf_load_fail +
                             _pk_query + _pk_suppress + _pk_bypass + _pk_error +
                             _knn_bs + _knn_inc_ok + _knn_inc_fail) > 0

            if _has_knn_data:
                lines.extend([
                    "---",
                    "",
                    "## KEY-007 KNN进化双引擎 (Vision宏观 + Plugin微观)",
                    "",
                ])

                # Vision KNN Section
                lines.append("### Vision KNN (宏观: 值不值得买卖)")
                lines.append("")
                if _vf_load_fail > 0:
                    lines.append(f"- **⚠ 模块加载失败**: {_vf_load_fail}次 — Vision KNN完全不可用!")
                elif _vf_load_ok > 0:
                    lines.append(f"- 模块加载: 成功")
                lines.append(f"- 拦截次数: {_vf_blk}次 | 异常: {_vf_err}次")
                if _vf_blk_sym:
                    _vf_sym_str = ", ".join(f"{s}:{c}" for s, c in sorted(_vf_blk_sym.items(), key=lambda x: -x[1]))
                    lines.append(f"- 拦截品种: {_vf_sym_str}")
                # KNN维护状态
                if _knn_bs > 0:
                    lines.append(f"- Bootstrap: {_knn_bs_st}")
                lines.append(f"- 增量更新: 成功{_knn_inc_ok}次 失败{_knn_inc_fail}次")
                # 加载knn_accuracy_map
                try:
                    import json as _json
                    _acc_path = "state/knn_accuracy_map.json"
                    with open(_acc_path, encoding="utf-8") as _af:
                        _acc_map = _json.load(_af)
                    _acc_vals = [v for v in _acc_map.values() if isinstance(v, (int, float))]
                    if _acc_vals:
                        _acc_avg = sum(_acc_vals) / len(_acc_vals) * 100
                        _acc_min_sym = min(_acc_map.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 999)
                        _bypass_cnt = sum(1 for v in _acc_vals if v < 0.55)
                        lines.append(f"- 准确率: 平均{_acc_avg:.1f}% ({len(_acc_vals)}品种) | bypass={_bypass_cnt}品种 | 最低={_acc_min_sym[0]}({_acc_min_sym[1]*100:.1f}%)")
                except Exception:
                    lines.append("- 准确率: knn_accuracy_map.json不可读")
                lines.append("")

                # Plugin KNN Section
                lines.append("### Plugin KNN (微观: 是不是好的买卖点)")
                lines.append("")
                if _pk_error > 0:
                    lines.append(f"- **⚠ 历史库读写失败**: {_pk_error}次")
                _pk_avg_wr = _pk_wr_sum / _pk_query if _pk_query > 0 else 0
                _pk_avg_conf = _pk_conf_sum / _pk_query if _pk_query > 0 else 0
                lines.append(f"- KNN查询: {_pk_query}次 | 平均胜率={_pk_avg_wr:.1f}% 平均置信={_pk_avg_conf:.2f}")
                lines.append(f"- Phase2抑制: {_pk_suppress}次 | bypass(低准确率): {_pk_bypass}次")
                lines.append(f"- 知识卡增强: {_pk_knowledge}次命中, 累计{_pk_kb_rules}条规则匹配")
                lines.append("")

                # 按外挂分表
                if _pk_by_plugin:
                    lines.append("| 外挂 | 查询 | 顺向 | 逆向 | 抑制 | bypass |")
                    lines.append("|------|------|------|------|------|--------|")
                    for _pl, _v in sorted(_pk_by_plugin.items()):
                        _agree = _v.get("buy_agree", 0) + _v.get("sell_agree", 0)
                        _contrary = _v.get("contrary", 0)
                        _sup = _pk_sup_by.get(_pl, 0)
                        _byp = _pk_byp_by.get(_pl, 0)
                        lines.append(f"| {_pl} | {_v.get('total',0)} | {_agree} | {_contrary} | {_sup} | {_byp} |")
                    lines.append("")

                # 加载Plugin KNN历史库统计
                try:
                    import numpy as _np
                    _pkdb = _np.load("state/plugin_knn_history.npz", allow_pickle=True)["db"].item()
                    _pk_keys = len(_pkdb)
                    _pk_samples = sum(len(v.get("features", [])) for v in _pkdb.values())
                    lines.append(f"- 历史库: {_pk_keys} keys, {_pk_samples:,} samples")
                except Exception:
                    lines.append("- 历史库: plugin_knn_history.npz不可读")
                # pending
                try:
                    with open("state/plugin_knn_pending.json", encoding="utf-8") as _pf:
                        _pending = _json.load(_pf)
                    lines.append(f"- Pending回填: {len(_pending)}条待回填 (S8:每4h回填未接入)")
                except Exception:
                    lines.append("- Pending回填: 文件不可读")
                # accuracy
                try:
                    with open("state/plugin_knn_accuracy.json", encoding="utf-8") as _paf:
                        _pk_acc = _json.load(_paf)
                    lines.append(f"- Plugin准确率: {len(_pk_acc)}个key已追踪")
                except FileNotFoundError:
                    lines.append("- Plugin准确率: **文件不存在** (S8: accuracy追踪未实现)")
                except Exception:
                    lines.append("- Plugin准确率: 文件读取异常")
                lines.append("")

                # S7-S10 进度提示
                lines.extend([
                    "### KEY-007 进化路线进度",
                    "",
                    "| 阶段 | 状态 | 健康指标 |",
                    "|------|------|----------|",
                ])
                # S7: Vision KNN纠正闭环
                _s7_health = "✅" if _knn_inc_ok > 0 and _knn_inc_fail == 0 else ("⚠" if _knn_inc_fail > 0 else "❓无数据")
                lines.append(f"| S7 Vision KNN纠正 | 增量4h={_knn_inc_ok}ok/{_knn_inc_fail}fail | {_s7_health} |")
                # S8: Plugin KNN回填闭环
                try:
                    _s8_pending = len(_pending)
                except NameError:
                    _s8_pending = -1
                _s8_health = "⚠待接入" if _s8_pending > 0 else ("✅" if _s8_pending == 0 else "❓")
                lines.append(f"| S8 Plugin KNN回填 | pending={_s8_pending} | {_s8_health} |")
                # S9: 论文→Vision
                lines.append(f"| S9 论文→Vision | Prompt固定 | ⏳规划中 |")
                # S10: 论文→外挂
                _s10_rules = 10  # 已知5外挂10条
                lines.append(f"| S10 论文→外挂 | {_s10_rules}条知识规则/5外挂 | ⏳规划中 |")
                lines.append("")

        # === 2a-19. GCC-0171 管线A审计: Vision拦截准确率 ===
        if dq_result:
            _va_correct = dq_result.get("vf_eval_correct", 0)
            _va_incorrect = dq_result.get("vf_eval_incorrect", 0)
            _va_total = _va_correct + _va_incorrect
            _va_promote = dq_result.get("vf_promote", 0)
            _va_demote = dq_result.get("vf_demote", 0)
            _va_by_sym = dq_result.get("vf_eval_by_symbol", {})
            _va_transitions = dq_result.get("vf_phase_transitions", [])
            _va_snapshot = dq_result.get("vf_acc_snapshot", "")
            _va_3day = dq_result.get("vf_3day_review", 0)

            if _va_total > 0 or _va_promote + _va_demote > 0 or _va_3day > 0:
                _va_rate = _va_correct / _va_total * 100 if _va_total > 0 else 0
                lines.extend([
                    "---",
                    "",
                    "## GCC-0171 管线A审计: Vision拦截准确率",
                    "",
                    f"- 回填评估: {_va_total}次 (正确={_va_correct} 错误={_va_incorrect} 准确率={_va_rate:.1f}%)",
                    f"- Phase切换: 升级={_va_promote}次 降级={_va_demote}次 | 3天评估={_va_3day}次",
                ])
                if _va_snapshot:
                    lines.append(f"- 最新快照: {_va_snapshot}")
                lines.append("")

                if _va_by_sym:
                    lines.append("| 品种 | 正确 | 错误 | 准确率 |")
                    lines.append("|------|------|------|--------|")
                    for _s, _v in sorted(_va_by_sym.items()):
                        _c = _v.get("correct", 0)
                        _ic = _v.get("incorrect", 0)
                        _t = _c + _ic
                        _r = _c / _t * 100 if _t > 0 else 0
                        lines.append(f"| {_s} | {_c} | {_ic} | {_r:.1f}% |")
                    lines.append("")

                if _va_transitions:
                    lines.append("### Phase切换事件")
                    for _tr in _va_transitions:
                        lines.append(f"- {_tr}")
                    lines.append("")

                # 读取state文件补充Phase状态
                try:
                    import json as _json
                    with open("state/vision_filter_accuracy.json", encoding="utf-8") as _vaf:
                        _va_data = _json.load(_vaf)
                    _va_acc = _va_data.get("accuracy", {})
                    if _va_acc:
                        lines.append("### 品种Phase状态")
                        lines.append("")
                        lines.append("| 品种 | 准确率 | 样本 | Phase | 最近切换 |")
                        lines.append("|------|--------|------|-------|----------|")
                        for _s, _v in sorted(_va_acc.items()):
                            _a = _v.get("accuracy", 0)
                            _n = _v.get("samples", 0)
                            _p = _v.get("phase", 1)
                            _lt = _v.get("last_transition", "-")
                            _ld = _v.get("last_direction", "")
                            _tag = f"Phase{_p}"
                            if _ld:
                                _tag += f" ({_ld})"
                            lines.append(f"| {_s} | {_a:.0%} | {_n} | {_tag} | {_lt} |")
                        lines.append("")
                except Exception:
                    pass

        # === 2a-20. GCC-0172 管线B审计: BrooksVision形态准确率 ===
        if dq_result:
            _bv_correct = dq_result.get("bv_eval_correct", 0)
            _bv_incorrect = dq_result.get("bv_eval_incorrect", 0)
            _bv_neutral = dq_result.get("bv_eval_neutral", 0)
            _bv_total = _bv_correct + _bv_incorrect + _bv_neutral
            _bv_gate = dq_result.get("bv_gate_blocked", 0)
            _bv_by_pat = dq_result.get("bv_eval_by_pattern", {})
            _bv_gate_pat = dq_result.get("bv_gate_by_pattern", {})

            # 也读state文件补充回测数据
            _bv_state = {}
            try:
                import json as _json
                with open("state/bv_signal_accuracy.json", encoding="utf-8") as _bvf:
                    _bv_state = _json.load(_bvf)
            except Exception:
                pass

            _bv_overall = _bv_state.get("overall", {})
            _bv_patterns = _bv_state.get("patterns", {})

            if _bv_total > 0 or _bv_gate > 0 or _bv_overall:
                _bv_rate = _bv_correct / (_bv_correct + _bv_incorrect) * 100 if (_bv_correct + _bv_incorrect) > 0 else 0
                lines.extend([
                    "---",
                    "",
                    "## GCC-0172 管线B审计: BrooksVision形态准确率",
                    "",
                ])
                if _bv_overall:
                    lines.append(
                        f"- 回测总计: {_bv_overall.get('decisive', _bv_overall.get('total', 0))}decisive信号, "
                        f"准确率={_bv_overall.get('accuracy', 0):.1%}")
                if _bv_total > 0:
                    lines.append(
                        f"- 本期日志: {_bv_total}次评估 "
                        f"(正确={_bv_correct} 错误={_bv_incorrect} neutral={_bv_neutral} "
                        f"准确率={_bv_rate:.1f}%)")
                if _bv_gate > 0:
                    lines.append(f"- Phase1拦截: {_bv_gate}次")
                lines.append("")

                if _bv_patterns:
                    lines.append("| 形态 | 总数 | 准确率 | 高胜率品种 | 低胜率品种 |")
                    lines.append("|------|------|--------|-----------|-----------|")
                    for _bp, _pd in sorted(_bv_patterns.items(), key=lambda x: -x[1].get("decisive", x[1].get("total", 0))):
                        _bt = _pd.get("decisive", _pd.get("total", 0))
                        if _bt < 3:
                            continue
                        _ba = _pd.get("accuracy", 0)
                        _syms = _pd.get("symbols", {})
                        _hi = [f"{s}({d['accuracy']:.0%})" for s, d in _syms.items()
                               if d.get("decisive", d.get("total", 0)) >= 5 and d.get("accuracy", 0) >= 0.6]
                        _lo = [f"{s}({d['accuracy']:.0%})" for s, d in _syms.items()
                               if d.get("decisive", d.get("total", 0)) >= 5 and d.get("accuracy", 0) < 0.35]
                        lines.append(
                            f"| {_bp} | {_bt} | {_ba:.1%} | "
                            f"{', '.join(_hi) if _hi else '-'} | "
                            f"{', '.join(_lo) if _lo else '-'} |")
                    lines.append("")

        # === 2a-21. GCC-0173 管线C审计: MACD背离准确率 ===
        _macd_state = {}
        try:
            import json as _json
            with open("state/macd_signal_accuracy.json", encoding="utf-8") as _maf:
                _macd_state = _json.load(_maf)
        except Exception:
            pass

        _macd_overall = _macd_state.get("overall", {})
        _macd_entries = _macd_state.get("entries", {})
        _macd_gate = dq_result.get("macd_gate_blocked", 0) if dq_result else 0

        if _macd_overall or _macd_gate > 0:
            lines.extend([
                "---",
                "",
                "## GCC-0173 管线C审计: MACD背离准确率",
                "",
            ])
            if _macd_overall:
                lines.append(
                    f"- 回测总计: {_macd_overall.get('decisive', 0)}decisive, "
                    f"准确率={_macd_overall.get('accuracy', 0):.1%}")
            if _macd_gate > 0:
                lines.append(f"- Phase1收紧拦截: {_macd_gate}次")
            lines.append("")

            if _macd_entries:
                lines.append("| 品种 | 类型 | decisive | 准确率 | Phase |")
                lines.append("|------|------|----------|--------|-------|")
                for _mk, _me in sorted(_macd_entries.items(), key=lambda x: -x[1].get("decisive", 0)):
                    _md = _me.get("decisive", 0)
                    if _md < 1:
                        continue
                    _ma = _me.get("accuracy", 0)
                    _mp = _me.get("suggested_phase", 0)
                    _ml = {0: "样本不足", 1: "收紧", 2: "信任"}.get(_mp, "?")
                    lines.append(
                        f"| {_me.get('symbol','')} | {_me.get('div_type','')} | "
                        f"{_md} | {_ma:.1%} | Phase{_mp}({_ml}) |")
                lines.append("")

        # === 2a-22. GCC-0174 知识卡活化: CardBridge ===
        if dq_result:
            _cb_match = dq_result.get("card_match_count", 0)
            _cb_distill = dq_result.get("card_distill_count", 0)
            _cb_error = dq_result.get("card_error_count", 0)
            _cb_cards = dq_result.get("card_match_cards", [])
            _cb_by_sym = dq_result.get("card_match_by_symbol", {})
            _cb_snap = dq_result.get("card_distill_snapshot", "")
            _cb_phase_gate = dq_result.get("card_phase_gate_count", 0)
            _cb_phase_by_sym = dq_result.get("card_phase_gate_by_symbol", {})
            _cb_backfill = dq_result.get("card_acc_backfill_total", 0)

            if _cb_match > 0 or _cb_distill > 0 or _cb_error > 0 or _cb_phase_gate > 0:
                lines.extend([
                    "---",
                    "",
                    "## GCC-0174 知识卡活化: CardBridge",
                    "",
                    f"- 因果匹配: {_cb_match}次 (涉及{len(_cb_cards)}张卡)",
                    f"- 蒸馏执行: {_cb_distill}次",
                ])
                if _cb_phase_gate > 0:
                    lines.append(f"- Phase1拦截: {_cb_phase_gate}次")
                if _cb_backfill > 0:
                    lines.append(f"- 4H回填: +{_cb_backfill}条")
                if _cb_error > 0:
                    lines.append(f"- ⚠️ 异常: {_cb_error}次")
                if _cb_snap:
                    lines.append(f"- 蒸馏快照: {_cb_snap}")
                lines.append("")

                if _cb_by_sym:
                    lines.append("| 品种 | 因果匹配 | Phase1拦截 |")
                    lines.append("|------|---------|-----------|")
                    _all_syms = set(list(_cb_by_sym.keys()) + list(_cb_phase_by_sym.keys()))
                    for _s in sorted(_all_syms):
                        lines.append(
                            f"| {_s} | {_cb_by_sym.get(_s, 0)} | "
                            f"{_cb_phase_by_sym.get(_s, 0)} |")
                    lines.append("")

                if _cb_cards:
                    lines.append(f"- 激活卡片: {', '.join(sorted(_cb_cards))}")
                    lines.append("")

        # === 2b. 4方校准准确率 (v3.640) ===
        dual_track = safe_json_read(CONFIG["data_files"]["human_dual_track"])
        dt_stats = dual_track.get("stats", {}) if dual_track else {}
        if dt_stats:
            lines.extend([
                "",
                "### 4方校准准确率 (v3.640: 谁准用谁)",
                "",
                "| 品种 | 缠论 | Vision | x4道氏 | x4缠论 | 采用 |",
                "|------|------|--------|--------|--------|------|",
            ])

            def _calc_acc(s, prefix):
                total = s.get(f"{prefix}_total", 0)
                correct = s.get(f"{prefix}_correct", 0)
                return correct / total if total >= 5 else None

            def _fmt_acc(v):
                return f"{v:.1%}" if v is not None else "---"

            for sym, data in sorted(dt_stats.items()):
                if not isinstance(data, dict):
                    continue
                rule_acc = _calc_acc(data, "rule")
                vision_acc = _calc_acc(data, "vision")
                x4_dow_acc = _calc_acc(data, "x4_dow")
                x4_chan_acc = _calc_acc(data, "x4_chan")

                # 判断采用来源
                l1_using = "缠论"
                if vision_acc is not None and rule_acc is not None and vision_acc > rule_acc:
                    l1_using = "Vision"
                x4_using = "道氏"
                if x4_chan_acc is not None and x4_dow_acc is not None and x4_chan_acc > x4_dow_acc:
                    x4_using = "缠论"
                using = f"{l1_using}+x4{x4_using}"

                lines.append(
                    f"| {sym} | {_fmt_acc(rule_acc)} | {_fmt_acc(vision_acc)} | "
                    f"{_fmt_acc(x4_dow_acc)} | {_fmt_acc(x4_chan_acc)} | {using} |"
                )
            lines.append("")

        # === 2c. 外挂信号追踪 (v3.3) ===
        if plugin_result and plugin_result.get("total_triggered", 0) > 0:
            lines.extend([
                "",
                "### 外挂信号追踪 (v3.3: 全生命周期)",
                "",
                f"- 总触发: {plugin_result['total_triggered']}次",
                f"- 总执行: {plugin_result['total_executed']}次",
                f"- 总阻止: {plugin_result['total_blocked']}次",
                f"- 执行率: {plugin_result['total_executed']/plugin_result['total_triggered']*100:.0f}%"
                if plugin_result['total_triggered'] > 0 else "",
                "",
                "| 外挂 | 触发 | 执行 | 阻止 | 主要阻止原因 |",
                "|------|------|------|------|-------------|",
            ])
            for plugin, pdata in sorted(plugin_result.get("plugins", {}).items()):
                triggered = pdata.get("triggered", 0)
                executed = pdata.get("executed", 0)
                blocked = pdata.get("blocked", 0)
                reasons = pdata.get("block_reasons", {})
                top_reason = max(reasons, key=reasons.get) if reasons else "-"
                top_count = reasons.get(top_reason, 0) if reasons else 0
                reason_str = f"{top_reason}({top_count})" if reasons else "-"
                lines.append(f"| {plugin} | {triggered} | {executed} | {blocked} | {reason_str} |")

            lines.append("")

            # 按品种细分 (只显示有阻止的品种)
            has_blocked_detail = False
            for plugin, pdata in sorted(plugin_result.get("plugins", {}).items()):
                for sym, sdata in sorted(pdata.get("by_symbol", {}).items()):
                    if sdata.get("blocked", 0) > 0:
                        if not has_blocked_detail:
                            lines.extend([
                                "**阻止明细 (按品种)**:",
                                "",
                            ])
                            has_blocked_detail = True
                        reasons_str = ", ".join(f"{r}:{c}" for r, c in sdata.get("block_reasons", {}).items())
                        lines.append(f"- {plugin}/{sym}: 触发{sdata['triggered']} 执行{sdata['executed']} 阻止{sdata['blocked']} ({reasons_str})")

            if has_blocked_detail:
                lines.append("")

            # P0端点统计
            p0 = plugin_result.get("p0_stats", {})
            if any(p0.values()):
                lines.extend([
                    "**P0端点统计**:",
                    f"- 执行: {p0.get('executed', 0)} | 失败: {p0.get('failed', 0)} | 去重: {p0.get('dedup', 0)} | 满仓拒绝: {p0.get('full_position', 0)}",
                    f"- 收到: {p0.get('received', 0)} | 限次: {p0.get('daily_limit', 0)} | 仓位偏差: {p0.get('pos_mismatch', 0)} | 冷却: {p0.get('cooldown', 0)}",
                    "",
                ])

            # profit_state交叉验证
            profit = plugin_result.get("profit_state", {})
            if profit:
                lines.extend(["**利润追踪器验证**:", ""])
                for market, plugins in sorted(profit.items()):
                    if isinstance(plugins, dict):
                        for pname, pinfo in sorted(plugins.items()):
                            if isinstance(pinfo, dict):
                                sig = pinfo.get("signals", 0)
                                exe = pinfo.get("executed", 0)
                                lines.append(f"- {market}/{pname}: 信号{sig} 执行{exe}")
                lines.append("")

        # === 2d. API/网络错误 (P1-3) ===
        api_errors = logic_result.get("api_errors", 0)
        order_errors = logic_result.get("order_errors", 0)
        if api_errors > 0 or order_errors > 0:
            lines.extend([
                "",
                "### API/网络错误追踪 (P1-3: 隐性丢单检测)",
                "",
                f"- API/网络错误: {api_errors}次",
                f"- 下单执行失败: {order_errors}次",
            ])
            for detail in logic_result.get("api_error_details", [])[:5]:
                lines.append(f"  - [{detail['time']}] {detail['symbol']} {detail['type']}: {detail['line'][:80]}")
            if api_errors + order_errors > 0:
                lines.append(f"- **警告**: {api_errors + order_errors}次错误可能导致信号丢失!")
            lines.append("")

        # === 2e. 外挂盈亏归因 (P0-3) ===
        if plugin_pnl and (plugin_pnl.get("entries") or plugin_pnl.get("exits")):
            lines.extend([
                "",
                "### 外挂盈亏归因 (P0-3: 谁赚谁亏)",
                "",
                "**入场来源 (BUY触发方)**:",
                "",
                "| 来源 | 配对数 | 胜率 | 平均盈亏 | 累计盈亏 |",
                "|------|--------|------|----------|----------|",
            ])
            for src, d in sorted(plugin_pnl.get("entries", {}).items(),
                                  key=lambda x: x[1]["total_pnl_pct"], reverse=True):
                lines.append(
                    f"| {src} | {d['count']} | {d['win_rate']}% | "
                    f"{d['avg_pnl_pct']:+.2f}% | {d['total_pnl_pct']:+.2f}% |"
                )
            lines.extend([
                "",
                "**出场来源 (SELL触发方)**:",
                "",
                "| 来源 | 配对数 | 胜率 | 平均盈亏 | 累计盈亏 |",
                "|------|--------|------|----------|----------|",
            ])
            for src, d in sorted(plugin_pnl.get("exits", {}).items(),
                                  key=lambda x: x[1]["total_pnl_pct"], reverse=True):
                lines.append(
                    f"| {src} | {d['count']} | {d['win_rate']}% | "
                    f"{d['avg_pnl_pct']:+.2f}% | {d['total_pnl_pct']:+.2f}% |"
                )
            lines.append("")

        # === 2f. 趋势预测验证 (P1-1) ===
        if trend_validation and trend_validation.get("validated", 0) > 0:
            tv = trend_validation
            lines.extend([
                "",
                "### 趋势预测验证 (P1-1: L1预测事后对账)",
                "",
                f"- 趋势切换事件: {tv['total_changes']}次",
                f"- 已验证: {tv['validated']}次",
                f"- 正确: {tv['correct']}次 | 错误: {tv['incorrect']}次",
                f"- **独立验证准确率: {tv['accuracy']}%**",
                "",
            ])
            wrong_details = [d for d in tv.get("details", []) if not d.get("correct")]
            if wrong_details:
                lines.append("错误预测明细:")
                for d in wrong_details[:5]:
                    lines.append(
                        f"  - [{d['ts']}] {d['symbol']} 预测{d['prediction']} → "
                        f"实际{d['hours']}h {d['price_change_pct']:+.1f}%"
                    )
                lines.append("")

        # === 2g. 被拒信号回测 (P1-2) ===
        if rejected_backtest and rejected_backtest.get("total_backtested", 0) > 0:
            rb = rejected_backtest
            lines.extend([
                "",
                "### 被拒信号回测 (P1-2: 过滤条件有效性)",
                "",
                f"- 回测信号: {rb['total_backtested']}个",
                f"- 错过盈利: {rb['would_profit']}个 (累计+{rb['missed_profit_pct']:.1f}%)",
                f"- 成功避损: {rb['would_loss']}个 (累计避免-{rb['avoided_loss_pct']:.1f}%)",
                f"- **过滤有效率: {100 - (rb.get('profit_rate') or 0):.0f}%** (拒绝的信号中{100 - (rb.get('profit_rate') or 0):.0f}%确实该拒)",
                "",
            ])
            # 按拒绝原因分析
            by_reason = rb.get("by_reason", {})
            if by_reason:
                lines.extend([
                    "按拒绝原因分析:",
                    "",
                    "| 原因 | 总数 | 错过盈利 | 成功避损 | 有效率 |",
                    "|------|------|----------|----------|--------|",
                ])
                for reason, rd in sorted(by_reason.items(), key=lambda x: x[1]["count"], reverse=True):
                    eff = rd["loss"] / rd["count"] * 100 if rd["count"] else 0
                    lines.append(
                        f"| {reason[:30]} | {rd['count']} | {rd['profit']} | {rd['loss']} | {eff:.0f}% |"
                    )
                lines.append("")

            # 重大错过
            big_misses = [d for d in rb.get("details", []) if d.get("hyp_pnl_pct", 0) > 1.5]
            if big_misses:
                lines.append("**重大错过 (假设盈亏>1.5%)**:")
                for d in big_misses[:5]:
                    lines.append(
                        f"  - [{d['ts']}] {d['symbol']} {d['signal']} "
                        f"入场{d['entry']}→4h后{d['exit_4h']} "
                        f"(+{d['hyp_pnl_pct']:.1f}%) 原因:{d['reason'][:25]}"
                    )
                lines.append("")

        # === 3. 多余交易检测 ===
        lines.extend([
            "---",
            "",
            "## 3. 多余交易检测",
            "",
        ])
        if redundant_result:
            lines.extend([
                f"- 同K线反复交易: {len(redundant_result.get('same_bar_trades', []))}组",
                f"- 亏损交易: {len(redundant_result.get('loss_trades', []))}笔",
                f"- 亏损金额: ${redundant_result.get('total_loss_amount', 0):.2f}",
                f"- 无效交易(小盈亏): {len(redundant_result.get('churn_trades', []))}组",
            ])
        else:
            lines.append("无多余交易检测数据")
        lines.append("")

        # === 4. 买卖节奏分析 ===
        lines.extend([
            "---",
            "",
            "## 4. 买卖节奏分析",
            "",
        ])
        if rhythm_result:
            lines.extend([
                f"### 综合评分: {rhythm_result.get('overall_score', 0)}/100",
                "",
                f"- 买入评分: {rhythm_result.get('buy_score', 0)}/100 ({rhythm_result.get('buy_count', 0)}笔)",
                f"- 卖出评分: {rhythm_result.get('sell_score', 0)}/100 ({rhythm_result.get('sell_count', 0)}笔)",
                f"- 优质买入比例 (pos < 0.4): {rhythm_result.get('excellent_buy_ratio', 0)}%",
                f"- 优质卖出比例 (pos > 0.6): {rhythm_result.get('excellent_sell_ratio', 0)}%",
                f"- 高位追买次数: {rhythm_result.get('bad_buys', 0)}",
                f"- 低位割肉次数: {rhythm_result.get('bad_sells', 0)}",
                "",
                "### 质量分布",
                "",
                "| 等级 | BUY | SELL | 位置区间 |",
                "|------|-----|------|----------|",
            ])
            position_ranges = {
                "EXCELLENT": "BUY: <20% / SELL: >80%",
                "GOOD": "BUY: 20-40% / SELL: 60-80%",
                "NEUTRAL": "40-60%",
                "POOR": "BUY: 60-80% / SELL: 20-40%",
                "TERRIBLE": "BUY: >80% / SELL: <20%"
            }
            for quality in TradeQuality:
                bd = rhythm_result.get("quality_breakdown", {}).get(quality.value, {"buy": 0, "sell": 0})
                lines.append(f"| {quality.value} | {bd['buy']} | {bd['sell']} | {position_ranges.get(quality.value, '')} |")
        else:
            lines.append("无节奏分析数据")
        lines.append("")

        # === 5. 每日改善建议 ===
        lines.extend([
            "---",
            "",
            "## 5. 📋 今日改善建议",
            "",
        ])
        if suggestions:
            for i, s in enumerate(suggestions, 1):
                priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(s.priority, "⚪")
                lines.extend([
                    f"### {i}. {priority_icon} [{s.priority}] {s.title}",
                    "",
                    f"**类别**: {s.category}",
                    f"**问题**: {s.detail}",
                    f"**建议**: {s.action}",
                    "",
                ])
        else:
            lines.append("今日无改善建议，交易状态良好！")
        lines.append("")

        # === 6. 严重问题详情 ===
        critical_issues = detector.get_issues_by_level("CRITICAL")
        if critical_issues:
            lines.extend([
                "---",
                "",
                "## 6. ⚠️ 严重问题详情",
                "",
            ])
            for issue in critical_issues[:10]:
                lines.extend([
                    f"- **[{issue.category}] {issue.symbol}**: {issue.description}",
                    f"  - 建议: {issue.suggestion}",
                ])
            lines.append("")

        # === 7. 本周累计来回买卖检测 ===
        if cumulative_whipsaw and cumulative_whipsaw.get("whipsaw_symbols"):
            ws = cumulative_whipsaw
            ws_summary = ws.get("summary", {})
            lines.extend([
                "---",
                "",
                "## 7. 本周累计来回买卖检测 (Whipsaw)",
                "",
                f"统计范围: 本周一至今 | 累计交易: {ws_summary.get('total_symbols', 0)}个品种",
                "",
            ])
            lines.extend([
                f"检测到 **{ws_summary.get('whipsaw_count', 0)}** 个品种存在来回翻转 (>={WhipsawDetector.FLIP_THRESHOLD}次方向切换)",
                "",
                "| 品种 | 交易序列 | 翻转次数 | 净盈亏 | 平均持仓 |",
                "|------|----------|----------|--------|----------|",
            ])
            for sym in sorted(ws["whipsaw_symbols"], key=lambda x: x["net_pnl"]):
                lines.append(
                    f"| {sym['symbol']} | {sym['sequence_str']} | {sym['direction_flips']}次 | "
                    f"${sym['net_pnl']:+.2f} | {sym['avg_hold_hours']:.1f}h |"
                )
            lines.append("")

            total_ws_loss = ws_summary.get("total_whipsaw_loss", 0)
            if total_ws_loss < 0:
                lines.append(f"**来回交易累计亏损: ${total_ws_loss:.2f}**")
                lines.append("")
        elif cumulative_whipsaw:
            lines.extend([
                "---",
                "",
                "## 7. 本周累计来回买卖检测 (Whipsaw)",
                "",
                "本周累计未检测到来回翻转品种",
                "",
            ])

        # === TESTING项自动验证 (v3.653闭环) ===
        if testing_results:
            verifier = TestingVerifier()
            lines.extend(verifier.format_report(testing_results))

        lines.extend([
            "=" * 70,
            f"报告生成完成",
            "=" * 70,
        ])

        return "\n".join(lines)

    def generate_weekly_report(self, week_start: str, week_end: str,
                                daily_summaries: List[Dict],
                                suggestions: List[ImprovementSuggestion],
                                whipsaw_result: Dict = None) -> str:
        """生成每周分析报告"""
        lines = [
            "=" * 70,
            f"📊 每周交易分析报告",
            f"📅 周期: {week_start} ~ {week_end}",
            "=" * 70,
            f"🕐 生成时间: {get_ny_now().strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)",
            "",
        ]

        # === 1. 周统计汇总 ===
        total_trades = sum(d.get("trade_count", 0) for d in daily_summaries)
        total_loss = sum(d.get("loss_amount", 0) for d in daily_summaries)
        avg_rhythm = sum(d.get("rhythm_score", 50) for d in daily_summaries) / len(daily_summaries) if daily_summaries else 0

        lines.extend([
            "## 1. 周统计汇总",
            "",
            f"- 总交易笔数: {total_trades}",
            f"- 累计亏损金额: ${total_loss:.2f}",
            f"- 平均节奏评分: {avg_rhythm:.1f}/100",
            "",
        ])

        # === 2. 每日明细 ===
        lines.extend([
            "---",
            "",
            "## 2. 每日明细",
            "",
            "| 日期 | 交易数 | 节奏评分 | 亏损金额 | 同K线交易 | 逻辑错误 |",
            "|------|--------|----------|----------|-----------|----------|",
        ])
        for d in daily_summaries:
            lines.append(
                f"| {d.get('date', 'N/A')} | {d.get('trade_count', 0)} | "
                f"{d.get('rhythm_score', 0):.1f} | ${d.get('loss_amount', 0):.2f} | "
                f"{d.get('same_bar_count', 0)} | {d.get('logic_errors', 0)} |"
            )
        lines.append("")

        # === 3. 跨天来回买卖检测 ===
        lines.extend([
            "---",
            "",
            "## 3. 跨天来回买卖检测 (Whipsaw)",
            "",
        ])
        if whipsaw_result and whipsaw_result.get("whipsaw_symbols"):
            ws = whipsaw_result
            lines.extend([
                f"检测到 **{ws['summary']['whipsaw_count']}** 个品种存在来回翻转 (>={WhipsawDetector.FLIP_THRESHOLD}次方向切换)",
                "",
                "### 来回翻转品种",
                "",
                "| 品种 | 交易序列 | 翻转次数 | 净盈亏 | 平均持仓 | 交易笔数 |",
                "|------|----------|----------|--------|----------|----------|",
            ])
            for sym in sorted(ws["whipsaw_symbols"], key=lambda x: x["net_pnl"]):
                pnl_str = f"${sym['net_pnl']:+.2f}"
                lines.append(
                    f"| {sym['symbol']} | {sym['sequence_str']} | {sym['direction_flips']}次 | "
                    f"{pnl_str} | {sym['avg_hold_hours']:.1f}h | {sym['trade_count']} |"
                )
            lines.append("")

            # 最大亏损来回明细
            loss_rts = [rt for rt in ws.get("round_trips", []) if rt["pnl"] < 0]
            if loss_rts:
                loss_rts.sort(key=lambda x: x["pnl"])
                lines.extend([
                    "### 最大亏损来回 (Top 5)",
                    "",
                    "| 品种 | 买入/卖出 | 入场价 | 出场价 | 盈亏 | 持仓时间 |",
                    "|------|-----------|--------|--------|------|----------|",
                ])
                for rt in loss_rts[:5]:
                    lines.append(
                        f"| {rt['symbol']} | {rt['entry_action']}→{'SELL' if rt['entry_action']=='BUY' else 'BUY'} | "
                        f"${rt['entry_price']:.2f} | ${rt['exit_price']:.2f} | "
                        f"${rt['pnl']:+.2f} | {rt['hold_hours']:.1f}h |"
                    )
                lines.append("")

            total_ws_loss = ws["summary"].get("total_whipsaw_loss", 0)
            if total_ws_loss < 0:
                lines.append(f"**来回交易累计亏损: ${total_ws_loss:.2f}**")
                lines.append("")
        else:
            lines.append("本周未检测到来回翻转品种 (方向切换<3次)")
            lines.append("")

        # === 4. 周趋势分析 ===
        lines.extend([
            "---",
            "",
            "## 4. 周趋势分析",
            "",
        ])
        rhythm_scores = [d.get("rhythm_score", 50) for d in daily_summaries]
        if len(rhythm_scores) >= 2:
            trend = rhythm_scores[-1] - rhythm_scores[0]
            trend_icon = "📈" if trend > 0 else "📉" if trend < 0 else "➡️"
            lines.append(f"- 节奏评分趋势: {trend_icon} {trend:+.1f} (从{rhythm_scores[0]:.1f}到{rhythm_scores[-1]:.1f})")
        lines.append("")

        # === 5. 周改善建议 ===
        lines.extend([
            "---",
            "",
            "## 5. 📋 本周改善建议",
            "",
        ])
        if suggestions:
            for i, s in enumerate(suggestions, 1):
                priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(s.priority, "⚪")
                lines.extend([
                    f"### {i}. {priority_icon} [{s.priority}] {s.title}",
                    "",
                    f"**类别**: {s.category}",
                    f"**问题**: {s.detail}",
                    f"**建议**: {s.action}",
                    "",
                ])
        else:
            lines.append("本周无改善建议，交易状态良好！")
        lines.append("")

        lines.extend([
            "=" * 70,
            f"周报生成完成",
            "=" * 70,
        ])

        return "\n".join(lines)

    def generate_monthly_report(self, month: str,
                                 weekly_summaries: List[Dict],
                                 suggestions: List[ImprovementSuggestion],
                                 whipsaw_result: Dict = None) -> str:
        """生成每月分析报告"""
        lines = [
            "=" * 70,
            f"📊 每月交易分析报告 - {month}",
            "=" * 70,
            f"🕐 生成时间: {get_ny_now().strftime('%Y-%m-%d %H:%M:%S')} (纽约时间)",
            "",
        ]

        # === 1. 月统计汇总 ===
        total_trades = sum(w.get("total_trades", 0) for w in weekly_summaries)
        total_loss = sum(w.get("total_loss", 0) for w in weekly_summaries)
        avg_rhythm = sum(w.get("avg_rhythm_score", 50) for w in weekly_summaries) / len(weekly_summaries) if weekly_summaries else 0

        lines.extend([
            "## 1. 月统计汇总",
            "",
            f"- 总交易笔数: {total_trades}",
            f"- 累计亏损金额: ${total_loss:.2f}",
            f"- 平均节奏评分: {avg_rhythm:.1f}/100",
            f"- 统计周数: {len(weekly_summaries)}",
            "",
        ])

        # === 2. 每周明细 ===
        lines.extend([
            "---",
            "",
            "## 2. 每周明细",
            "",
            "| 周 | 交易数 | 平均节奏 | 累计亏损 | 高位追买 | 低位割肉 |",
            "|-----|--------|----------|----------|----------|----------|",
        ])
        for w in weekly_summaries:
            lines.append(
                f"| {w.get('week', 'N/A')} | {w.get('total_trades', 0)} | "
                f"{w.get('avg_rhythm_score', 0):.1f} | ${w.get('total_loss', 0):.2f} | "
                f"{w.get('bad_buys', 0)} | {w.get('bad_sells', 0)} |"
            )
        lines.append("")

        # === 3. 跨天来回买卖检测 ===
        lines.extend([
            "---",
            "",
            "## 3. 跨天来回买卖检测 (Whipsaw)",
            "",
        ])
        if whipsaw_result and whipsaw_result.get("whipsaw_symbols"):
            ws = whipsaw_result
            lines.extend([
                f"本月检测到 **{ws['summary']['whipsaw_count']}** 个品种存在来回翻转",
                "",
                "### 来回翻转品种",
                "",
                "| 品种 | 交易序列 | 翻转次数 | 净盈亏 | 平均持仓 | 交易笔数 |",
                "|------|----------|----------|--------|----------|----------|",
            ])
            for sym in sorted(ws["whipsaw_symbols"], key=lambda x: x["net_pnl"]):
                pnl_str = f"${sym['net_pnl']:+.2f}"
                lines.append(
                    f"| {sym['symbol']} | {sym['sequence_str']} | {sym['direction_flips']}次 | "
                    f"{pnl_str} | {sym['avg_hold_hours']:.1f}h | {sym['trade_count']} |"
                )
            lines.append("")

            # 最大亏损来回
            loss_rts = [rt for rt in ws.get("round_trips", []) if rt["pnl"] < 0]
            if loss_rts:
                loss_rts.sort(key=lambda x: x["pnl"])
                lines.extend([
                    "### 最大亏损来回 (Top 5)",
                    "",
                    "| 品种 | 买入/卖出 | 入场价 | 出场价 | 盈亏 | 持仓时间 |",
                    "|------|-----------|--------|--------|------|----------|",
                ])
                for rt in loss_rts[:5]:
                    lines.append(
                        f"| {rt['symbol']} | {rt['entry_action']}→{'SELL' if rt['entry_action']=='BUY' else 'BUY'} | "
                        f"${rt['entry_price']:.2f} | ${rt['exit_price']:.2f} | "
                        f"${rt['pnl']:+.2f} | {rt['hold_hours']:.1f}h |"
                    )
                lines.append("")

            total_ws_loss = ws["summary"].get("total_whipsaw_loss", 0)
            if total_ws_loss < 0:
                lines.append(f"**来回交易累计亏损: ${total_ws_loss:.2f}**")
                lines.append("")

            # 月度特有: 按品种统计来回频率排名
            all_analyses = ws.get("symbol_analyses", {})
            if all_analyses:
                ranked = sorted(all_analyses.values(), key=lambda x: x["direction_flips"], reverse=True)
                top_churners = [r for r in ranked[:5] if r["direction_flips"] >= 2]
                if top_churners:
                    lines.extend([
                        "### 方向切换频率 Top 5",
                        "",
                        "| 品种 | 翻转次数 | 净盈亏 | 交易笔数 |",
                        "|------|----------|--------|----------|",
                    ])
                    for r in top_churners:
                        lines.append(
                            f"| {r['symbol']} | {r['direction_flips']}次 | "
                            f"${r['net_pnl']:+.2f} | {r['trade_count']} |"
                        )
                    lines.append("")
        else:
            lines.append("本月未检测到来回翻转品种")
            lines.append("")

        # === 4. 月度趋势 ===
        lines.extend([
            "---",
            "",
            "## 4. 月度趋势分析",
            "",
        ])
        weekly_scores = [w.get("avg_rhythm_score", 50) for w in weekly_summaries]
        if len(weekly_scores) >= 2:
            trend = weekly_scores[-1] - weekly_scores[0]
            trend_icon = "📈" if trend > 0 else "📉" if trend < 0 else "➡️"
            lines.append(f"- 月度节奏趋势: {trend_icon} {trend:+.1f}")

            # 识别最佳和最差周
            best_week = max(weekly_summaries, key=lambda w: w.get("avg_rhythm_score", 0))
            worst_week = min(weekly_summaries, key=lambda w: w.get("avg_rhythm_score", 0))
            lines.extend([
                f"- 最佳周: {best_week.get('week', 'N/A')} (评分: {best_week.get('avg_rhythm_score', 0):.1f})",
                f"- 最差周: {worst_week.get('week', 'N/A')} (评分: {worst_week.get('avg_rhythm_score', 0):.1f})",
            ])
        lines.append("")

        # === 5. 月度改善建议 ===
        lines.extend([
            "---",
            "",
            "## 5. 📋 本月改善建议",
            "",
        ])
        if suggestions:
            for i, s in enumerate(suggestions, 1):
                priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(s.priority, "⚪")
                lines.extend([
                    f"### {i}. {priority_icon} [{s.priority}] {s.title}",
                    "",
                    f"**类别**: {s.category}",
                    f"**问题**: {s.detail}",
                    f"**建议**: {s.action}",
                    "",
                ])
        else:
            lines.append("本月无改善建议，交易状态良好！")
        lines.append("")

        lines.extend([
            "=" * 70,
            f"月报生成完成",
            "=" * 70,
        ])

        return "\n".join(lines)

    # ==========================================================
    # Per-Symbol HTML Reports (v3.2)
    # ==========================================================

    def _compute_symbol_rhythm(self, trades: list) -> Dict:
        """Compute rhythm metrics for a single symbol's trades."""
        buy_count = 0
        sell_count = 0
        total_buy_score = 0
        total_sell_score = 0

        for t in trades:
            score = RhythmAnalyzer.QUALITY_SCORES.get(t.quality, 50)
            if t.action == "BUY":
                buy_count += 1
                total_buy_score += score
            elif t.action == "SELL":
                sell_count += 1
                total_sell_score += score

        avg_buy = total_buy_score / buy_count if buy_count else 0
        avg_sell = total_sell_score / sell_count if sell_count else 0
        overall = (avg_buy + avg_sell) / 2 if (buy_count + sell_count) else 0

        return {
            "overall_score": round(overall, 1),
            "buy_score": round(avg_buy, 1),
            "sell_score": round(avg_sell, 1),
            "buy_count": buy_count,
            "sell_count": sell_count,
        }

    def _build_symbol_html(self, symbol: str, date_str: str, period_str: str,
                            trades: list, issues: list, rhythm: Dict,
                            calibration: Optional[Dict], rejected_signals: list,
                            chart_base64: Optional[str]) -> str:
        """Build per-symbol HTML report with clean modern design."""
        gen_time = get_ny_now().strftime('%Y-%m-%d %H:%M:%S')
        buy_trades = [t for t in trades if t.action == "BUY"]
        sell_trades = [t for t in trades if t.action == "SELL"]
        buy_count = rhythm.get("buy_count", 0)
        sell_count = rhythm.get("sell_count", 0)
        score = rhythm.get("overall_score", 0)

        def quality_badge(q):
            if q is None:
                return '<span class="badge neutral">neutral</span>'
            name = q.value if hasattr(q, 'value') else str(q)
            css = name.lower()
            return f'<span class="badge {css}">{name.lower()}</span>'

        def fmt_price(p):
            if p >= 1000:
                return f"${p:,.2f}"
            return f"${p:.4f}"

        def fmt_pos(pos):
            if pos is not None:
                return f"{pos:.2f}"
            return "---"

        def fmt_ts_short(ts):
            """Format timestamp as MM-DD HH:MM"""
            try:
                return ts[5:16].replace(" ", " ")
            except Exception:
                return ts[:16]

        # Compute summary statistics
        buy_positions = [t.pos_in_channel for t in buy_trades if t.pos_in_channel is not None]
        sell_positions = [t.pos_in_channel for t in sell_trades if t.pos_in_channel is not None]
        avg_buy_pos = sum(buy_positions) / len(buy_positions) if buy_positions else 0
        avg_sell_pos = sum(sell_positions) / len(sell_positions) if sell_positions else 0
        good_buys = sum(1 for t in buy_trades if t.quality in (TradeQuality.EXCELLENT, TradeQuality.GOOD))
        good_sells = sum(1 for t in sell_trades if t.quality in (TradeQuality.EXCELLENT, TradeQuality.GOOD))
        good_buy_rate = good_buys / buy_count * 100 if buy_count else 0
        good_sell_rate = good_sells / sell_count * 100 if sell_count else 0
        bad_buys = [t for t in buy_trades if t.quality in (TradeQuality.POOR, TradeQuality.TERRIBLE)]
        bad_sells = [t for t in sell_trades if t.quality in (TradeQuality.POOR, TradeQuality.TERRIBLE)]

        # ---- HTML Template ----
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{symbol} - Daily Trading Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,500;9..40,700&family=JetBrains+Mono:wght@400;600&display=swap');
:root {{
    --accent:#2563eb; --accent-light:#eff6ff;
    --green:#16a34a; --green-bg:#f0fdf4; --green-border:#bbf7d0;
    --red:#dc2626; --red-bg:#fef2f2; --red-border:#fecaca;
    --amber:#d97706; --amber-bg:#fffbeb;
    --text:#0f172a; --text-s:#64748b; --text-m:#94a3b8;
    --border:#e2e8f0; --border-l:#f1f5f9; --bg:#f8fafc; --white:#fff;
    --r:8px; --sh:0 1px 2px rgba(0,0,0,0.04);
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'DM Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:var(--bg); color:var(--text); line-height:1.6; -webkit-font-smoothing:antialiased; }}
.container {{ max-width:940px; margin:32px auto; padding:0 20px; }}
.header {{ background:var(--white); border:1px solid var(--border); border-radius:var(--r);
    padding:28px 32px; margin-bottom:20px; box-shadow:var(--sh); }}
.header-top {{ display:flex; align-items:baseline; justify-content:space-between; margin-bottom:6px; }}
.header h1 {{ font-size:22px; font-weight:700; letter-spacing:-0.3px; }}
.symbol-tag {{ background:var(--accent); color:#fff; font-family:'JetBrains Mono',monospace;
    font-size:11px; font-weight:600; padding:3px 10px; border-radius:4px; letter-spacing:0.5px; }}
.header .period {{ font-size:13px; color:var(--text-s); font-weight:500; }}
.header .gen-time {{ font-size:11px; color:var(--text-m); margin-top:2px; }}
.cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:20px; }}
.card {{ background:var(--white); border:1px solid var(--border); border-radius:var(--r);
    padding:20px 22px; box-shadow:var(--sh); position:relative; overflow:hidden; }}
.card::before {{ content:''; position:absolute; top:0;left:0;right:0; height:3px; }}
.card.buy::before {{ background:var(--green); }}
.card.sell::before {{ background:var(--red); }}
.card.score::before {{ background:var(--accent); }}
.card .label {{ font-size:12px; font-weight:500; color:var(--text-m);
    text-transform:uppercase; letter-spacing:0.6px; margin-bottom:6px; }}
.card .value {{ font-family:'JetBrains Mono',monospace; font-size:30px; font-weight:600; line-height:1.1; }}
.card.buy .value {{ color:var(--green); }}
.card.sell .value {{ color:var(--red); }}
.card.score .value {{ color:var(--accent); }}
.card .unit {{ font-size:12px; color:var(--text-m); margin-top:2px; }}
.section {{ background:var(--white); border:1px solid var(--border); border-radius:var(--r);
    margin-bottom:14px; box-shadow:var(--sh); overflow:hidden; }}
.section-header {{ padding:14px 24px; border-bottom:1px solid var(--border-l);
    display:flex; align-items:center; gap:8px; }}
.section-header h2 {{ font-size:14px; font-weight:600; letter-spacing:-0.1px; }}
.section-header .count {{ font-family:'JetBrains Mono',monospace; font-size:11px;
    background:var(--border-l); color:var(--text-s); padding:1px 8px; border-radius:10px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
table thead th {{ background:var(--bg); color:var(--text-s); padding:9px 20px; text-align:left;
    font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:0.5px;
    border-bottom:1px solid var(--border); }}
table thead th:first-child {{ padding-left:24px; }}
table tbody td {{ padding:10px 20px; border-bottom:1px solid var(--border-l); }}
table tbody td:first-child {{ padding-left:24px; }}
table tbody tr:last-child td {{ border-bottom:none; }}
table tbody tr:hover {{ background:#fafbff; }}
.mono {{ font-family:'JetBrains Mono',monospace; font-size:12px; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:4px;
    font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.4px; }}
.badge.excellent {{ background:var(--green-bg); color:var(--green); border:1px solid var(--green-border); }}
.badge.good {{ background:#eff6ff; color:#2563eb; border:1px solid #bfdbfe; }}
.badge.neutral {{ background:var(--amber-bg); color:var(--amber); border:1px solid #fde68a; }}
.badge.poor {{ background:#fff7ed; color:#c2410c; border:1px solid #fed7aa; }}
.badge.terrible {{ background:var(--red-bg); color:var(--red); border:1px solid var(--red-border); }}
.badge.warning {{ background:#fff7ed; color:#c2410c; border:1px solid #fed7aa; }}
.badge.critical {{ background:var(--red-bg); color:var(--red); border:1px solid var(--red-border); }}
.badge.active {{ background:var(--green-bg); color:var(--green); border:1px solid var(--green-border); }}
.chart-container {{ padding:16px 24px 20px; }}
.chart-container img {{ width:100%; height:auto; border-radius:6px; border:1px solid var(--border-l); }}
.chart-placeholder {{ padding:48px 20px; text-align:center; color:var(--text-m); font-size:13px; }}
.summary-container {{ padding:20px 24px 24px; }}
.summary-section {{ margin-bottom:20px; }}
.summary-section:last-child {{ margin-bottom:0; }}
.summary-section h3 {{ font-size:13px; font-weight:600; margin-bottom:8px;
    display:flex; align-items:center; gap:6px; }}
.dot {{ width:6px; height:6px; border-radius:50%; display:inline-block; }}
.dot.green {{ background:var(--green); }} .dot.red {{ background:var(--red); }}
.dot.blue {{ background:var(--accent); }} .dot.amber {{ background:var(--amber); }}
.insight-row {{ display:flex; align-items:flex-start; gap:8px; padding:4px 0;
    font-size:13px; line-height:1.5; color:var(--text-s); }}
.insight-row .icon {{ flex-shrink:0; width:16px; text-align:center; font-size:12px; line-height:20px; }}
.insight-row.pos .icon {{ color:var(--green); }}
.insight-row.neg .icon {{ color:var(--red); }}
.insight-row.neu .icon {{ color:var(--text-m); }}
.stats-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }}
.stat-item {{ text-align:center; }}
.stat-item .stat-value {{ font-family:'JetBrains Mono',monospace; font-size:18px; font-weight:600; }}
.stat-item .stat-label {{ font-size:11px; color:var(--text-m); margin-top:1px; }}
.score-meter {{ margin:8px 0 4px; height:6px; background:var(--border-l); border-radius:3px; overflow:hidden; }}
.score-meter .fill {{ height:100%; border-radius:3px; }}
.divider {{ height:1px; background:var(--border-l); margin:16px 0; }}
.cal-grid {{ padding:16px 24px 20px; }}
.cal-row {{ display:grid; grid-template-columns:110px 1fr 60px 60px; align-items:center;
    gap:14px; padding:12px 0; border-bottom:1px solid var(--border-l); }}
.cal-row:last-child {{ border-bottom:none; }}
.cal-row.is-active {{ background:var(--green-bg); margin:0 -24px; padding:12px 24px; border-radius:6px; }}
.cal-name {{ font-size:13px; font-weight:600; }}
.cal-desc {{ font-size:11px; color:var(--text-m); margin-top:1px; }}
.cal-bar-wrap {{ display:flex; align-items:center; gap:10px; }}
.cal-bar {{ flex:1; height:8px; background:var(--border-l); border-radius:4px; overflow:hidden; }}
.cal-bar .cal-fill {{ height:100%; border-radius:4px; }}
.cal-pct {{ font-family:'JetBrains Mono',monospace; font-size:13px; font-weight:600; min-width:50px; text-align:right; }}
.cal-delta {{ font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--text-m); text-align:right; }}
.cal-note {{ padding:12px 24px 16px; font-size:12px; color:var(--text-s); line-height:1.6;
    border-top:1px solid var(--border-l); }}
.cal-note strong {{ color:var(--text); }}
.no-data {{ text-align:center; color:var(--text-m); padding:28px 20px; font-size:13px; }}
.footer {{ text-align:center; padding:20px; color:var(--text-m); font-size:11px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="header-top">
            <h1>Daily Trading Report</h1>
            <span class="symbol-tag">{symbol}</span>
        </div>
        <div class="period">{period_str}</div>
        <div class="gen-time">Generated {gen_time} New York Time</div>
    </div>
    <div class="cards">
        <div class="card buy">
            <div class="label">Buy Count</div>
            <div class="value">{buy_count}</div>
            <div class="unit">trades</div>
        </div>
        <div class="card sell">
            <div class="label">Sell Count</div>
            <div class="value">{sell_count}</div>
            <div class="unit">trades</div>
        </div>
        <div class="card score">
            <div class="label">Rhythm Score</div>
            <div class="value">{score:.0f}</div>
            <div class="unit">/ 100</div>
        </div>
    </div>
'''

        # ---- Chart Section ----
        html += '    <div class="section"><div class="section-header"><h2>K-Line Chart</h2></div>\n'
        html += '    <div class="chart-container">\n'
        if chart_base64:
            html += f'        <img src="data:image/png;base64,{chart_base64}" alt="K-line chart">\n'
        else:
            html += '        <div class="chart-placeholder">Chart unavailable</div>\n'
        html += '    </div></div>\n'

        # ---- Helper: render trade table ----
        def _trade_table(label, trade_list):
            out = f'    <div class="section"><div class="section-header"><h2>Trade Details &mdash; {label}</h2>'
            out += f'<span class="count">{len(trade_list)}</span></div>\n'
            if trade_list:
                out += '    <div class="section-body"><table><thead><tr>'
                out += '<th>Time</th><th>Price</th><th>Position</th><th>Quality</th><th>Source</th>'
                out += '</tr></thead><tbody>\n'
                for t in trade_list:
                    out += f'    <tr><td class="mono">{fmt_ts_short(t.ts)}</td>'
                    out += f'<td class="mono">{fmt_price(t.price)}</td>'
                    out += f'<td class="mono">{fmt_pos(t.pos_in_channel)}</td>'
                    out += f'<td>{quality_badge(t.quality)}</td>'
                    out += f'<td>{t.source or "L2"}</td></tr>\n'
                out += '    </tbody></table></div>\n'
            else:
                out += f'    <div class="no-data">No {label} trades</div>\n'
            out += '    </div>\n'
            return out

        html += _trade_table("BUY", buy_trades)
        html += _trade_table("SELL", sell_trades)

        # ---- Rejected Signals ----
        html += '    <div class="section"><div class="section-header">'
        html += f'<h2>Rejected Signals</h2><span class="count">{len(rejected_signals)}</span></div>\n'
        if rejected_signals:
            html += '    <div class="section-body"><table><thead><tr>'
            html += '<th>Time</th><th>Original</th><th>Result</th><th>Reason</th>'
            html += '</tr></thead><tbody>\n'
            for r in rejected_signals:
                html += f'    <tr><td class="mono">{r.get("time", "")[:11]}</td>'
                html += f'<td>{r.get("original_signal", "")}</td>'
                html += '<td><span class="badge neutral">HOLD</span></td>'
                html += f'<td>{r.get("reason", "")}</td></tr>\n'
            html += '    </tbody></table></div>\n'
        else:
            html += '    <div class="no-data">No rejected signals</div>\n'
        html += '    </div>\n'

        # ---- 4-Way Calibration (v3.640) ----
        if calibration and isinstance(calibration, dict):
            def _cal_acc(s, prefix):
                t = s.get(f"{prefix}_total", 0)
                c = s.get(f"{prefix}_correct", 0)
                return c / t if t >= 5 else None

            rule_acc = _cal_acc(calibration, "rule")
            vision_acc = _cal_acc(calibration, "vision")
            x4_dow_acc = _cal_acc(calibration, "x4_dow")
            x4_chan_acc = _cal_acc(calibration, "x4_chan")

            methods_data = [
                ("缠论Rule", rule_acc, "Chan Theory K-line merge + 3-segment judgment"),
                ("Vision", vision_acc, "GPT-4o simple trend chart analysis"),
                ("x4道氏", x4_dow_acc, "Dow Theory swing points on x4 aggregated bars"),
                ("x4缠論", x4_chan_acc, "Chan Theory on last 12 current-period bars"),
            ]
            # Sort by accuracy descending (None at bottom)
            methods_sorted = sorted(methods_data, key=lambda x: x[1] if x[1] is not None else -1, reverse=True)
            best_val = methods_sorted[0][1] if methods_sorted[0][1] is not None else 0
            best_name = methods_sorted[0][0]

            html += f'    <div class="section"><div class="section-header"><h2>4-Way Calibration Accuracy</h2>'
            html += f'<span class="count">Best: {best_name} {best_val:.1%}</span></div>\n'
            html += '    <div class="cal-grid">\n'

            for name, acc, desc in methods_sorted:
                if acc is None:
                    pct_str = "---"
                    bar_w = 0
                    delta_str = "N/A"
                    bar_color = "var(--text-m)"
                else:
                    pct_str = f"{acc:.1%}"
                    bar_w = acc * 100
                    delta_val = (acc - best_val) * 100
                    if abs(delta_val) < 0.05:
                        delta_str = "best"
                    else:
                        delta_str = f"{delta_val:+.1f}%"
                    if abs(delta_val) < 0.05:
                        bar_color = "var(--green)"
                    elif abs(delta_val) < 5:
                        bar_color = "var(--accent)"
                    elif abs(delta_val) < 10:
                        bar_color = "var(--amber)"
                    else:
                        bar_color = "var(--red)"

                is_active = (name == best_name and acc is not None)
                row_cls = "cal-row is-active" if is_active else "cal-row"
                active_badge = ' &nbsp;<span class="badge active">Active</span>' if is_active else ''
                pct_color = f' style="color:var(--green);"' if is_active else ''
                delta_color = f' style="color:var(--green);"' if delta_str == "best" else ''

                html += f'    <div class="{row_cls}">\n'
                html += f'        <div><div class="cal-name">{name}{active_badge}</div><div class="cal-desc">{desc}</div></div>\n'
                html += f'        <div class="cal-bar-wrap"><div class="cal-bar"><div class="cal-fill" style="width:{bar_w:.0f}%;background:{bar_color};"></div></div></div>\n'
                html += f'        <div class="cal-pct"{pct_color}>{pct_str}</div>\n'
                html += f'        <div class="cal-delta"{delta_color}>{delta_str}</div>\n'
                html += f'    </div>\n'

            html += '    </div>\n'

            # Explanatory note
            note_parts = ['The system automatically selects the method with the highest historical accuracy for this symbol.']
            if best_val > 0:
                note_parts.append(f'{best_name} ({best_val:.1%}) is the current winner.')
                if len(methods_sorted) > 1 and methods_sorted[1][1] is not None:
                    runner = methods_sorted[1]
                    gap = (best_val - runner[1]) * 100
                    note_parts.append(f'It outperforms {runner[0]} ({runner[1]:.1%}) by +{gap:.1f}pp.')
            html += f'    <div class="cal-note"><strong>Selection Logic:</strong> {" ".join(note_parts)}</div>\n'
            html += '    </div>\n'
        else:
            html += '    <div class="section"><div class="section-header"><h2>4-Way Calibration Accuracy</h2></div>\n'
            html += '    <div class="no-data">No calibration data</div></div>\n'

        # ---- Issues ----
        html += f'    <div class="section"><div class="section-header"><h2>Issue Detection</h2>'
        html += f'<span class="count">{len(issues)}</span></div>\n'
        if issues:
            html += '    <div class="section-body"><table><thead><tr>'
            html += '<th>Level</th><th>Category</th><th>Description</th><th>Suggestion</th>'
            html += '</tr></thead><tbody>\n'
            for iss in issues[:15]:
                level_css = "critical" if iss.level == "CRITICAL" else "warning" if iss.level == "WARNING" else "neutral"
                html += f'    <tr><td><span class="badge {level_css}">{iss.level}</span></td>'
                html += f'<td>{iss.category}</td>'
                html += f'<td>{iss.description}</td>'
                html += f'<td>{iss.suggestion}</td></tr>\n'
            html += '    </tbody></table></div>\n'
        else:
            html += '    <div class="no-data">No issues detected</div>\n'
        html += '    </div>\n'

        # ---- 24-Hour Analysis Summary ----
        html += '    <div class="section"><div class="section-header"><h2>24-Hour Analysis Summary</h2></div>\n'
        html += '    <div class="summary-container">\n'

        if not trades:
            html += '        <div class="no-data">No trades recorded in this period.</div>\n'
        else:
            # Key stats grid
            html += '        <div class="stats-grid">\n'
            html += f'            <div class="stat-item"><div class="stat-value" style="color:var(--green)">{good_buy_rate:.0f}%</div><div class="stat-label">Good BUY Rate</div></div>\n'
            html += f'            <div class="stat-item"><div class="stat-value" style="color:var(--red)">{good_sell_rate:.0f}%</div><div class="stat-label">Good SELL Rate</div></div>\n'
            html += f'            <div class="stat-item"><div class="stat-value">{avg_buy_pos:.2f}</div><div class="stat-label">Avg BUY Pos</div></div>\n'
            html += f'            <div class="stat-item"><div class="stat-value">{avg_sell_pos:.2f}</div><div class="stat-label">Avg SELL Pos</div></div>\n'
            html += '        </div>\n'

            # Score bar
            score_color = "var(--green)" if score >= 70 else "var(--amber)" if score >= 40 else "var(--red)"
            html += '        <div style="margin-bottom:16px;">\n'
            html += '            <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;">\n'
            html += '                <span style="font-size:12px;font-weight:500;color:var(--text-s)">Overall Rhythm</span>\n'
            html += f'                <span class="mono" style="font-size:13px;font-weight:600;color:{score_color}">{score:.0f} / 100</span>\n'
            html += '            </div>\n'
            html += f'            <div class="score-meter"><div class="fill" style="width:{min(score, 100):.0f}%;background:{score_color};"></div></div>\n'
            html += '        </div>\n'
            html += '        <div class="divider"></div>\n'

            # BUY Analysis
            if buy_trades:
                html += f'        <div class="summary-section"><h3><span class="dot green"></span> BUY Decisions ({buy_count} trades, avg pos {avg_buy_pos:.2f})</h3>\n'
                for t in buy_trades:
                    pos = t.pos_in_channel
                    q = t.quality
                    ts_short = fmt_ts_short(t.ts)
                    if q in (TradeQuality.EXCELLENT, TradeQuality.GOOD):
                        pos_desc = "near channel bottom" if pos is not None and pos < 0.25 else "in lower channel half"
                        html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                        html += f'<strong>{q.value}</strong> entry at {ts_short} &mdash; pos={fmt_pos(pos)}, '
                        html += f'price={fmt_price(t.price)}. {pos_desc.capitalize()}, '
                        html += f'low-risk trend-aligned entry via {t.source or "L2"}.</span></div>\n'
                    elif q in (TradeQuality.POOR, TradeQuality.TERRIBLE):
                        risk = "upper channel risk zone" if pos is not None and pos > 0.7 else "elevated position"
                        html += f'        <div class="insight-row neg"><span class="icon">&minus;</span><span>'
                        html += f'<strong>{q.value}</strong> entry at {ts_short} &mdash; pos={fmt_pos(pos)}, '
                        html += f'price={fmt_price(t.price)}. {risk.capitalize()}, '
                        html += f'high retracement risk. '
                        if t.source and t.source != "L2":
                            html += f'{t.source} plugin triggered this BUY &mdash; consider adding pos&gt;0.65 gate for {t.source} signals.'
                        else:
                            html += 'Consider waiting for pullback before adding position at this level.'
                        html += '</span></div>\n'
                    else:
                        html += f'        <div class="insight-row neu"><span class="icon">&bull;</span><span>'
                        html += f'<strong>NEUTRAL</strong> entry at {ts_short} &mdash; pos={fmt_pos(pos)}, '
                        html += f'price={fmt_price(t.price)}. Mid-channel entry, '
                        html += f'moderate risk/reward profile.</span></div>\n'
                html += '        </div><div class="divider"></div>\n'

            # SELL Analysis
            if sell_trades:
                html += f'        <div class="summary-section"><h3><span class="dot red"></span> SELL Decisions ({sell_count} trades, avg pos {avg_sell_pos:.2f})</h3>\n'
                for t in sell_trades:
                    pos = t.pos_in_channel
                    q = t.quality
                    ts_short = fmt_ts_short(t.ts)
                    if q in (TradeQuality.EXCELLENT, TradeQuality.GOOD):
                        pos_desc = "near channel top" if pos is not None and pos > 0.75 else "in upper channel half"
                        html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                        html += f'<strong>{q.value}</strong> exit at {ts_short} &mdash; pos={fmt_pos(pos)}, '
                        html += f'price={fmt_price(t.price)}. {pos_desc.capitalize()}, '
                        html += f'well-timed profit-taking.</span></div>\n'
                    elif q in (TradeQuality.POOR, TradeQuality.TERRIBLE):
                        html += f'        <div class="insight-row neg"><span class="icon">&minus;</span><span>'
                        html += f'<strong>{q.value}</strong> exit at {ts_short} &mdash; pos={fmt_pos(pos)}, '
                        html += f'price={fmt_price(t.price)}. Low position exit, may be premature. '
                        if t.source and t.source != "L2":
                            html += f'{t.source}-triggered SELL &mdash; consider requiring pos&gt;0.65 for {t.source} SELL signals.'
                        else:
                            html += 'Consider holding for better exit level when no bearish divergence is confirmed.'
                        html += '</span></div>\n'
                    else:
                        html += f'        <div class="insight-row neu"><span class="icon">&bull;</span><span>'
                        html += f'<strong>NEUTRAL</strong> exit at {ts_short} &mdash; pos={fmt_pos(pos)}, '
                        html += f'price={fmt_price(t.price)}. Mid-channel exit, '
                        if t.source and t.source != "L2":
                            html += f'{t.source}-triggered. '
                        html += f'acceptable but not optimal timing.</span></div>\n'
                html += '        </div><div class="divider"></div>\n'

            # Rejected signals analysis
            l1_vetos = []  # v3.641fix: 预定义，避免rejected_signals为空时UnboundLocalError
            if rejected_signals:
                html += f'        <div class="summary-section"><h3><span class="dot amber"></span> Rejected Signals ({len(rejected_signals)} blocked)</h3>\n'
                # Categorize rejections
                sr_vetos = [r for r in rejected_signals if "SR_VETO" in r.get("reason", "")]
                l1_vetos = [r for r in rejected_signals if "L1" in r.get("reason", "") and "否决" in r.get("reason", "")]
                pos_gates = [r for r in rejected_signals if "满仓" in r.get("reason", "") or "空仓" in r.get("reason", "")]
                conflicts = [r for r in rejected_signals if "冲突" in r.get("reason", "")]
                l1_refs = [r for r in rejected_signals if "v3.650" in r.get("reason", "")]
                l2_strongs = [r for r in rejected_signals if "STRONG" in r.get("reason", "")]
                pos_blocks = [r for r in rejected_signals if "v3.411" in r.get("reason", "")]

                if l1_refs:
                    html += f'        <div class="insight-row neu"><span class="icon">&bull;</span><span>'
                    html += f'<strong>L1 Reference (v3.650)</strong> {len(l1_refs)} signal(s) &mdash; '
                    html += 'L1 BUY/SELL as reference only, no actual trades placed.</span></div>\n'
                if l2_strongs:
                    html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                    html += f'<strong>L2 STRONG Block</strong> blocked {len(l2_strongs)} opposite signal(s) &mdash; '
                    html += 'STRONG_BUY/SELL blocked reverse direction in scan engine.</span></div>\n'
                if pos_blocks:
                    html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                    html += f'<strong>Position Block (v3.411)</strong> blocked {len(pos_blocks)} signal(s) &mdash; '
                    html += 'full/empty position final guard prevented invalid trades.</span></div>\n'
                if sr_vetos:
                    html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                    html += f'<strong>SR Veto</strong> blocked {len(sr_vetos)} signal(s) near S/R levels &mdash; '
                    html += 'prevented entries/exits at unfavorable price zones.</span></div>\n'
                if pos_gates:
                    html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                    html += f'<strong>Position Gate</strong> blocked {len(pos_gates)} signal(s) &mdash; '
                    html += 'correct risk management, avoiding over-exposure.</span></div>\n'
                if conflicts:
                    html += f'        <div class="insight-row neu"><span class="icon">&bull;</span><span>'
                    html += f'<strong>Direction Conflict</strong> blocked {len(conflicts)} signal(s) &mdash; '
                    html += 'L1/L2 disagreed on trend direction. Conservative but protective.</span></div>\n'
                rhythm_blocks = [r for r in rejected_signals if "拦截" in r.get("reason", "") and "v21.6" in r.get("reason", "")]
                donchian_blocks = [r for r in rejected_signals if "唐纳奇" in r.get("reason", "")]
                if rhythm_blocks:
                    html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                    html += f'<strong>Rhythm Filter (v21.6)</strong> blocked {len(rhythm_blocks)} signal(s) &mdash; '
                    low_blocks = [r for r in rhythm_blocks if "低位" in r.get("reason", "")]
                    high_blocks = [r for r in rhythm_blocks if "追高" in r.get("reason", "")]
                    parts = []
                    if low_blocks:
                        parts.append(f'{len(low_blocks)} low-position SELL(s)')
                    if high_blocks:
                        parts.append(f'{len(high_blocks)} high-position BUY(s)')
                    html += f'{", ".join(parts)}. Prevented poor-rhythm trades (pos&lt;40% SELL or pos&gt;75% BUY).</span></div>\n'
                if donchian_blocks:
                    html += f'        <div class="insight-row pos"><span class="icon">+</span><span>'
                    html += f'<strong>Donchian Support (v21.6)</strong> blocked {len(donchian_blocks)} trailing stop SELL(s) &mdash; '
                    html += 'price near channel support (pos&lt;40%), prevented premature stop-loss exit.</span></div>\n'
                if l1_vetos:
                    html += f'        <div class="insight-row neg"><span class="icon">&minus;</span><span>'
                    html += f'<strong>L1 Veto</strong> blocked {len(l1_vetos)} L2 signal(s) &mdash; '
                    html += 'L1=HOLD overruled L2 trade signals. Review whether L1 sensitivity is appropriate for detecting short-term distribution/accumulation.</span></div>\n'
                html += '        </div><div class="divider"></div>\n'

            # Key Observations
            html += '        <div class="summary-section"><h3><span class="dot blue"></span> Key Observations</h3>\n'
            obs_num = 1

            # 1. Entry timing quality
            if buy_count > 0:
                lower_half_buys = sum(1 for t in buy_trades if t.pos_in_channel is not None and t.pos_in_channel < 0.5)
                html += f'        <div class="insight-row neu"><span class="icon">{obs_num}.</span><span>'
                html += f'<strong>Entry Timing</strong> &mdash; '
                html += f'{lower_half_buys} of {buy_count} BUY entries ({lower_half_buys*100//buy_count}%) were in the lower channel half (pos&lt;0.5). '
                html += f'Average BUY position: {avg_buy_pos:.2f}. '
                if avg_buy_pos < 0.35:
                    html += 'Excellent entry discipline &mdash; consistently buying near support levels.'
                elif avg_buy_pos < 0.5:
                    html += 'Good entry timing overall, with room to improve by waiting for deeper pullbacks.'
                else:
                    html += 'Entry positions are too high on average. Consider stricter position channel gating to avoid chasing.'
                if bad_buys:
                    worst = max(bad_buys, key=lambda t: t.pos_in_channel or 0)
                    html += f' Worst entry: {fmt_ts_short(worst.ts)} at pos={fmt_pos(worst.pos_in_channel)}'
                    if worst.source and worst.source != "L2":
                        html += f' ({worst.source} plugin).'
                    else:
                        html += '.'
                html += '</span></div>\n'
                obs_num += 1

            # 2. Exit quality
            if sell_count > 0:
                upper_half_sells = sum(1 for t in sell_trades if t.pos_in_channel is not None and t.pos_in_channel > 0.5)
                html += f'        <div class="insight-row neu"><span class="icon">{obs_num}.</span><span>'
                html += f'<strong>Exit Quality</strong> &mdash; '
                html += f'{upper_half_sells} of {sell_count} SELL exits ({upper_half_sells*100//sell_count}%) were in the upper channel half (pos&gt;0.5). '
                html += f'Average SELL position: {avg_sell_pos:.2f}. '
                if avg_sell_pos > 0.7:
                    html += 'Strong exit timing &mdash; selling near resistance levels for maximum profit capture.'
                elif avg_sell_pos > 0.5:
                    html += 'Acceptable exit timing. Consider holding longer for better exits when no bearish divergence is present.'
                else:
                    html += 'Exit positions are too low &mdash; selling too early leaves profit on the table. Review SELL trigger conditions.'
                if bad_sells:
                    worst = min(bad_sells, key=lambda t: t.pos_in_channel if t.pos_in_channel is not None else 1)
                    html += f' Weakest exit: {fmt_ts_short(worst.ts)} at pos={fmt_pos(worst.pos_in_channel)}'
                    if worst.source and worst.source != "L2":
                        html += f' ({worst.source} plugin).'
                    else:
                        html += '.'
                html += '</span></div>\n'
                obs_num += 1

            # 3. Risk control assessment
            if rejected_signals:
                html += f'        <div class="insight-row neu"><span class="icon">{obs_num}.</span><span>'
                html += f'<strong>Risk Control</strong> &mdash; '
                html += f'{len(rejected_signals)} signals were rejected during this period. '
                if sr_vetos:
                    html += f'SR veto blocked {len(sr_vetos)} signal(s) near key levels. '
                total_actions = buy_count + sell_count + len(rejected_signals)
                reject_rate = len(rejected_signals) / total_actions * 100 if total_actions else 0
                html += f'Rejection rate: {reject_rate:.0f}% ({len(rejected_signals)}/{total_actions} total signals). '
                if reject_rate > 60:
                    html += 'High rejection rate suggests the system is very conservative &mdash; review if L1/SR conditions are too strict.'
                elif reject_rate > 30:
                    html += 'Moderate rejection rate indicates balanced risk management.'
                else:
                    html += 'Low rejection rate &mdash; most signals pass through to execution.'
                html += '</span></div>\n'
                obs_num += 1

            # 4. Actionable improvements
            improvements = []
            if bad_buys:
                sources = set(t.source for t in bad_buys if t.source and t.source != "L2")
                if sources:
                    improvements.append(f'Add pos&gt;0.65 gate for {"/".join(sources)} BUY signals to prevent high-position entries')
                else:
                    improvements.append('Tighten BUY position threshold &mdash; avoid entries above pos=0.65 in current volatility')
            if bad_sells:
                sources = set(t.source for t in bad_sells if t.source and t.source != "L2")
                if sources:
                    improvements.append(f'Require pos&gt;0.65 for {"/".join(sources)} SELL signals to avoid premature mid-channel exits')
                else:
                    improvements.append('Raise minimum SELL position &mdash; avoid exits below pos=0.4 unless bearish divergence confirmed')
            if l1_vetos:
                improvements.append('Review L1 HOLD sensitivity &mdash; possible missed opportunities when L1 is slow to detect distribution/accumulation')
            if not improvements and score >= 70:
                improvements.append('No critical improvements needed. Maintain current strategy parameters.')

            if improvements:
                html += f'        <div class="insight-row neu"><span class="icon">{obs_num}.</span><span>'
                html += '<strong>Actionable Improvements</strong> &mdash; '
                html += ' '.join(f'({chr(97+i)}) {imp}.' for i, imp in enumerate(improvements))
                html += '</span></div>\n'

            html += '        </div>\n'

        html += '    </div></div>\n'

        # Footer
        html += '''    <div class="footer">AI Trading System &middot; Log Analyzer v3.2 &middot; Per-Symbol Daily Report</div>
</div>
</body>
</html>'''

        return html

    def generate_daily_html_reports(self, date_str: str, detector: IssueDetector,
                                     logic_result: Dict, redundant_result: Dict,
                                     rhythm_result: Dict,
                                     suggestions: List[ImprovementSuggestion],
                                     rejected_signals: Dict[str, List[Dict]]) -> List[str]:
        """Generate per-symbol HTML reports, returns list of file paths."""
        from datetime import datetime, timedelta

        # Create daily directory
        html_dir = f"{CONFIG['output_dir']}/{date_str}"
        os.makedirs(html_dir, exist_ok=True)

        # Compute period string
        try:
            report_date = datetime.strptime(date_str, "%Y-%m-%d")
            prev_date = report_date - timedelta(days=1)
            period_str = f"{prev_date.strftime('%Y%m%d')}-{report_date.strftime('%Y%m%d')} 8AM to 8AM 24hrs"
        except Exception:
            period_str = f"{date_str} 24hrs"

        # Read calibration data once
        dual_track = safe_json_read(CONFIG["data_files"]["human_dual_track"]) or {}

        # Get all enriched trades from rhythm result
        all_trades = rhythm_result.get("trades", [])

        # Get all issues
        all_issues = detector.issues

        # Get loss trades and same bar trades from redundant result
        loss_trades = redundant_result.get("loss_trades", [])
        same_bar_trades = redundant_result.get("same_bar_trades", [])

        html_files = []

        for symbol in ALL_SYMBOLS:
            # Filter by symbol
            sym_trades = [t for t in all_trades if t.symbol == symbol]
            sym_issues = [i for i in all_issues if i.symbol == symbol]
            sym_rejected = rejected_signals.get(symbol, [])
            sym_calibration = dual_track.get("stats", {}).get(symbol)

            # Per-symbol rhythm
            sym_rhythm = self._compute_symbol_rhythm(sym_trades)

            # Generate chart
            try:
                from timeframe_params import read_symbol_timeframe
                tf = read_symbol_timeframe(symbol)
            except Exception:
                tf = 240
            chart_base64 = generate_candlestick_chart(symbol, date_str, sym_trades, tf)

            # Build HTML
            html_content = self._build_symbol_html(
                symbol=symbol,
                date_str=date_str,
                period_str=period_str,
                trades=sym_trades,
                issues=sym_issues,
                rhythm=sym_rhythm,
                calibration=sym_calibration,
                rejected_signals=sym_rejected,
                chart_base64=chart_base64,
            )

            # Write file
            filepath = f"{html_dir}/{symbol}.html"
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                html_files.append(filepath)
            except Exception as e:
                logger.error(f"[HTML] Failed to write {filepath}: {e}")

        return html_files


# ============================================================
# 6. EnhancedLogAnalyzer - 增强版日志分析器主类
# ============================================================

class EnhancedLogAnalyzer:
    """增强版日志分析器"""

    def __init__(self):
        self.logic_checker = LogicChecker()
        self.data_quality_checker = DataQualityChecker()
        self.plugin_tracker = PluginSignalTracker()
        self.redundant_checker = RedundantTradeChecker()
        self.whipsaw_detector = WhipsawDetector()
        self.rhythm_analyzer = RhythmAnalyzer()
        self.signal_validator = SignalValidator()
        self.improvement_advisor = ImprovementAdvisor()
        self.testing_verifier = TestingVerifier()
        self.report_generator = ReportGenerator()

        self.quality_scores = self._load_quality_scores()

    def _load_quality_scores(self) -> Dict:
        """加载质量评分历史"""
        return safe_json_read(CONFIG["quality_scores_file"]) or {"daily": {}, "weekly": {}, "monthly": {}}

    def _save_quality_scores(self):
        """保存质量评分历史"""
        safe_json_write(CONFIG["quality_scores_file"], self.quality_scores)

    def _read_log_lines(self, filepath: str, date_str: str = None) -> List[str]:
        """读取日志文件 (含rotate .1回退)"""
        all_lines = []
        # 读主文件 + .1 rotate文件(RotatingFileHandler rotate后当天数据可能在.1中)
        for fpath in [filepath, filepath + ".1"]:
            if not os.path.exists(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    all_lines.extend(f.readlines())
            except Exception as e:
                logger.error(f"读取日志失败 {fpath}: {e}")

        if not all_lines:
            logger.warning(f"日志文件不存在: {filepath}")
            return []

        if date_str:
            all_lines = [l for l in all_lines if date_str in l]

        return all_lines

    def analyze_daily(self, date_str: str = None) -> Dict:
        """执行每日分析"""
        if not date_str:
            date_str = get_today_date_ny()

        logger.info(f"开始每日分析: {date_str}")

        detector = IssueDetector()

        # 读取日志
        server_lines = self._read_log_lines(CONFIG["log_files"]["server"], date_str)
        scan_lines = self._read_log_lines(CONFIG["log_files"]["scan_engine"], date_str)
        all_lines = server_lines + scan_lines
        # 补充5个遗漏日志 (deepseek仲裁/MACD背离/RobHoffman/L1诊断/估值)
        for _extra_key in ("deepseek_arbiter", "macd_divergence", "rob_hoffman", "l1_diagnosis", "value_analysis"):
            _extra_path = CONFIG["log_files"].get(_extra_key)
            if _extra_path:
                _extra_lines = self._read_log_lines(_extra_path, date_str)
                all_lines.extend(_extra_lines)
        logger.info(f"读取到 {len(all_lines)} 行日志")

        # 1. 逻辑问题检测
        logic_result = self.logic_checker.check(all_lines, detector)

        # 1a. 数据质量检测 (v3.4)
        dq_result = self.data_quality_checker.check(all_lines, detector)
        logger.info(
            f"数据质量: 总问题{dq_result['total_issues']} "
            f"(数据{dq_result['kline_insufficient']+dq_result['no_history_data']+dq_result['invalid_candle']} "
            f"API{dq_result['yfinance_timeout']+dq_result['yfinance_error']+dq_result['coinbase_error']} "
            f"指标{dq_result['indicator_failures']} "
            f"Vision{dq_result['vision_file_missing']+dq_result['vision_stale']})"
        )
        # 1a-knn. KEY-007 KNN统计
        _knn_vf = dq_result.get("vision_filter_block", 0)
        _knn_pk = dq_result.get("plugin_knn_query", 0)
        _knn_sup = dq_result.get("plugin_knn_suppress", 0)
        _knn_err = dq_result.get("plugin_knn_error", 0) + dq_result.get("vision_filter_error", 0)
        if _knn_vf + _knn_pk + _knn_sup + _knn_err > 0:
            logger.info(
                f"KEY-007 KNN: VisionFilter拦截={_knn_vf} PluginKNN查询={_knn_pk} "
                f"抑制={_knn_sup} 异常={_knn_err}"
            )

        # 1b. 外挂信号生命周期追踪
        plugin_result = self.plugin_tracker.parse(all_lines)
        signal_decisions = self.plugin_tracker.parse_signal_decisions(
            "logs/signal_decisions.jsonl", date_str
        )
        profit_state = self.plugin_tracker.load_profit_state(
            "plugin_profit_state.json", date_str
        )
        plugin_result["signal_decisions"] = signal_decisions
        plugin_result["profit_state"] = profit_state
        logger.info(f"外挂追踪: 触发{plugin_result['total_triggered']} 执行{plugin_result['total_executed']} 阻止{plugin_result['total_blocked']}")

        # 2. 加载交易记录并检测多余交易
        trades = self.redundant_checker.load_trades(CONFIG["data_files"]["trade_history"], date_str)
        redundant_result = self.redundant_checker.check(detector, trades)

        # 3. 节奏分析
        self.rhythm_analyzer.load_state(CONFIG["data_files"]["state"])
        rhythm_result = self.rhythm_analyzer.analyze_rhythm(trades, detector, all_lines)

        # 4. 外挂盈亏归因 (P0-3)
        plugin_pnl = PluginSignalTracker.compute_plugin_pnl(trades)
        logger.info(f"外挂盈亏: {len(plugin_pnl.get('entries', {}))}个入场来源, {len(plugin_pnl.get('pairs', []))}笔配对")

        # 6. 被拒信号解析 (提前到此处供回测使用)
        rejected_signals = self.logic_checker.parse_rejected_signals(all_lines, date_str)

        # 7. 信号事后验证 (P1-1) + 被拒信号回测 (P1-2)
        trend_validation = self.signal_validator.validate_trend_changes(all_lines, date_str, detector)
        rejected_backtest = self.signal_validator.backtest_rejected_signals(rejected_signals, date_str, detector)
        logger.info(
            f"信号验证: {trend_validation.get('validated', 0)}个趋势切换, "
            f"准确率={trend_validation.get('accuracy', 'N/A')}% | "
            f"被拒回测: {rejected_backtest.get('total_backtested', 0)}个信号, "
            f"错过盈利率={rejected_backtest.get('profit_rate', 'N/A')}%"
        )

        # 7b. 本周累计来回买卖检测 (从本周一8am NY开始)
        cumulative_whipsaw = {}
        try:
            today_dt = datetime.strptime(date_str, "%Y-%m-%d")
            # 本周一 (Monday=0)
            days_since_monday = today_dt.weekday()
            week_start_dt = today_dt - timedelta(days=days_since_monday)
            week_start_str = week_start_dt.strftime("%Y-%m-%d")
            cumulative_trades = self.whipsaw_detector.load_trades_range(
                CONFIG["data_files"]["trade_history"], week_start_str, date_str)
            if cumulative_trades:
                cumulative_whipsaw = self.whipsaw_detector.detect(cumulative_trades)
                cum_days = days_since_monday + 1
                logger.info(f"本周累计Whipsaw ({week_start_str}~{date_str}, {cum_days}天): "
                             f"{len(cumulative_trades)}笔交易, "
                             f"{cumulative_whipsaw.get('summary', {}).get('whipsaw_count', 0)}个来回品种")
        except Exception as e:
            logger.warning(f"[累计Whipsaw] 检测异常: {e}")

        # 8. 生成改善建议
        suggestions = self.improvement_advisor.generate_daily_suggestions(
            detector, rhythm_result, redundant_result, cumulative_whipsaw
        )

        # 8a. 自动写入AUDIT层改善项 (v3.5)
        try:
            save_audit_improvements(suggestions, date_str)
        except Exception as e:
            logger.warning(f"[改善追踪] 自动写入失败: {e}")

        # 8b. TESTING项自动验证 (v3.653)
        testing_results = []
        try:
            testing_results = self.testing_verifier.verify(
                all_lines, dq_result, rhythm_result, rejected_signals
            )
            _pass = sum(1 for r in testing_results if r["verdict"] == "PASS")
            _fail = sum(1 for r in testing_results if r["verdict"] == "FAIL")
            _active = sum(1 for r in testing_results if r["verdict"] == "ACTIVE")
            logger.info(f"TESTING验证: {len(testing_results)}项 → {_pass} PASS / {_fail} FAIL / {_active} ACTIVE")
        except Exception as e:
            logger.warning(f"[TESTING验证] 异常: {e}")

        # 9. 生成报告
        report = self.report_generator.generate_daily_report(
            date_str, detector, logic_result, redundant_result, rhythm_result, suggestions,
            plugin_result=plugin_result,
            plugin_pnl=plugin_pnl,
            trend_validation=trend_validation,
            rejected_backtest=rejected_backtest,
            dq_result=dq_result,
            testing_results=testing_results,
            cumulative_whipsaw=cumulative_whipsaw,
        )

        # 10. 保存报告和质量评分
        report_file = f"{CONFIG['output_dir']}/daily_v3_{date_str}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"每日报告已保存: {report_file}")

        # 11. Generate per-symbol HTML reports
        html_files = self.report_generator.generate_daily_html_reports(
            date_str, detector, logic_result, redundant_result,
            rhythm_result, suggestions, rejected_signals
        )
        html_dir = f"{CONFIG['output_dir']}/{date_str}"
        logger.info(f"Per-symbol HTML reports: {len(html_files)} files → {html_dir}/")

        # 保存质量评分
        self.quality_scores["daily"][date_str] = {
            "rhythm_score": rhythm_result.get("overall_score", 0),
            "buy_score": rhythm_result.get("buy_score", 0),
            "sell_score": rhythm_result.get("sell_score", 0),
            "excellent_buy_ratio": rhythm_result.get("excellent_buy_ratio", 0),
            "excellent_sell_ratio": rhythm_result.get("excellent_sell_ratio", 0),
            "trade_count": len(trades),
            "loss_amount": redundant_result.get("total_loss_amount", 0),
            "same_bar_count": len(redundant_result.get("same_bar_trades", [])),
            "logic_errors": logic_result.get("trend_conflicts", 0) + logic_result.get("vision_errors", 0),
            "bad_buys": rhythm_result.get("bad_buys", 0),
            "bad_sells": rhythm_result.get("bad_sells", 0),
            "dq_total": dq_result.get("total_issues", 0),
            "dq_api_errors": detector.stats.get("dq_api_errors", 0),
            "dq_data_issues": detector.stats.get("dq_data_issues", 0),
            "dq_indicator_failures": dq_result.get("indicator_failures", 0),
            "dq_vision_issues": detector.stats.get("dq_vision_issues", 0),
            "key007_vision_filter_block": dq_result.get("vision_filter_block", 0),
            "key007_plugin_knn_query": dq_result.get("plugin_knn_query", 0),
            "key007_plugin_knn_suppress": dq_result.get("plugin_knn_suppress", 0),
        }
        self._save_quality_scores()

        return {
            "date": date_str,
            "detector": detector,
            "logic_result": logic_result,
            "dq_result": dq_result,
            "redundant_result": redundant_result,
            "rhythm_result": rhythm_result,
            "plugin_pnl": plugin_pnl,
            "trend_validation": trend_validation,
            "rejected_backtest": rejected_backtest,
            "suggestions": suggestions,
            "report": report,
            "report_file": report_file,
            "html_files": html_files,
            "html_dir": html_dir,
            "testing_results": testing_results,
        }

    def analyze_weekly(self, end_date: str = None) -> Dict:
        """执行每周分析"""
        if not end_date:
            end_date = get_today_date_ny()

        # 计算本周日期范围
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=6)
        week_dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        logger.info(f"开始每周分析: {week_dates[0]} ~ {week_dates[-1]}")

        # 收集每日摘要
        daily_summaries = []
        for date in week_dates:
            if date in self.quality_scores.get("daily", {}):
                daily_data = self.quality_scores["daily"][date]
                daily_summaries.append({
                    "date": date,
                    "trade_count": daily_data.get("trade_count", 0),
                    "rhythm_score": daily_data.get("rhythm_score", 50),
                    "loss_amount": daily_data.get("loss_amount", 0),
                    "same_bar_count": daily_data.get("same_bar_count", 0),
                    "logic_errors": daily_data.get("logic_errors", 0),
                    "bad_buys": daily_data.get("bad_buys", 0),
                    "bad_sells": daily_data.get("bad_sells", 0),
                })

        # 加载本周全部交易记录，检测跨天来回买卖
        all_week_trades = self.whipsaw_detector.load_trades_range(
            CONFIG["data_files"]["trade_history"], week_dates[0], week_dates[-1])
        whipsaw_result = self.whipsaw_detector.detect(all_week_trades)
        logger.info(f"周Whipsaw检测: {len(all_week_trades)}笔交易, "
                     f"{whipsaw_result['summary'].get('whipsaw_count', 0)}个来回品种")

        # 生成周改善建议
        suggestions = self.improvement_advisor.generate_weekly_suggestions(daily_summaries, whipsaw_result)

        # 生成周报
        report = self.report_generator.generate_weekly_report(
            week_dates[0], week_dates[-1], daily_summaries, suggestions, whipsaw_result
        )

        # 保存周报
        week_id = f"{week_dates[0]}_{week_dates[-1]}"
        report_file = f"{CONFIG['output_dir']}/weekly_v3_{week_id}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"每周报告已保存: {report_file}")

        # 保存周质量评分
        self.quality_scores["weekly"][week_id] = {
            "week": week_id,
            "total_trades": sum(d.get("trade_count", 0) for d in daily_summaries),
            "avg_rhythm_score": sum(d.get("rhythm_score", 50) for d in daily_summaries) / len(daily_summaries) if daily_summaries else 0,
            "total_loss": sum(d.get("loss_amount", 0) for d in daily_summaries),
            "bad_buys": sum(d.get("bad_buys", 0) for d in daily_summaries),
            "bad_sells": sum(d.get("bad_sells", 0) for d in daily_summaries),
        }
        self._save_quality_scores()

        return {
            "week": week_id,
            "daily_summaries": daily_summaries,
            "suggestions": suggestions,
            "report": report,
            "report_file": report_file,
        }

    def analyze_monthly(self, month: str = None) -> Dict:
        """执行每月分析"""
        if not month:
            month = get_ny_now().strftime("%Y-%m")

        logger.info(f"开始每月分析: {month}")

        # 收集本月所有周的数据
        weekly_summaries = []
        for week_id, week_data in self.quality_scores.get("weekly", {}).items():
            if week_id.startswith(month):
                weekly_summaries.append(week_data)

        # 如果没有周数据，尝试从日数据汇总
        if not weekly_summaries:
            daily_in_month = [
                (date, data) for date, data in self.quality_scores.get("daily", {}).items()
                if date.startswith(month)
            ]
            if daily_in_month:
                # 简单汇总为一个"周"
                weekly_summaries.append({
                    "week": month,
                    "total_trades": sum(d.get("trade_count", 0) for _, d in daily_in_month),
                    "avg_rhythm_score": sum(d.get("rhythm_score", 50) for _, d in daily_in_month) / len(daily_in_month),
                    "total_loss": sum(d.get("loss_amount", 0) for _, d in daily_in_month),
                    "bad_buys": sum(d.get("bad_buys", 0) for _, d in daily_in_month),
                    "bad_sells": sum(d.get("bad_sells", 0) for _, d in daily_in_month),
                })

        # 加载全月交易记录，检测跨天来回买卖
        import calendar
        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]
        month_start = f"{month}-01"
        month_end = f"{month}-{last_day:02d}"
        all_month_trades = self.whipsaw_detector.load_trades_range(
            CONFIG["data_files"]["trade_history"], month_start, month_end)
        whipsaw_result = self.whipsaw_detector.detect(all_month_trades)
        logger.info(f"月Whipsaw检测: {len(all_month_trades)}笔交易, "
                     f"{whipsaw_result['summary'].get('whipsaw_count', 0)}个来回品种")

        # 生成月改善建议
        suggestions = self.improvement_advisor.generate_monthly_suggestions(weekly_summaries, whipsaw_result)

        # 生成月报
        report = self.report_generator.generate_monthly_report(month, weekly_summaries, suggestions, whipsaw_result)

        # 保存月报
        report_file = f"{CONFIG['output_dir']}/monthly_v3_{month}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"每月报告已保存: {report_file}")

        # 保存月质量评分
        self.quality_scores["monthly"][month] = {
            "month": month,
            "total_trades": sum(w.get("total_trades", 0) for w in weekly_summaries),
            "avg_rhythm_score": sum(w.get("avg_rhythm_score", 50) for w in weekly_summaries) / len(weekly_summaries) if weekly_summaries else 0,
            "total_loss": sum(w.get("total_loss", 0) for w in weekly_summaries),
        }
        self._save_quality_scores()

        return {
            "month": month,
            "weekly_summaries": weekly_summaries,
            "suggestions": suggestions,
            "report": report,
            "report_file": report_file,
        }

    def run_full_analysis(self) -> Dict:
        """执行完整分析 (每日+每周+每月)"""
        logger.info("=" * 50)
        logger.info("开始完整分析")
        logger.info("=" * 50)

        results = {}

        # 每日分析
        daily_result = self.analyze_daily()
        results["daily"] = daily_result
        print(f"\n每日报告: {daily_result['report_file']}")

        # 每周分析
        weekly_result = self.analyze_weekly()
        results["weekly"] = weekly_result
        print(f"每周报告: {weekly_result['report_file']}")

        # 每月分析
        monthly_result = self.analyze_monthly()
        results["monthly"] = monthly_result
        print(f"每月报告: {monthly_result['report_file']}")

        logger.info("完整分析完成")
        return results


# ============================================================
# 主入口
# ============================================================

def run_continuous_watch(analyzer: "EnhancedLogAnalyzer", interval: int = 300):
    """
    持续监控模式 - 定期分析日志并输出心跳

    Args:
        analyzer: 分析器实例
        interval: 分析间隔(秒), 默认5分钟
    """
    NY_TZ = ZoneInfo("America/New_York")
    last_analysis_hour = -1
    cycle_count = 0

    logger.info(f"[WATCH] 启动持续监控模式 | 分析间隔: {interval}秒")
    print(f"\n{'='*60}")
    print("[WATCH] Log Analyzer v3.1 - 持续监控模式")
    print(f"{'='*60}")
    print(f"[*] 分析间隔: {interval}秒 ({interval//60}分钟)")
    print(f"[*] 输出目录: {CONFIG['output_dir']}")
    print(f"[*] 启动时间: {datetime.now(NY_TZ).strftime('%Y-%m-%d %H:%M:%S')} (纽约)")
    print(f"{'='*60}\n")

    while True:
        try:
            now = datetime.now(NY_TZ)
            cycle_count += 1

            # 心跳输出 (每个周期)
            print(f"[{now.strftime('%H:%M:%S')}] [HEARTBEAT] 周期 #{cycle_count} | 分析中...")

            # 执行每日分析
            try:
                daily_result = analyzer.analyze_daily()
                rhythm_score = daily_result.get("rhythm_result", {}).get("overall_score", 0)
                trade_count = len(daily_result.get("rhythm_result", {}).get("trades", []))
                suggestions_count = len(daily_result.get("suggestions", []))

                # 简洁输出
                print(f"[{now.strftime('%H:%M:%S')}] [OK] 分析完成 | "
                      f"节奏评分: {rhythm_score:.1f}/100 | "
                      f"交易数: {trade_count} | "
                      f"建议: {suggestions_count}条")

                # 如果有高优先级问题，立即提醒
                high_priority = [s for s in daily_result.get("suggestions", [])
                               if s.priority == "HIGH"]
                if high_priority:
                    print(f"[{now.strftime('%H:%M:%S')}] [WARN] 发现 {len(high_priority)} 个高优先级问题:")
                    for s in high_priority[:3]:
                        print(f"    [HIGH] {s.title}")

            except Exception as e:
                logger.error(f"[WATCH] 分析出错: {e}")
                print(f"[{now.strftime('%H:%M:%S')}] [ERROR] 分析出错: {e}")

            # 每小时执行一次完整分析 (整点)
            current_hour = now.hour
            if current_hour != last_analysis_hour:
                last_analysis_hour = current_hour
                print(f"[{now.strftime('%H:%M:%S')}] [FULL] 整点完整分析...")
                try:
                    analyzer.run_full_analysis()
                    print(f"[{now.strftime('%H:%M:%S')}] [OK] 完整分析已保存")
                except Exception as e:
                    logger.error(f"[WATCH] 完整分析出错: {e}")

            # 等待下一个周期
            time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n[{datetime.now(NY_TZ).strftime('%H:%M:%S')}] [STOP] 收到停止信号，正在退出...")
            logger.info("[WATCH] 持续监控模式已停止")
            break
        except Exception as e:
            logger.error(f"[WATCH] 未知错误: {e}")
            print(f"[ERROR] 未知错误: {e}，10秒后重试...")
            time.sleep(10)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="增强版日志分析器 v3.1")
    parser.add_argument("--daily", action="store_true", help="执行每日分析")
    parser.add_argument("--weekly", action="store_true", help="执行每周分析")
    parser.add_argument("--monthly", action="store_true", help="执行每月分析")
    parser.add_argument("--full", action="store_true", help="执行完整分析")
    parser.add_argument("--watch", action="store_true", help="持续监控模式")
    parser.add_argument("--interval", type=int, default=300, help="监控间隔(秒), 默认300")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--month", type=str, help="指定月份 (YYYY-MM)")

    args = parser.parse_args()

    analyzer = EnhancedLogAnalyzer()

    # 持续监控模式
    if args.watch:
        run_continuous_watch(analyzer, args.interval)
        return

    if args.full or (not args.daily and not args.weekly and not args.monthly):
        # 默认执行完整分析
        results = analyzer.run_full_analysis()

        # 打印今日改善建议摘要
        print("\n" + "=" * 50)
        print("📋 今日改善建议摘要")
        print("=" * 50)
        for s in results["daily"]["suggestions"][:5]:
            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(s.priority, "⚪")
            print(f"{priority_icon} [{s.priority}] {s.title}")
            print(f"   -> {s.action}")

        # v3.641: 完整分析后自动进入持续监控模式
        print(f"\n[INFO] 完整分析完成，自动进入持续监控模式 (间隔{args.interval}秒，Ctrl+C退出)")
        run_continuous_watch(analyzer, args.interval)
        return

    elif args.daily:
        result = analyzer.analyze_daily(args.date)
        print(f"\n每日报告: {result['report_file']}")

    elif args.weekly:
        result = analyzer.analyze_weekly(args.date)
        print(f"\n每周报告: {result['report_file']}")

    elif args.monthly:
        result = analyzer.analyze_monthly(args.month)
        print(f"\n每月报告: {result['report_file']}")


if __name__ == "__main__":
    main()
