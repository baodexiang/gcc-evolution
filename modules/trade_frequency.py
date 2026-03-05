"""
Module B: 交易频率控制模块 — 根据预选结果限制全局交易次数
v1.0: Phase 2 先记录后拦截

依赖:
- state/stock_selection.json (Module A输出)

输出:
- state/trade_frequency.json: 当日模式+配额+使用情况
"""

import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

SELECTION_STATE_FILE = "state/stock_selection.json"
FREQUENCY_STATE_FILE = "state/trade_frequency.json"

# 模式配置: (全局上限, 单品种上限)
MODE_CONFIG = {
    "AGGRESSIVE": {"global_limit": 12, "per_symbol_limit": 3},
    "NORMAL":     {"global_limit": 8,  "per_symbol_limit": 2},
    "CONSERVATIVE": {"global_limit": 4, "per_symbol_limit": 1},
}


def _safe_json_read(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[频率控制] 读取 {filepath} 失败: {e}")
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
        logger.error(f"[频率控制] 写入 {filepath} 失败: {e}")
        return False


class TradeFrequencyController:
    """
    交易频率控制器

    根据Module A预选结果决定交易模式:
    - AGGRESSIVE: A/B品种占比>=60% → 全局12次, 单品种3次
    - NORMAL:     A/B品种占比40-60% → 全局8次, 单品种2次
    - CONSERVATIVE: A/B品种占比<40% → 全局4次, 单品种1次

    Phase 2: 先记录模式运行, 验证合理后再开启拦截
    """

    def __init__(self, enforce=False):
        """
        Args:
            enforce: True=拦截模式, False=记录模式(Phase 2初期)
        """
        self.state_file = FREQUENCY_STATE_FILE
        self.enforce = enforce
        self._state = None
        self._load_or_reset()

    def _load_or_reset(self):
        """加载状态, 新一天则重置"""
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
        data = _safe_json_read(self.state_file)

        if data and data.get("date") == today:
            self._state = data
        else:
            # 新一天, 重新计算模式
            self._state = {
                "date": today,
                "mode": "NORMAL",
                "global_limit": 8,
                "per_symbol_limit": 2,
                "global_used": 0,
                "per_symbol_used": {},
                "trades": [],
                "updated_at": datetime.now(NY_TZ).isoformat()
            }
            self._compute_mode()
            self._save()

    def _compute_mode(self):
        """根据预选结果计算当日模式"""
        selection = _safe_json_read(SELECTION_STATE_FILE)
        if not selection or not selection.get("scores"):
            logger.info("[频率控制] 无预选数据, 使用默认NORMAL模式")
            return

        scores = selection["scores"]
        total_count = len(scores)
        if total_count == 0:
            return

        ab_count = sum(1 for s in scores.values() if s.get("tier") in ("A", "B"))
        ab_ratio = ab_count / total_count

        if ab_ratio >= 0.6:
            mode = "AGGRESSIVE"
        elif ab_ratio >= 0.4:
            mode = "NORMAL"
        else:
            mode = "CONSERVATIVE"

        config = MODE_CONFIG[mode]
        self._state["mode"] = mode
        self._state["global_limit"] = config["global_limit"]
        self._state["per_symbol_limit"] = config["per_symbol_limit"]

        logger.info(f"[频率控制] 模式={mode} (A/B比例={ab_ratio:.0%}), "
                    f"全局上限={config['global_limit']}, 单品种={config['per_symbol_limit']}")

    def _save(self):
        """保存状态"""
        self._state["updated_at"] = datetime.now(NY_TZ).isoformat()
        _safe_json_write(self.state_file, self._state)

    def compute_daily_budget(self) -> dict:
        """返回当日模式和配额信息"""
        self._load_or_reset()
        return {
            "mode": self._state["mode"],
            "global_limit": self._state["global_limit"],
            "global_used": self._state["global_used"],
            "per_symbol_limit": self._state["per_symbol_limit"],
        }

    def can_trade(self, symbol) -> tuple:
        """
        检查是否允许交易

        Args:
            symbol: 品种代码

        Returns:
            (allowed: bool, reason: str)
        """
        self._load_or_reset()

        global_used = self._state.get("global_used", 0)
        global_limit = self._state.get("global_limit", 8)
        per_symbol_used = self._state.get("per_symbol_used", {}).get(symbol, 0)
        per_symbol_limit = self._state.get("per_symbol_limit", 2)

        # 全局检查
        if global_used >= global_limit:
            msg = f"全局配额已满 ({global_used}/{global_limit})"
            if self.enforce:
                logger.info(f"[频率控制] {symbol} 拦截: {msg}")
                return (False, msg)
            else:
                logger.info(f"[频率控制] {symbol} {msg} — 记录模式,不拦截")
                return (True, f"[记录] {msg}")

        # 单品种检查
        if per_symbol_used >= per_symbol_limit:
            msg = f"单品种配额已满 ({per_symbol_used}/{per_symbol_limit})"
            if self.enforce:
                logger.info(f"[频率控制] {symbol} 拦截: {msg}")
                return (False, msg)
            else:
                logger.info(f"[频率控制] {symbol} {msg} — 记录模式,不拦截")
                return (True, f"[记录] {msg}")

        return (True, f"可交易 (全局{global_used}/{global_limit}, {symbol}={per_symbol_used}/{per_symbol_limit})")

    def record_trade(self, symbol, action="", source=""):
        """
        记录一次交易

        Args:
            symbol: 品种代码
            action: "BUY" or "SELL"
            source: 信号来源 (e.g., "P0-Tracking", "SuperTrend")
        """
        self._load_or_reset()

        self._state["global_used"] = self._state.get("global_used", 0) + 1

        per_symbol = self._state.get("per_symbol_used", {})
        per_symbol[symbol] = per_symbol.get(symbol, 0) + 1
        self._state["per_symbol_used"] = per_symbol

        # 记录交易详情
        trades = self._state.get("trades", [])
        trades.append({
            "symbol": symbol,
            "action": action,
            "source": source,
            "time": datetime.now(NY_TZ).isoformat()
        })
        self._state["trades"] = trades

        self._save()
        logger.info(f"[频率控制] 记录交易: {symbol} {action} ({source}), "
                    f"全局={self._state['global_used']}/{self._state['global_limit']}")
