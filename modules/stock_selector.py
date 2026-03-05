"""
Module A: 股票预选模块 — 每日评分+分级+活跃池
v1.0: Phase 1 纯记录模式, 不拦截任何交易

数据来源(全部现有JSON, 零新增):
- global_trend_state.json: 趋势/regime/x4_dow/x4_chan
- state/vision/pattern_latest.json: Vision形态识别结果
- state/human_dual_track.json: 校准器准确率(可选)

输出:
- state/stock_selection.json: 评分+分级+活跃池
"""

import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

# 文件路径
GLOBAL_TREND_STATE_FILE = "global_trend_state.json"
VISION_PATTERN_FILE = "state/vision/pattern_latest.json"
SELECTION_STATE_FILE = "state/stock_selection.json"
AUDIT_DIR = "logs/audit"

# 所有交易品种 (与主程序一致, 使用主程序内部符号名)
ALL_SYMBOLS_STOCK = ["TSLA", "COIN", "RDDT", "NBIS", "CRWV", "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR"]
ALL_SYMBOLS_CRYPTO = ["BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC"]
ALL_SYMBOLS = ALL_SYMBOLS_STOCK + ALL_SYMBOLS_CRYPTO

# 分级阈值
TIER_A_MIN = 40  # 40-50
TIER_B_MIN = 30  # 30-39
TIER_C_MIN = 20  # 20-29
# D = 0-19


def _safe_json_read(filepath):
    """安全读取JSON文件"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[预选] 读取 {filepath} 失败: {e}")
    return None


def _safe_json_write(filepath, data):
    """安全写入JSON文件(原子操作)"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        temp_file = filepath + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        logger.error(f"[预选] 写入 {filepath} 失败: {e}")
        return False


def _is_crypto(symbol):
    """判断是否为加密货币"""
    return symbol.endswith("USDC") or symbol.endswith("USDT") or symbol.endswith("-USD")


class StockSelector:
    """
    股票预选模块: 每日对所有标的进行5维度评分, 按总分分级

    评分维度(每项0-10, 总分0-50):
    1. 趋势清晰度: 缠论+x4+Vision三方向一致性
    2. 动能强度: regime状态(TRENDING vs RANGING)
    3. 波动率适中: 基于regime推断(无直接ATR数据)
    4. 形态结构: Vision形态识别结果
    5. 大小周期共振: current_trend vs big_trend(x4)一致性
    """

    def __init__(self):
        self.state_file = SELECTION_STATE_FILE

    def score_single(self, symbol, trend_data, pattern_data) -> dict:
        """
        对单个品种5维度评分

        Args:
            symbol: 品种代码
            trend_data: global_trend_state中该品种的数据
            pattern_data: pattern_latest中该品种的数据

        Returns:
            dict: {trend, momentum, volatility, structure, resonance, total, tier}
        """
        if not trend_data:
            return {"trend": 0, "momentum": 0, "volatility": 0,
                    "structure": 5, "resonance": 0, "total": 5, "tier": "D"}

        # --- 维度1: 趋势清晰度 (0-10) ---
        # 检查big_trend, current_trend, x4_dow, x4_chan的方向一致性
        big = (trend_data.get("big_trend") or "SIDE").upper()
        current = (trend_data.get("current_trend") or "SIDE").upper()
        x4_dow = (trend_data.get("x4_dow_trend") or big).upper() if trend_data.get("x4_dow_trend") else big
        x4_chan = (trend_data.get("x4_chan_trend") or big).upper() if trend_data.get("x4_chan_trend") else big

        directions = [big, current, x4_dow, x4_chan]
        # 去除SIDE后看非SIDE方向是否一致
        non_side = [d for d in directions if d != "SIDE"]

        if len(non_side) == 0:
            # 全部SIDE → 趋势不清晰
            trend_score = 3
        elif len(set(non_side)) == 1:
            # 所有非SIDE方向一致
            if len(non_side) >= 3:
                trend_score = 10  # 强一致
            elif len(non_side) == 2:
                trend_score = 8
            else:
                trend_score = 7
        elif len(set(non_side)) == 2:
            # 有分歧
            trend_score = 5
        else:
            # 多方向分歧
            trend_score = 3

        # --- 维度2: 动能强度 (0-10) ---
        # 根据regime和regime_x4判断
        regime = (trend_data.get("regime") or "RANGING").upper()
        regime_x4 = (trend_data.get("regime_x4") or "RANGING").upper()

        if "TREND" in regime and "TREND" in regime_x4:
            momentum_score = 9  # 双周期趋势
        elif "TREND" in regime or "TREND" in regime_x4:
            momentum_score = 7  # 单周期趋势
        else:
            momentum_score = 4  # 双震荡

        # --- 维度3: 波动率适中 (0-10) ---
        # 基于regime推断波动率适中度
        # TRENDING通常波动率适中(有方向性), RANGING可能过低或过高
        crypto = _is_crypto(symbol)
        if regime == "RANGING" and regime_x4 == "RANGING":
            volatility_score = 5  # 震荡市, 波动可能不规律
        elif "TREND" in regime:
            volatility_score = 8  # 趋势市, 波动率通常适中
        else:
            volatility_score = 6  # 混合

        # 加密货币波动率天然偏高, 给个微调
        if crypto and "TREND" not in regime:
            volatility_score = max(4, volatility_score - 1)

        # --- 维度4: 形态结构 (0-10) ---
        # 基于Vision形态识别结果
        if pattern_data:
            pattern = (pattern_data.get("pattern") or "NONE").upper()
            confidence = pattern_data.get("confidence", 0) or 0
            volume_confirmed = pattern_data.get("volume_confirmed", False)

            if pattern != "NONE":
                # 有明确形态
                structure_score = 6
                if confidence >= 0.7:
                    structure_score += 2
                elif confidence >= 0.5:
                    structure_score += 1
                if volume_confirmed:
                    structure_score += 2
                structure_score = min(10, structure_score)
            else:
                # 无形态
                structure_score = 5
        else:
            structure_score = 5  # 无数据默认中间

        # --- 维度5: 大小周期共振 (0-10) ---
        # current_trend vs big_trend 是否同向
        if big == current and big != "SIDE":
            resonance_score = 10  # 完美共振
        elif big == "SIDE" and current == "SIDE":
            resonance_score = 4   # 双SIDE, 无方向
        elif big == "SIDE" or current == "SIDE":
            resonance_score = 5   # 一方SIDE
        elif big != current:
            resonance_score = 2   # 逆向
        else:
            resonance_score = 5

        # 计算总分和等级
        total = trend_score + momentum_score + volatility_score + structure_score + resonance_score
        tier = self._get_tier(total)

        return {
            "trend": trend_score,
            "momentum": momentum_score,
            "volatility": volatility_score,
            "structure": structure_score,
            "resonance": resonance_score,
            "total": total,
            "tier": tier
        }

    def _get_tier(self, total):
        """根据总分返回等级"""
        if total >= TIER_A_MIN:
            return "A"
        elif total >= TIER_B_MIN:
            return "B"
        elif total >= TIER_C_MIN:
            return "C"
        else:
            return "D"

    def score_all(self) -> list:
        """
        遍历所有品种评分, 按total降序排列

        Returns:
            list of (symbol, score_dict), sorted by total desc
        """
        # 读取数据源
        trend_state = _safe_json_read(GLOBAL_TREND_STATE_FILE) or {}
        pattern_state = _safe_json_read(VISION_PATTERN_FILE) or {}
        symbols_data = trend_state.get("symbols", {})

        results = []
        for symbol in ALL_SYMBOLS:
            # 趋势数据: 尝试主程序内部符号名
            t_data = symbols_data.get(symbol)

            # 形态数据: pattern_latest用的是主程序符号(BTCUSDC等)
            p_data = pattern_data = pattern_state.get(symbol)

            score = self.score_single(symbol, t_data, p_data)
            results.append((symbol, score))

        # 按总分降序
        results.sort(key=lambda x: x[1]["total"], reverse=True)
        return results

    def select_active_pool(self, scores: list) -> dict:
        """
        根据评分分级, 生成活跃池

        Args:
            scores: [(symbol, score_dict), ...] from score_all()

        Returns:
            dict: {active: [...], reduced: [...], paused: [...]}
        """
        active = []    # A+B级: 正常/满配额
        reduced = []   # C级: 减半
        paused = []    # D级: 暂停

        for symbol, score in scores:
            tier = score["tier"]
            if tier in ("A", "B"):
                active.append(symbol)
            elif tier == "C":
                reduced.append(symbol)
            else:
                paused.append(symbol)

        return {
            "active": active,
            "reduced": reduced,
            "paused": paused
        }

    def run_daily(self) -> dict:
        """
        入口函数: 每日运行一次

        流程: score_all → select_active_pool → 写入JSON → 返回结果
        """
        ny_now = datetime.now(NY_TZ)
        today = ny_now.strftime("%Y-%m-%d")

        logger.info(f"[预选] 开始每日评分 ({today})")

        scores = self.score_all()

        # v1.1: 审计降级 — 读取前一天审计报告的降级建议
        audit_penalties = self._load_audit_penalties()
        if audit_penalties:
            for i, (symbol, score) in enumerate(scores):
                if symbol in audit_penalties:
                    penalty = audit_penalties[symbol]
                    old_total = score["total"]
                    score["total"] = max(0, old_total - penalty)
                    score["tier"] = self._get_tier(score["total"])
                    score["audit_penalty"] = penalty
                    scores[i] = (symbol, score)
                    logger.info(f"[预选] {symbol}: 审计降级 -{penalty}分 ({old_total}→{score['total']}, {score['tier']}级)")
            scores.sort(key=lambda x: x[1]["total"], reverse=True)

        pool = self.select_active_pool(scores)

        # 构建scores字典
        scores_dict = {}
        for symbol, score in scores:
            scores_dict[symbol] = score

        result = {
            "date": today,
            "mode": "PHASE2_WARN",  # Phase 2: C/D级强警告(不拦截)
            "scores": scores_dict,
            "pool": pool,
            "updated_at": ny_now.isoformat()
        }

        _safe_json_write(self.state_file, result)

        # 日志输出摘要
        a_count = len(pool["active"])
        c_count = len(pool["reduced"])
        d_count = len(pool["paused"])
        logger.info(f"[预选] 评分完成: A/B={a_count}, C={c_count}, D={d_count}")

        for symbol, score in scores:
            tier = score["tier"]
            total = score["total"]
            if tier in ("C", "D"):
                penalty_str = f" (审计-{score.get('audit_penalty', 0)})" if score.get('audit_penalty') else ""
                logger.info(f"[预选] {symbol}: 总分={total}{penalty_str}, 等级={tier} — Phase2警告")

        return result

    def _load_audit_penalties(self) -> dict:
        """
        v1.1: 读取最近审计报告中的降级建议
        Returns: {symbol: penalty_points, ...}
        """
        penalties = {}
        try:
            # 找最近的审计文件
            audit_files = []
            if os.path.exists(AUDIT_DIR):
                for f in os.listdir(AUDIT_DIR):
                    if f.startswith("audit_") and f.endswith(".json"):
                        audit_files.append(os.path.join(AUDIT_DIR, f))
            if not audit_files:
                return penalties
            audit_files.sort(reverse=True)
            latest = _safe_json_read(audit_files[0])
            if not latest:
                return penalties
            # 读取suggestions中的tier_review
            for suggestion in latest.get("suggestions", []):
                if suggestion.get("type") == "tier_review":
                    sym = suggestion.get("symbol")
                    if sym:
                        penalties[sym] = 5  # 降级扣5分
        except Exception as e:
            logger.warning(f"[预选] 读取审计降级失败: {e}")
        return penalties

    def get_tier(self, symbol) -> str:
        """
        快速查询某品种当前等级(从缓存JSON读取)

        Returns:
            str: "A", "B", "C", "D", or "?" (无数据)
        """
        data = _safe_json_read(self.state_file)
        if not data:
            return "?"
        return data.get("scores", {}).get(symbol, {}).get("tier", "?")
