# ========================================================================
# L1 RULE TRACKER v1.0
# ========================================================================
# 目标: 追踪L1增强模块的6个规则效果，建立"规则→效果→优化"闭环
#
# 规则ID:
#   R1 - 多周期斜率
#   R2 - 趋势结构(HH/HL)
#   R3 - 动态Choppiness
#   R4 - 大周期保护
#   R5 - 一致性加成
#   R6 - 三方投票权重
#
# 验证周期: 10根K线后 (约5小时)
# ========================================================================

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# ========================================================================
# 常量定义
# ========================================================================

TRACKER_FILE = "logs/l1_rule_tracker.json"
DAILY_SUMMARY_FILE = "logs/l1_daily_summary.txt"
VERIFY_AFTER_BARS = 10  # 10根K线后验证
PRICE_CHANGE_THRESHOLD = 0.005  # 0.5% 价格变化阈值


class RuleID(Enum):
    """规则ID枚举"""
    R1_MULTI_SLOPE = "R1"      # 多周期斜率
    R2_STRUCTURE = "R2"        # 趋势结构(HH/HL)
    R3_CHOPPINESS = "R3"       # 动态Choppiness
    R4_BIG_TREND = "R4"        # 大周期保护
    R5_CONSISTENCY = "R5"      # 一致性加成
    R6_VOTING = "R6"           # 三方投票权重


class Outcome(Enum):
    """验证结果"""
    CORRECT = "CORRECT"
    WRONG = "WRONG"
    NEUTRAL = "NEUTRAL"


RULE_NAMES = {
    "R1": "多周期斜率",
    "R2": "趋势结构",
    "R3": "动态Choppiness",
    "R4": "大周期保护",
    "R5": "一致性加成",
    "R6": "三方投票",
}


# ========================================================================
# 数据结构
# ========================================================================

@dataclass
class PendingRecord:
    """待验证记录"""
    id: str
    timestamp: str
    symbol: str
    rule_id: str
    rule_name: str
    trigger_value: Dict
    prediction: str  # "UP" / "DOWN" / "HOLD"
    entry_price: float
    verify_after_bars: int
    bars_seen: int  # 已经过的K线数
    verified: bool


@dataclass
class VerifiedRecord:
    """已验证记录"""
    id: str
    timestamp: str
    symbol: str
    rule_id: str
    rule_name: str
    prediction: str
    entry_price: float
    exit_price: float
    actual_change: float  # 百分比
    outcome: str  # CORRECT / WRONG / NEUTRAL
    verified_at: str


@dataclass
class RuleStats:
    """规则统计"""
    triggers: int = 0
    correct: int = 0
    wrong: int = 0
    neutral: int = 0
    accuracy: float = 0.0

    def update_accuracy(self):
        """更新准确率"""
        total = self.correct + self.wrong
        if total > 0:
            self.accuracy = self.correct / total
        else:
            self.accuracy = 0.0


# ========================================================================
# L1规则追踪器
# ========================================================================

class L1RuleTracker:
    """L1规则效果追踪器"""

    def __init__(self):
        self.pending: List[Dict] = []
        self.verified: List[Dict] = []
        self.stats: Dict[str, Dict] = {}
        self.today_triggers: Dict[str, int] = {}  # 今日触发计数
        self._load()

    def _load(self):
        """加载追踪数据"""
        if os.path.exists(TRACKER_FILE):
            try:
                with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.pending = data.get("pending", [])
                    self.verified = data.get("verified", [])
                    self.stats = data.get("stats", {})
            except Exception as e:
                print(f"[L1Tracker] 加载失败: {e}")
                self._init_empty()
        else:
            self._init_empty()

    def _init_empty(self):
        """初始化空数据"""
        self.pending = []
        self.verified = []
        self.stats = {
            rule_id: {"triggers": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0.0}
            for rule_id in RULE_NAMES.keys()
        }

    def _save(self):
        """保存追踪数据"""
        try:
            os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
            data = {
                "pending": self.pending,
                "verified": self.verified[-500:],  # 只保留最近500条已验证
                "stats": self.stats,
                "last_updated": datetime.now().isoformat(),
            }
            with open(TRACKER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[L1Tracker] 保存失败: {e}")

    # ========================================================================
    # 记录规则触发
    # ========================================================================

    def record(
        self,
        rule_id: str,
        symbol: str,
        trigger_value: Dict,
        prediction: str,
        entry_price: float,
    ):
        """
        记录规则触发

        Args:
            rule_id: 规则ID (R1-R6)
            symbol: 品种代码
            trigger_value: 触发时的值 (用于后续分析)
            prediction: 预测方向 "UP" / "DOWN" / "HOLD"
            entry_price: 入场价格
        """
        if rule_id not in RULE_NAMES:
            return

        now = datetime.now()
        record_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{symbol}_{rule_id}"

        record = {
            "id": record_id,
            "timestamp": now.isoformat(),
            "symbol": symbol,
            "rule_id": rule_id,
            "rule_name": RULE_NAMES[rule_id],
            "trigger_value": trigger_value,
            "prediction": prediction,
            "entry_price": entry_price,
            "verify_after_bars": VERIFY_AFTER_BARS,
            "bars_seen": 0,
            "verified": False,
        }

        self.pending.append(record)

        # 更新统计
        if rule_id not in self.stats:
            self.stats[rule_id] = {"triggers": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy": 0.0}
        self.stats[rule_id]["triggers"] += 1

        # 今日触发计数
        today = now.strftime("%Y-%m-%d")
        if rule_id not in self.today_triggers:
            self.today_triggers[rule_id] = 0
        self.today_triggers[rule_id] += 1

        self._save()

        print(f"[L1Tracker] 记录 {rule_id} {RULE_NAMES[rule_id]}: {symbol} 预测={prediction}")

    # ========================================================================
    # 验证待处理记录
    # ========================================================================

    def verify_pending(self, current_prices: Dict[str, float]):
        """
        验证待处理的记录

        Args:
            current_prices: 当前价格字典 {symbol: price}
        """
        if not self.pending:
            return

        now = datetime.now()
        still_pending = []

        for record in self.pending:
            symbol = record["symbol"]

            # 增加已过K线计数
            record["bars_seen"] = record.get("bars_seen", 0) + 1

            # 检查是否到验证时间
            if record["bars_seen"] < record["verify_after_bars"]:
                still_pending.append(record)
                continue

            # 获取当前价格
            current_price = current_prices.get(symbol)
            if current_price is None:
                # 没有价格数据，继续等待
                still_pending.append(record)
                continue

            # 计算价格变化
            entry_price = record["entry_price"]
            if entry_price <= 0:
                still_pending.append(record)
                continue

            actual_change = (current_price - entry_price) / entry_price

            # 判断结果
            prediction = record["prediction"]
            outcome = self._evaluate_outcome(prediction, actual_change)

            # 创建已验证记录
            verified_record = {
                "id": record["id"],
                "timestamp": record["timestamp"],
                "symbol": symbol,
                "rule_id": record["rule_id"],
                "rule_name": record["rule_name"],
                "prediction": prediction,
                "entry_price": entry_price,
                "exit_price": current_price,
                "actual_change": round(actual_change * 100, 2),  # 百分比
                "outcome": outcome,
                "verified_at": now.isoformat(),
            }

            self.verified.append(verified_record)

            # 更新统计
            rule_id = record["rule_id"]
            if outcome == "CORRECT":
                self.stats[rule_id]["correct"] += 1
            elif outcome == "WRONG":
                self.stats[rule_id]["wrong"] += 1
            else:
                self.stats[rule_id]["neutral"] += 1

            # 更新准确率
            stats = self.stats[rule_id]
            total = stats["correct"] + stats["wrong"]
            if total > 0:
                stats["accuracy"] = round(stats["correct"] / total, 3)

            print(f"[L1Tracker] 验证 {rule_id}: {symbol} 预测={prediction} 实际={actual_change*100:.2f}% → {outcome}")

        self.pending = still_pending
        self._save()

    def _evaluate_outcome(self, prediction: str, actual_change: float) -> str:
        """
        评估预测结果

        Args:
            prediction: 预测方向 "UP" / "DOWN" / "HOLD"
            actual_change: 实际价格变化 (小数形式)

        Returns:
            "CORRECT" / "WRONG" / "NEUTRAL"
        """
        threshold = PRICE_CHANGE_THRESHOLD  # 0.5%

        if prediction == "UP":
            if actual_change > threshold:
                return "CORRECT"
            elif actual_change < -threshold:
                return "WRONG"
            else:
                return "NEUTRAL"

        elif prediction == "DOWN":
            if actual_change < -threshold:
                return "CORRECT"
            elif actual_change > threshold:
                return "WRONG"
            else:
                return "NEUTRAL"

        else:  # HOLD
            if abs(actual_change) <= threshold:
                return "CORRECT"
            else:
                return "NEUTRAL"  # HOLD预测变动不算错

    # ========================================================================
    # 日报生成
    # ========================================================================

    def generate_daily_summary(self, date: str = None) -> str:
        """
        生成每日汇总报告

        Args:
            date: 日期 (默认今天)

        Returns:
            报告文本
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # 过滤今日验证的记录
        today_verified = [
            r for r in self.verified
            if r.get("verified_at", "").startswith(date)
        ]

        # 按规则统计今日数据
        today_stats = {}
        for rule_id in RULE_NAMES.keys():
            today_stats[rule_id] = {"triggers": 0, "correct": 0, "wrong": 0, "neutral": 0}

        for record in today_verified:
            rule_id = record["rule_id"]
            outcome = record["outcome"]
            today_stats[rule_id]["triggers"] += 1
            if outcome == "CORRECT":
                today_stats[rule_id]["correct"] += 1
            elif outcome == "WRONG":
                today_stats[rule_id]["wrong"] += 1
            else:
                today_stats[rule_id]["neutral"] += 1

        # 生成报告
        lines = []
        lines.append("=" * 50)
        lines.append(f"L1规则效果日报 - {date}")
        lines.append("=" * 50)
        lines.append("")
        lines.append("今日规则验证统计:")
        lines.append("-" * 50)
        lines.append(f"{'规则':<20} {'验证数':>8} {'正确':>8} {'错误':>8} {'准确率':>10}")
        lines.append("-" * 50)

        for rule_id, name in RULE_NAMES.items():
            s = today_stats[rule_id]
            total = s["correct"] + s["wrong"]
            acc = f"{s['correct']/total*100:.1f}%" if total > 0 else "N/A"
            lines.append(f"{rule_id} {name:<14} {s['triggers']:>8} {s['correct']:>8} {s['wrong']:>8} {acc:>10}")

        lines.append("-" * 50)
        lines.append("")

        # 累计统计
        lines.append("累计统计 (全部历史):")
        lines.append("-" * 50)
        lines.append(f"{'规则':<20} {'触发数':>8} {'正确':>8} {'错误':>8} {'准确率':>10}")
        lines.append("-" * 50)

        for rule_id, name in RULE_NAMES.items():
            s = self.stats.get(rule_id, {"triggers": 0, "correct": 0, "wrong": 0, "accuracy": 0})
            acc = f"{s.get('accuracy', 0)*100:.1f}%"
            lines.append(f"{rule_id} {name:<14} {s.get('triggers', 0):>8} {s.get('correct', 0):>8} {s.get('wrong', 0):>8} {acc:>10}")

        lines.append("-" * 50)
        lines.append("")

        # 关键发现
        lines.append("关键发现:")

        # 找出准确率最高的规则
        best_rule = None
        best_acc = 0
        for rule_id, s in self.stats.items():
            if s.get("correct", 0) + s.get("wrong", 0) >= 5:  # 至少5次验证
                if s.get("accuracy", 0) > best_acc:
                    best_acc = s["accuracy"]
                    best_rule = rule_id

        if best_rule:
            lines.append(f"- {best_rule} {RULE_NAMES[best_rule]} 准确率最高: {best_acc*100:.1f}%")

        # 找出准确率最低的规则
        worst_rule = None
        worst_acc = 1.0
        for rule_id, s in self.stats.items():
            if s.get("correct", 0) + s.get("wrong", 0) >= 5:
                if s.get("accuracy", 0) < worst_acc:
                    worst_acc = s["accuracy"]
                    worst_rule = rule_id

        if worst_rule and worst_acc < 0.6:
            lines.append(f"- {worst_rule} {RULE_NAMES[worst_rule]} 需要关注: {worst_acc*100:.1f}%")

        # 待验证数量
        lines.append(f"- 当前待验证记录: {len(self.pending)} 条")

        lines.append("")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 50)

        report = "\n".join(lines)

        # 保存到文件
        try:
            with open(DAILY_SUMMARY_FILE, "w", encoding="utf-8") as f:
                f.write(report)
        except Exception as e:
            print(f"[L1Tracker] 保存日报失败: {e}")

        return report

    def print_startup_summary(self):
        """程序启动时打印昨日汇总"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        print("\n" + "=" * 50)
        print("L1规则效果追踪器 v1.0")
        print("=" * 50)
        print(f"待验证记录: {len(self.pending)} 条")
        print(f"已验证记录: {len(self.verified)} 条")
        print("")
        print("累计规则准确率:")
        print("-" * 40)

        for rule_id, name in RULE_NAMES.items():
            s = self.stats.get(rule_id, {})
            total = s.get("correct", 0) + s.get("wrong", 0)
            if total > 0:
                acc = f"{s.get('accuracy', 0)*100:.1f}%"
                print(f"  {rule_id} {name:<14}: {acc} ({total}次验证)")
            else:
                print(f"  {rule_id} {name:<14}: 无数据")

        print("-" * 40)
        print("")

    # ========================================================================
    # 便捷方法
    # ========================================================================

    def record_multi_slope(self, symbol: str, weighted_slope: float, direction: str, consistency: float, entry_price: float):
        """记录R1多周期斜率触发"""
        prediction = "UP" if direction in ["UP", "STRONG_UP"] else ("DOWN" if direction in ["DOWN", "STRONG_DOWN"] else "HOLD")
        self.record(
            rule_id="R1",
            symbol=symbol,
            trigger_value={"weighted_slope": weighted_slope, "direction": direction, "consistency": consistency},
            prediction=prediction,
            entry_price=entry_price,
        )

    def record_structure(self, symbol: str, structure: str, hh: int, hl: int, ll: int, lh: int, entry_price: float):
        """记录R2趋势结构触发"""
        prediction = "UP" if structure == "UPTREND" else ("DOWN" if structure == "DOWNTREND" else "HOLD")
        self.record(
            rule_id="R2",
            symbol=symbol,
            trigger_value={"structure": structure, "hh": hh, "hl": hl, "ll": ll, "lh": lh},
            prediction=prediction,
            entry_price=entry_price,
        )

    def record_choppiness(self, symbol: str, chop_value: float, regime: str, entry_price: float):
        """记录R3动态Choppiness触发"""
        prediction = "HOLD" if regime in ["RANGING", "CHOPPY"] else "UP"  # 简化
        self.record(
            rule_id="R3",
            symbol=symbol,
            trigger_value={"chop_value": chop_value, "regime": regime},
            prediction=prediction,
            entry_price=entry_price,
        )

    def record_big_trend_protection(self, symbol: str, trend_x4: str, pos_ratio: float, original_signal: str, entry_price: float):
        """记录R4大周期保护触发"""
        # 大周期保护触发时，预测是保护方向的反向
        if original_signal == "SELL" and trend_x4.lower() == "up":
            prediction = "UP"  # 阻止卖出，预测会涨
        elif original_signal == "BUY" and trend_x4.lower() == "down":
            prediction = "DOWN"  # 阻止买入，预测会跌
        else:
            prediction = "HOLD"

        self.record(
            rule_id="R4",
            symbol=symbol,
            trigger_value={"trend_x4": trend_x4, "pos_ratio": pos_ratio, "blocked_signal": original_signal},
            prediction=prediction,
            entry_price=entry_price,
        )

    def record_consistency_boost(self, symbol: str, consistency: float, boosted_direction: str, entry_price: float):
        """记录R5一致性加成触发"""
        prediction = boosted_direction
        self.record(
            rule_id="R5",
            symbol=symbol,
            trigger_value={"consistency": consistency, "boosted_direction": boosted_direction},
            prediction=prediction,
            entry_price=entry_price,
        )

    def record_voting(self, symbol: str, ai_vote: str, human_vote: str, tech_vote: str, final_regime: str, final_direction: str, entry_price: float):
        """记录R6三方投票触发"""
        prediction = final_direction
        self.record(
            rule_id="R6",
            symbol=symbol,
            trigger_value={"ai": ai_vote, "human": human_vote, "tech": tech_vote, "final": f"{final_regime}/{final_direction}"},
            prediction=prediction,
            entry_price=entry_price,
        )


# ========================================================================
# 全局实例
# ========================================================================

_tracker_instance: Optional[L1RuleTracker] = None


def get_tracker() -> L1RuleTracker:
    """获取全局追踪器实例"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = L1RuleTracker()
    return _tracker_instance


# ========================================================================
# 测试
# ========================================================================

if __name__ == "__main__":
    print("L1 Rule Tracker v1.0 - 测试")
    print("=" * 50)

    tracker = get_tracker()
    tracker.print_startup_summary()

    # 模拟记录
    print("\n模拟记录规则触发...")
    tracker.record_multi_slope("BTCUSDC", 0.08, "UP", 0.9, 94500)
    tracker.record_structure("ETHUSDC", "UPTREND", 2, 2, 0, 0, 3200)
    tracker.record_big_trend_protection("SOLUSDC", "up", 0.75, "SELL", 136)

    # 模拟验证
    print("\n模拟验证...")
    current_prices = {
        "BTCUSDC": 95000,  # 涨了
        "ETHUSDC": 3250,   # 涨了
        "SOLUSDC": 138,    # 涨了
    }

    # 手动设置bars_seen以便立即验证
    for record in tracker.pending:
        record["bars_seen"] = 10

    tracker.verify_pending(current_prices)

    # 生成日报
    print("\n生成日报...")
    report = tracker.generate_daily_summary()
    print(report)
