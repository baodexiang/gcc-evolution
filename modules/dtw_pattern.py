"""
Module F: DTW历史模式匹配 (SYS-013)
v1.0: Phase 1 观察模式 (只记录, 不拦截)

使用Dynamic Time Warping算法匹配当前K线形态与历史成功/失败模式。
复杂度高, ROI需验证。

接口:
- match_pattern(current_bars) → dict     # 匹配最相似历史模式
- record_outcome(pattern_id, success)    # 记录模式结局
- get_pattern_stats() → dict             # 获取模式统计
"""
import json
import os
import math
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")
DTW_STATE_FILE = "state/dtw_patterns.json"

# 配置
PATTERN_WINDOW = 20       # 用最近20根K线做匹配
MAX_PATTERNS = 500        # 最多保留500个历史模式
DTW_MATCH_THRESHOLD = 0.15  # 归一化DTW距离阈值
ENABLED = False           # Phase 1: 仅记录


def _normalize_series(series: list) -> list:
    """Min-Max归一化到[0,1]"""
    if not series or len(series) < 2:
        return series
    mn = min(series)
    mx = max(series)
    rng = mx - mn
    if rng == 0:
        return [0.5] * len(series)
    return [(v - mn) / rng for v in series]


def _dtw_distance(s1: list, s2: list) -> float:
    """
    基础DTW距离计算 (O(n*m))
    使用归一化序列, 返回归一化距离
    """
    n, m = len(s1), len(s2)
    if n == 0 or m == 0:
        return float('inf')

    # DTW矩阵
    dtw = [[float('inf')] * (m + 1) for _ in range(n + 1)]
    dtw[0][0] = 0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s1[i-1] - s2[j-1])
            dtw[i][j] = cost + min(dtw[i-1][j], dtw[i][j-1], dtw[i-1][j-1])

    # 归一化
    return dtw[n][m] / max(n, m)


class DTWPatternMatcher:

    def __init__(self):
        self._patterns = []   # [{"id": int, "series": list, "outcome": str, "symbol": str, "ts": str}]
        self._load_state()

    def _load_state(self):
        if os.path.exists(DTW_STATE_FILE):
            try:
                with open(DTW_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._patterns = data.get("patterns", [])
            except Exception:
                self._patterns = []

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(DTW_STATE_FILE), exist_ok=True)
            with open(DTW_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"patterns": self._patterns[-MAX_PATTERNS:],
                           "updated_at": datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")},
                          f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"DTW state保存失败: {e}")

    def extract_series(self, bars: list) -> list:
        """从K线提取收盘价序列并归一化"""
        if not bars:
            return []
        closes = [b.get("close", 0) for b in bars[-PATTERN_WINDOW:]]
        return _normalize_series(closes)

    def match_pattern(self, bars: list, symbol: str = "") -> dict:
        """
        匹配当前形态与历史模式
        Returns: {"matched": bool, "distance": float, "best_pattern": dict or None,
                  "win_count": int, "lose_count": int, "win_rate": float}
        """
        current = self.extract_series(bars)
        if len(current) < 10:
            return {"matched": False, "distance": 1.0, "best_pattern": None,
                    "win_count": 0, "lose_count": 0, "win_rate": 0.5}

        best_dist = float('inf')
        best_pattern = None
        win_count = 0
        lose_count = 0

        for pat in self._patterns:
            pat_series = pat.get("series", [])
            if len(pat_series) < 10:
                continue
            dist = _dtw_distance(current, pat_series)
            if dist < DTW_MATCH_THRESHOLD:
                if pat.get("outcome") == "WIN":
                    win_count += 1
                elif pat.get("outcome") == "LOSE":
                    lose_count += 1
            if dist < best_dist:
                best_dist = dist
                best_pattern = pat

        total = win_count + lose_count
        win_rate = win_count / total if total > 0 else 0.5

        matched = best_dist < DTW_MATCH_THRESHOLD
        if matched:
            print(f"[DTW] {symbol} 匹配: dist={best_dist:.4f} "
                  f"相似模式{total}个(胜{win_count}/负{lose_count}, WR={win_rate:.0%})")

        return {
            "matched": matched,
            "distance": round(best_dist, 4),
            "best_pattern": {"id": best_pattern.get("id"), "outcome": best_pattern.get("outcome")} if best_pattern else None,
            "win_count": win_count,
            "lose_count": lose_count,
            "win_rate": round(win_rate, 3),
        }

    def record_pattern(self, bars: list, outcome: str, symbol: str = "") -> None:
        """记录一个新模式 (BUY/SELL后标注结果WIN/LOSE)"""
        series = self.extract_series(bars)
        if len(series) < 10:
            return
        pid = len(self._patterns) + 1
        self._patterns.append({
            "id": pid,
            "series": [round(v, 4) for v in series],
            "outcome": outcome,
            "symbol": symbol,
            "ts": datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        })
        # 保留最近MAX_PATTERNS个
        if len(self._patterns) > MAX_PATTERNS:
            self._patterns = self._patterns[-MAX_PATTERNS:]
        self._save_state()

    def get_pattern_stats(self) -> dict:
        """获取模式库统计"""
        total = len(self._patterns)
        wins = sum(1 for p in self._patterns if p.get("outcome") == "WIN")
        loses = sum(1 for p in self._patterns if p.get("outcome") == "LOSE")
        return {
            "total_patterns": total,
            "wins": wins,
            "loses": loses,
            "win_rate": round(wins / (wins + loses), 3) if (wins + loses) > 0 else 0,
            "enabled": ENABLED,
        }
