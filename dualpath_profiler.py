#!/usr/bin/env python3
"""
DualPath Profiler v1.0 — GCC-0141 基准性能测量
scan_engine / plugin_knn 关键路径计时, 输出 state/dualpath_baseline.json

用法:
    from dualpath_profiler import profiler
    profiler.start("scan_once")
    ...
    profiler.stop("scan_once")
    profiler.flush()   # 每轮scan_once结束后写入JSON
"""
import json
import time
import threading
from pathlib import Path
from datetime import datetime

_STATE_DIR = Path(__file__).parent / "state"
_BASELINE_FILE = _STATE_DIR / "dualpath_baseline.json"
_MAX_HISTORY = 100  # 最多保留最近100轮的单轮明细


class DualPathProfiler:
    """线程安全的轻量计时器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._timers: dict[str, float] = {}      # key → start timestamp
        self._current: dict[str, float] = {}      # key → elapsed_ms (本轮)
        self._history: list[dict] = []            # 历史轮次
        self._loaded = False

    # ── 计时 API ──

    def start(self, key: str):
        with self._lock:
            self._timers[key] = time.perf_counter()

    def stop(self, key: str) -> float:
        """返回 elapsed_ms, 累加到 _current"""
        t1 = time.perf_counter()
        with self._lock:
            t0 = self._timers.pop(key, t1)
            elapsed = (t1 - t0) * 1000
            self._current[key] = self._current.get(key, 0) + elapsed
            return elapsed

    def record(self, key: str, elapsed_ms: float):
        """直接记录一个耗时值（不走start/stop）"""
        with self._lock:
            self._current[key] = self._current.get(key, 0) + elapsed_ms

    # ── 持久化 ──

    def flush(self):
        """本轮扫描结束, 写入baseline JSON"""
        with self._lock:
            if not self._current:
                return
            entry = {
                "ts": datetime.now().isoformat(),
                "metrics": dict(self._current),
            }
            self._current.clear()
            self._timers.clear()

        # 读→追加→写
        data = self._load_baseline()
        data["rounds"].append(entry)
        # 保留最近 _MAX_HISTORY 轮
        if len(data["rounds"]) > _MAX_HISTORY:
            data["rounds"] = data["rounds"][-_MAX_HISTORY:]
        # 更新汇总统计
        data["summary"] = self._compute_summary(data["rounds"])
        data["updated_at"] = datetime.now().isoformat()
        self._save_baseline(data)

    def _load_baseline(self) -> dict:
        if _BASELINE_FILE.exists():
            try:
                return json.loads(_BASELINE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"version": "1.0", "rounds": [], "summary": {}, "updated_at": ""}

    def _save_baseline(self, data: dict):
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _BASELINE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _compute_summary(rounds: list) -> dict:
        """计算每个metric的 avg / p50 / p95 / max"""
        from collections import defaultdict
        buckets: dict[str, list] = defaultdict(list)
        for r in rounds:
            for k, v in r.get("metrics", {}).items():
                buckets[k].append(v)
        summary = {}
        for k, vals in buckets.items():
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            summary[k] = {
                "count": n,
                "avg_ms": round(sum(vals_sorted) / n, 2),
                "p50_ms": round(vals_sorted[n // 2], 2),
                "p95_ms": round(vals_sorted[int(n * 0.95)], 2) if n >= 2 else round(vals_sorted[-1], 2),
                "max_ms": round(vals_sorted[-1], 2),
            }
        return summary


# 全局单例
profiler = DualPathProfiler()
