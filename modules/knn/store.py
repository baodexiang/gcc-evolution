"""
modules/knn/store.py — L2 记忆存储
===================================
PluginKNNDB历史特征库: 纯数据I/O(加载/保存/记录/读取)。
gcc-evo五层架构: L2 记忆检索层(存储部分)
依赖: 仅L1 models
"""
from __future__ import annotations

import os
import json
import threading
import time
import numpy as np
from datetime import datetime, timezone

from .models import (
    plugin_log,
    _HISTORY_FILE, _PENDING_FILE,
    KNN_FUTURE_BARS,
)


# ============================================================
# PluginKNNDB: 历史特征库(纯数据I/O)
# ============================================================
class PluginKNNDB:
    """每个外挂×品种一个历史特征库"""

    def __init__(self):
        self._db: dict = {}
        self._pending: list = []
        self._lock = threading.Lock()
        self._load()

    def _make_key(self, plugin_name: str, symbol: str) -> str:
        return f"{plugin_name}_{symbol}"

    def _load(self):
        """加载历史库"""
        if _HISTORY_FILE.exists():
            try:
                data = np.load(str(_HISTORY_FILE), allow_pickle=True)
                self._db = data["db"].item() if "db" in data else {}
            except Exception as e:
                plugin_log(f"[PLUGIN_KNN] 加载历史库失败: {e}")
                self._db = {}
        if _PENDING_FILE.exists():
            try:
                with open(_PENDING_FILE, "r") as f:
                    self._pending = json.load(f)
            except Exception:
                self._pending = []

    def _save(self):
        """保存历史库"""
        try:
            os.makedirs("state", exist_ok=True)
            np.savez(str(_HISTORY_FILE), db=np.array(self._db, dtype=object))
        except Exception as e:
            plugin_log(f"[PLUGIN_KNN] 保存历史库失败: {e}")

    def _save_pending(self):
        """保存待回填列表"""
        try:
            os.makedirs("state", exist_ok=True)
            with open(_PENDING_FILE, "w") as f:
                json.dump(self._pending[-5000:], f)
        except Exception:
            pass

    def record(self, plugin_name: str, symbol: str, features: np.ndarray,
               signal_direction: str, close_price: float = 0,
               regime: str = "unknown"):
        """外挂触发时记录特征(收益待回填)"""
        if features is None or len(features) == 0:
            return
        key = self._make_key(plugin_name, symbol)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            self._pending.append({
                "key": key,
                "plugin": plugin_name,
                "symbol": symbol,
                "features": features.tolist(),
                "direction": signal_direction,
                "close_price": close_price,
                "recorded_at": ts,
                "regime": regime,
            })
            self._save_pending()

    def add_to_history(self, key: str, features: np.ndarray, ret: float,
                       regime: str = "unknown"):
        """添加一条已确认收益的记录到历史库"""
        feat_2d = features.reshape(1, -1)
        ts_now = time.time()
        with self._lock:
            if key in self._db:
                self._db[key]["features"] = np.vstack([self._db[key]["features"], feat_2d])
                self._db[key]["returns"] = np.append(self._db[key]["returns"], ret)
                if "regimes" not in self._db[key]:
                    n_existing = len(self._db[key]["returns"]) - 1
                    self._db[key]["regimes"] = ["unknown"] * n_existing + [regime]
                else:
                    self._db[key]["regimes"].append(regime)
                if "timestamps" not in self._db[key]:
                    n_existing = len(self._db[key]["returns"]) - 1
                    self._db[key]["timestamps"] = [ts_now] * n_existing + [ts_now]
                else:
                    self._db[key]["timestamps"].append(ts_now)
                if len(self._db[key]["returns"]) > 2000:
                    self._db[key]["features"] = self._db[key]["features"][-2000:]
                    self._db[key]["returns"] = self._db[key]["returns"][-2000:]
                    if "regimes" in self._db[key]:
                        self._db[key]["regimes"] = self._db[key]["regimes"][-2000:]
                    if "timestamps" in self._db[key]:
                        self._db[key]["timestamps"] = self._db[key]["timestamps"][-2000:]
            else:
                self._db[key] = {
                    "features": feat_2d,
                    "returns": np.array([ret]),
                    "regimes": [regime],
                    "timestamps": [ts_now],
                }

    def get_history(self, key: str) -> dict | None:
        """返回指定key的原始数据(features, returns, regimes, timestamps)"""
        return self._db.get(key)

    def get_all_keys(self) -> list:
        """返回所有key列表"""
        return list(self._db.keys())

    def get_pending(self) -> list:
        """返回待回填列表(只读副本)"""
        return list(self._pending)

    def commit_backfill(self, remaining: list, save_history: bool = False):
        """回填完成后: 更新pending + 可选保存历史"""
        with self._lock:
            self._pending = remaining
            self._save_pending()
            if save_history:
                self._save()

    def get_stats(self) -> dict:
        """获取所有key的统计信息"""
        stats = {}
        for key, data in self._db.items():
            n = len(data["returns"])
            avg = float(np.mean(data["returns"])) if n > 0 else 0
            win = float(np.sum(data["returns"] > 0) / n) if n > 0 else 0
            stats[key] = {"samples": n, "avg_return": avg, "win_rate": win}
        stats["_pending"] = len(self._pending)
        return stats
