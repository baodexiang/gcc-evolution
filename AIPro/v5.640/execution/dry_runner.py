"""
DRY_RUN 执行器
==============
虚拟执行模块，只记录信号不执行实际交易。
"""

import json
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class DryRunner:
    """虚拟执行器 - 只记录不交易"""

    def __init__(self, log_dir: str = None):
        """
        初始化虚拟执行器

        Args:
            log_dir: 日志目录路径
        """
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.history_file = self.log_dir / "signal_history.json"
        self.history: List[Dict] = self._load_history()

        # 模拟持仓
        self.positions: Dict[str, Dict] = {}

    def execute_signal(
        self,
        symbol: str,
        action: str,
        price: float,
        confidence: float = 0.0,
        reason: str = "",
        analysis: Dict = None,
        timeframe: str = "30m"
    ) -> Dict:
        """
        执行信号 (仅记录)

        Args:
            symbol: 标的代码
            action: 动作 (BUY/SELL/HOLD)
            price: 当前价格
            confidence: 置信度
            reason: 原因
            analysis: 完整分析结果
            timeframe: 时间周期

        Returns:
            执行结果
        """
        timestamp = datetime.now()

        # 创建信号记录
        signal_record = {
            "id": f"{symbol}_{timestamp.strftime('%Y%m%d%H%M%S')}",
            "timestamp": timestamp.isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "action": action,
            "price": price,
            "confidence": confidence,
            "reason": reason,
            "mode": "DRY_RUN",
            "executed": False,
            "analysis_summary": self._extract_summary(analysis) if analysis else {}
        }

        # 计算模拟收益
        if action == "BUY":
            self.positions[symbol] = {
                "entry_price": price,
                "entry_time": timestamp.isoformat(),
                "quantity": 1  # 模拟1单位
            }
            signal_record["position_action"] = "OPENED"

        elif action == "SELL" and symbol in self.positions:
            position = self.positions.pop(symbol)
            entry_price = position["entry_price"]
            pnl = (price - entry_price) / entry_price * 100
            signal_record["position_action"] = "CLOSED"
            signal_record["pnl_percent"] = round(pnl, 2)
            signal_record["entry_price"] = entry_price

        # 保存到历史
        self.history.append(signal_record)
        self._save_history()

        logger.info(
            f"[DRY_RUN] {symbol} {action} @ ${price:.2f} "
            f"(置信度: {confidence*100:.0f}%, 原因: {reason})"
        )

        return {
            "status": "logged",
            "executed": False,
            "record": signal_record
        }

    def _extract_summary(self, analysis: Dict) -> Dict:
        """提取分析摘要"""
        if not analysis:
            return {}

        return {
            "l1_trend": analysis.get("l1", {}).get("trend"),
            "l1_strength": analysis.get("l1", {}).get("strength"),
            "l1_adx": analysis.get("l1", {}).get("adx"),
            "l2_signal": analysis.get("l2", {}).get("signal"),
            "l2_score": analysis.get("l2", {}).get("score"),
            "l2_rsi": analysis.get("l2", {}).get("rsi"),
        }

    def _load_history(self) -> List[Dict]:
        """加载历史记录"""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load history: {e}")
        return []

    def _save_history(self):
        """保存历史记录"""
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def get_history(
        self,
        symbol: str = None,
        action: str = None,
        timeframe: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        获取信号历史

        Args:
            symbol: 筛选标的
            action: 筛选动作
            timeframe: 筛选时间周期
            limit: 返回条数

        Returns:
            信号历史列表
        """
        filtered = self.history

        if symbol:
            filtered = [r for r in filtered if r["symbol"] == symbol]

        if action:
            filtered = [r for r in filtered if r["action"] == action]

        if timeframe:
            filtered = [r for r in filtered if r.get("timeframe") == timeframe]

        return filtered[-limit:]

    def get_statistics(self) -> Dict:
        """
        获取统计数据

        Returns:
            统计信息
        """
        total = len(self.history)
        buys = len([r for r in self.history if r["action"] == "BUY"])
        sells = len([r for r in self.history if r["action"] == "SELL"])
        holds = len([r for r in self.history if r["action"] == "HOLD"])

        # 计算已平仓交易的胜率
        closed_trades = [r for r in self.history if "pnl_percent" in r]
        wins = len([t for t in closed_trades if t["pnl_percent"] > 0])
        losses = len([t for t in closed_trades if t["pnl_percent"] < 0])

        total_pnl = sum(t.get("pnl_percent", 0) for t in closed_trades)

        # v3.496: 最近10次信号统计 (changed from 5)
        recent_5 = self.history[-10:] if len(self.history) >= 10 else self.history
        recent_5_count = len(recent_5)
        recent_5_buys = len([r for r in recent_5 if r["action"] == "BUY"])
        recent_5_holds = len([r for r in recent_5 if r["action"] == "HOLD"])
        recent_5_sells = len([r for r in recent_5 if r["action"] == "SELL"])

        # v3.496: 最近10次平均确信度 (changed from 5)
        recent_5_confidences = [r.get("confidence", 0) for r in recent_5]
        avg_confidence = sum(recent_5_confidences) / len(recent_5_confidences) * 100 if recent_5_confidences else 0

        return {
            "total_signals": total,
            "buy_signals": buys,
            "sell_signals": sells,
            "hold_signals": holds,
            "closed_trades": len(closed_trades),
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": wins / len(closed_trades) * 100 if closed_trades else 0,
            "total_pnl_percent": round(total_pnl, 2),
            "open_positions": len(self.positions),
            # v3.496: 最近10次统计 (changed from 5)
            "recent_5_count": recent_5_count,
            "recent_5_buys": recent_5_buys,
            "recent_5_holds": recent_5_holds,
            "recent_5_sells": recent_5_sells,
            "avg_confidence": round(avg_confidence, 1),
        }

    def get_open_positions(self) -> Dict[str, Dict]:
        """获取当前持仓"""
        return self.positions.copy()

    def clear_history(self):
        """清空历史记录"""
        self.history = []
        self.positions = {}
        self._save_history()
        logger.info("History cleared")
