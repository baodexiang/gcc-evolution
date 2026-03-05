"""
Module E: 组合相关性监控 (SYS-019)
v1.0: Phase 1 观察模式 (只记录, 不拦截)

基于OHLCV历史收益率计算rolling correlation matrix。
识别高相关集群(rho>0.7), 记录集中度风险。

接口:
- update_correlation(symbol, returns) → None       # 更新品种收益率
- get_concentration_risk() → dict                   # 获取集中度风险状态
- check_correlation_limit(symbol, action) → tuple   # 检查是否允许新建仓
"""
import json
import os
import time
import logging
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")
CORRELATION_STATE_FILE = "state/correlation_state.json"

# 配置
LOOKBACK_DAYS = 20       # 20日rolling窗口
CORR_THRESHOLD = 0.7     # 高相关阈值
CLUSTER_MAX_PCT = 0.60   # 单集群最大持仓占比60%
ENABLED = False           # Phase 1: 仅记录


class CorrelationMonitor:

    def __init__(self):
        self._returns = {}      # symbol → [daily_returns]
        self._positions = {}    # symbol → tier (from external)
        self._clusters = []     # [(symbols, avg_corr)]
        self._last_update = 0

    def update_returns(self, symbol: str, daily_returns: list) -> None:
        """更新品种日收益率序列(最近20个交易日)"""
        self._returns[symbol] = daily_returns[-LOOKBACK_DAYS:]

    def set_positions(self, positions: dict) -> None:
        """设置当前持仓(symbol → tier)"""
        self._positions = positions

    def compute_correlation_matrix(self) -> dict:
        """计算品种间相关系数矩阵"""
        symbols = sorted(self._returns.keys())
        if len(symbols) < 2:
            return {}

        matrix = {}
        for i, s1 in enumerate(symbols):
            for j, s2 in enumerate(symbols):
                if i >= j:
                    continue
                r1 = self._returns.get(s1, [])
                r2 = self._returns.get(s2, [])
                min_len = min(len(r1), len(r2))
                if min_len < 5:
                    continue
                r1 = r1[-min_len:]
                r2 = r2[-min_len:]
                corr = self._pearson(r1, r2)
                pair = f"{s1}|{s2}"
                matrix[pair] = round(corr, 3)

        return matrix

    def find_clusters(self, matrix: dict) -> list:
        """找出高相关集群 (rho > threshold)"""
        # 构建邻接图
        adj = defaultdict(set)
        for pair, corr in matrix.items():
            if corr >= CORR_THRESHOLD:
                s1, s2 = pair.split("|")
                adj[s1].add(s2)
                adj[s2].add(s1)

        # BFS找连通分量
        visited = set()
        clusters = []
        for sym in adj:
            if sym in visited:
                continue
            cluster = set()
            queue = [sym]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                cluster.add(node)
                for neighbor in adj[node]:
                    if neighbor not in visited:
                        queue.append(neighbor)
            if len(cluster) >= 2:
                # 计算集群平均相关度
                corrs = []
                for pair, c in matrix.items():
                    s1, s2 = pair.split("|")
                    if s1 in cluster and s2 in cluster:
                        corrs.append(c)
                avg_corr = sum(corrs) / len(corrs) if corrs else 0
                clusters.append((sorted(cluster), round(avg_corr, 3)))

        self._clusters = clusters
        return clusters

    def get_concentration_risk(self) -> dict:
        """计算各集群的持仓集中度"""
        total_positions = sum(1 for t in self._positions.values() if t > 0)
        if total_positions == 0:
            return {"clusters": [], "max_concentration": 0, "risk": "LOW"}

        result = []
        max_pct = 0
        for symbols, avg_corr in self._clusters:
            cluster_positions = sum(1 for s in symbols if self._positions.get(s, 0) > 0)
            pct = cluster_positions / total_positions if total_positions > 0 else 0
            max_pct = max(max_pct, pct)
            result.append({
                "symbols": symbols,
                "avg_corr": avg_corr,
                "positions": cluster_positions,
                "concentration": round(pct, 3),
            })

        risk = "HIGH" if max_pct > CLUSTER_MAX_PCT else "MEDIUM" if max_pct > 0.4 else "LOW"
        return {
            "clusters": result,
            "max_concentration": round(max_pct, 3),
            "risk": risk,
            "total_positions": total_positions,
        }

    def check_correlation_limit(self, symbol: str, action: str) -> tuple:
        """
        检查新建仓是否超过集中度限制
        Returns: (allowed: bool, reason: str)
        """
        if not ENABLED:
            return (True, "")

        if action != "BUY":
            return (True, "")

        conc = self.get_concentration_risk()
        for cluster in conc.get("clusters", []):
            if symbol in cluster["symbols"] and cluster["concentration"] >= CLUSTER_MAX_PCT:
                return (False, f"相关性风控: {symbol}所在集群{cluster['symbols']}集中度"
                        f"{cluster['concentration']:.0%}>{CLUSTER_MAX_PCT:.0%}")

        return (True, "")

    def save_state(self) -> None:
        """保存状态到JSON"""
        matrix = self.compute_correlation_matrix()
        clusters = self.find_clusters(matrix)
        conc = self.get_concentration_risk()
        state = {
            "updated_at": datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "matrix_size": len(matrix),
            "high_corr_pairs": {k: v for k, v in matrix.items() if v >= CORR_THRESHOLD},
            "clusters": conc.get("clusters", []),
            "max_concentration": conc.get("max_concentration", 0),
            "risk_level": conc.get("risk", "LOW"),
            "enabled": ENABLED,
        }
        try:
            with open(CORRELATION_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存correlation state失败: {e}")

        tag = "[生效]" if ENABLED else "[观察]"
        high_pairs = len(state["high_corr_pairs"])
        print(f"[CORR_MONITOR] {tag} matrix={len(matrix)}对 高相关={high_pairs}对 "
              f"集群={len(clusters)}个 风险={conc.get('risk', 'N/A')}")

    @staticmethod
    def _pearson(x: list, y: list) -> float:
        n = len(x)
        if n < 2:
            return 0.0
        mx = sum(x) / n
        my = sum(y) / n
        sx = sum((xi - mx) ** 2 for xi in x) ** 0.5
        sy = sum((yi - my) ** 2 for yi in y) ** 0.5
        if sx == 0 or sy == 0:
            return 0.0
        cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
        return cov / (sx * sy)
