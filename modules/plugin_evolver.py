"""
Module D: 外挂智能进化 — 基于N字每日统计自动调整外挂参数
v1.0: Phase 1 记录+建议模式

依赖:
- state/n_daily_stats.json (当日N字×交易统计)
- plugin_profit_state.json (外挂盈亏追踪)

输出:
- state/plugin_evolution.json: 累积统计+进化建议+参数调整
"""

import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

DAILY_STATS_FILE = "state/n_daily_stats.json"
PROFIT_STATE_FILE = "plugin_profit_state.json"
EVOLUTION_STATE_FILE = "state/plugin_evolution.json"

# Phase 1: 仅记录+建议, Phase 2: 自动调参
PHASE2_ENABLED = False

# 最少样本数才产出建议
MIN_SAMPLES_FOR_ADVICE = 5

# 默认外挂列表
KNOWN_PLUGINS = [
    "SuperTrend", "SuperTrend+AV2", "RobHoffman",
    "DoublePattern", "ChanBS", "Feiyun", "L1/L2",
]


def _safe_json_read(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[进化] 读取 {filepath} 失败: {e}")
    return None


def _safe_json_write(filepath, data):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        logger.error(f"[进化] 写入 {filepath} 失败: {e}")
        return False


class PluginEvolver:
    """
    外挂智能进化器

    每日收盘后调用 daily_evolve():
    1. 读取当日N字统计 (state/n_daily_stats.json)
    2. 合并到累积统计 (state/plugin_evolution.json)
    3. 分析每个品种×外挂×N字状态的交易效果
    4. 生成进化建议 (Phase 1: 仅日志输出)
    5. Phase 2: 自动调整参数
    """

    def __init__(self):
        self.state = self._load_state()

    def _load_state(self):
        data = _safe_json_read(EVOLUTION_STATE_FILE)
        if data:
            return data
        return {
            "version": "1.0",
            "last_update": "",
            "history": [],       # 最近30天的每日摘要
            "cumulative": {},    # {symbol: {plugin: {perfect_n: N, imperfect_n: N, side: N}}}
            "advice": {},        # {symbol: {plugin: {"action": str, "reason": str}}}
            "adjustments": {},   # Phase 2: {symbol: {plugin: {param: value}}}
        }

    def _save_state(self):
        _safe_json_write(EVOLUTION_STATE_FILE, self.state)

    def daily_evolve(self):
        """每日收盘后执行: 累积数据 + 分析 + 建议"""
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")

        # 1. 读取当日N字统计
        daily = _safe_json_read(DAILY_STATS_FILE)
        if not daily or not daily.get("symbols"):
            logger.info("[进化] 无当日N字统计数据")
            return None

        # 2. 读取外挂盈亏数据
        profit_data = _safe_json_read(PROFIT_STATE_FILE)

        # 3. 累积统计
        self._accumulate(daily)

        # 4. 保存每日摘要到history (最近30天)
        summary = self._make_daily_summary(daily, today)
        self.state["history"].append(summary)
        if len(self.state["history"]) > 30:
            self.state["history"] = self.state["history"][-30:]

        # 5. 生成进化建议
        advice = self._analyze_and_advise(profit_data)
        self.state["advice"] = advice

        # 6. Phase 2: 自动调参
        if PHASE2_ENABLED:
            self._auto_adjust(advice)

        self.state["last_update"] = today
        self._save_state()

        logger.info(f"[进化] 每日进化完成: {len(daily['symbols'])}品种, "
                     f"{len(advice)}条建议")
        return advice

    def _accumulate(self, daily):
        """将当日数据累积到cumulative"""
        cum = self.state.get("cumulative", {})
        for symbol, sdata in daily.get("symbols", {}).items():
            if symbol not in cum:
                cum[symbol] = {}
            for n_cat in ("perfect_n", "imperfect_n", "side"):
                cat_data = sdata.get(n_cat, {})
                by_source = cat_data.get("by_source", {})
                for src, count in by_source.items():
                    if src not in cum[symbol]:
                        cum[symbol][src] = {"perfect_n": 0, "imperfect_n": 0, "side": 0, "total": 0}
                    cum[symbol][src][n_cat] += count
                    cum[symbol][src]["total"] += count
        self.state["cumulative"] = cum

    def _make_daily_summary(self, daily, date):
        """生成当日摘要"""
        total_scans = 0
        total_trades = 0
        n_breakdown = {"perfect_n": 0, "imperfect_n": 0, "side": 0}
        for sdata in daily.get("symbols", {}).values():
            for n_cat in ("perfect_n", "imperfect_n", "side"):
                cat = sdata.get(n_cat, {})
                total_scans += cat.get("scans", 0)
                trades = cat.get("trades", 0)
                total_trades += trades
                n_breakdown[n_cat] += trades
        return {
            "date": date,
            "symbols": len(daily.get("symbols", {})),
            "scans": total_scans,
            "trades": total_trades,
            "breakdown": n_breakdown,
        }

    def _analyze_and_advise(self, profit_data=None):
        """分析累积数据，生成进化建议"""
        advice = {}
        cum = self.state.get("cumulative", {})

        # 外挂盈亏映射: {plugin: {symbol: {wins: N, losses: N, pnl: float}}}
        pnl_map = self._build_pnl_map(profit_data) if profit_data else {}

        for symbol, plugins in cum.items():
            advice[symbol] = {}
            for plugin, stats in plugins.items():
                total = stats.get("total", 0)
                if total < MIN_SAMPLES_FOR_ADVICE:
                    continue

                perfect = stats.get("perfect_n", 0)
                imperfect = stats.get("imperfect_n", 0)
                side = stats.get("side", 0)

                # 计算N字质量比 (完美N交易占总交易的比例)
                quality_ratio = perfect / total if total > 0 else 0

                # 获取盈亏数据
                plugin_pnl = pnl_map.get(plugin, {}).get(symbol, {})
                win_rate = plugin_pnl.get("win_rate", None)

                # 生成建议
                rec = self._generate_recommendation(
                    symbol, plugin, total, perfect, imperfect, side,
                    quality_ratio, win_rate
                )
                if rec:
                    advice[symbol][plugin] = rec

        return advice

    def _generate_recommendation(self, symbol, plugin, total, perfect, imperfect, side,
                                  quality_ratio, win_rate):
        """生成单条进化建议"""
        # 规则1: SIDE交易过多 → 建议收紧
        side_ratio = side / total if total > 0 else 0
        if side_ratio > 0.5:
            return {
                "action": "TIGHTEN",
                "level": "HIGH",
                "reason": f"SIDE交易占{side_ratio:.0%}(>{50}%), 建议仅在N字有效时交易",
                "side_trades": side,
                "total_trades": total,
                "quality_ratio": round(quality_ratio, 2),
            }

        # 规则2: 完美N占比高且胜率好 → 建议放宽
        if quality_ratio > 0.7 and win_rate is not None and win_rate > 0.6:
            return {
                "action": "LOOSEN",
                "level": "LOW",
                "reason": f"完美N占{quality_ratio:.0%}, 胜率{win_rate:.0%}, 表现优秀",
                "quality_ratio": round(quality_ratio, 2),
                "win_rate": round(win_rate, 2),
            }

        # 规则3: 不完美N交易多但亏损 → 建议收紧
        imp_ratio = imperfect / total if total > 0 else 0
        if imp_ratio > 0.3 and win_rate is not None and win_rate < 0.4:
            return {
                "action": "TIGHTEN",
                "level": "MEDIUM",
                "reason": f"不完美N交易占{imp_ratio:.0%}, 胜率{win_rate:.0%}, 建议仅完美N交易",
                "imperfect_trades": imperfect,
                "win_rate": round(win_rate, 2),
            }

        # 规则4: 样本充足但无明显模式 → 保持观察
        if total >= MIN_SAMPLES_FOR_ADVICE:
            return {
                "action": "HOLD",
                "level": "INFO",
                "reason": f"样本{total}, 完美N:{quality_ratio:.0%}, 暂无明确建议",
                "quality_ratio": round(quality_ratio, 2),
            }

        return None

    def _build_pnl_map(self, profit_data):
        """从plugin_profit_state构建盈亏映射"""
        pnl_map = {}
        if not profit_data:
            return pnl_map

        # profit_data格式: {asset_type: {plugin: {symbol: {...}}}}
        for asset_type in ("crypto", "stock"):
            plugins = profit_data.get(asset_type, {})
            for plugin_name, symbols in plugins.items():
                if plugin_name not in pnl_map:
                    pnl_map[plugin_name] = {}
                for sym, data in symbols.items():
                    wins = data.get("wins", 0)
                    losses = data.get("losses", 0)
                    total = wins + losses
                    pnl_map[plugin_name][sym] = {
                        "wins": wins,
                        "losses": losses,
                        "pnl": data.get("realized_pnl", 0),
                        "win_rate": wins / total if total > 0 else None,
                    }

        return pnl_map

    def _auto_adjust(self, advice):
        """Phase 2: 根据建议自动调参 (暂未启用)"""
        adjustments = {}
        for symbol, plugins in advice.items():
            for plugin, rec in plugins.items():
                action = rec.get("action")
                if action == "TIGHTEN":
                    # 收紧: 提高外挂信号的置信度要求
                    adjustments.setdefault(symbol, {})[plugin] = {
                        "confidence_mult": 1.2,  # 提高20%门槛
                        "n_gate_strict": True,    # 仅完美N允许
                    }
                elif action == "LOOSEN":
                    # 放宽: 降低门槛
                    adjustments.setdefault(symbol, {})[plugin] = {
                        "confidence_mult": 0.9,  # 降低10%门槛
                        "n_gate_strict": False,
                    }
        self.state["adjustments"] = adjustments
        logger.info(f"[进化] Phase 2 调参: {len(adjustments)}品种")

    def get_advice_for_symbol(self, symbol):
        """供主程序查询某品种的进化建议"""
        return self.state.get("advice", {}).get(symbol, {})

    def get_adjustment(self, symbol, plugin_name):
        """Phase 2: 获取某品种某外挂的参数调整"""
        if not PHASE2_ENABLED:
            return None
        return self.state.get("adjustments", {}).get(symbol, {}).get(plugin_name)

    def get_summary(self):
        """获取进化摘要供monitor显示"""
        cum = self.state.get("cumulative", {})
        advice = self.state.get("advice", {})
        history = self.state.get("history", [])

        total_symbols = len(cum)
        total_advice = sum(len(v) for v in advice.values())
        tighten_count = sum(1 for s in advice.values() for r in s.values() if r.get("action") == "TIGHTEN")
        loosen_count = sum(1 for s in advice.values() for r in s.values() if r.get("action") == "LOOSEN")

        # 最近7天交易趋势
        recent = history[-7:] if history else []
        recent_trades = sum(d.get("trades", 0) for d in recent)

        return {
            "symbols": total_symbols,
            "advice_count": total_advice,
            "tighten": tighten_count,
            "loosen": loosen_count,
            "recent_7d_trades": recent_trades,
            "last_update": self.state.get("last_update", ""),
            "phase": "Phase2" if PHASE2_ENABLED else "Phase1",
        }
