from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Sequence


Bias = Literal["BUY", "SELL", "HOLD"]
Horizon = Literal["1h", "4h", "1d", "3d"]
GateMode = Literal["observe", "soft", "full"]

ALLOWED_HORIZONS: tuple[Horizon, ...] = ("1h", "4h", "1d", "3d")
HORIZON_SECONDS: dict[Horizon, int] = {
    "1h": 3600,
    "4h": 4 * 3600,
    "1d": 24 * 3600,
    "3d": 3 * 24 * 3600,
}

logger = logging.getLogger(__name__)


@dataclass
class VisionSnapshot:
    snapshot_id: str
    ts_iso: str
    symbol: str
    timeframe: str
    price_at_snapshot: float
    pattern: str
    bias: Bias
    confidence: float
    key_features: list[str] = field(default_factory=list)
    price_signature: list[float] = field(default_factory=list)
    volume_signature: list[float] = field(default_factory=list)
    structure_points: list[tuple[int, str, float]] = field(default_factory=list)
    price_after: dict[Horizon, float] = field(default_factory=dict)
    move_pct: dict[Horizon, float] = field(default_factory=dict)
    actual_outcome: str | None = None
    vision_correct: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["structure_points"] = [list(p) for p in self.structure_points]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisionSnapshot":
        sp: list[tuple[int, str, float]] = []
        for raw in data.get("structure_points", []) or []:
            if isinstance(raw, (list, tuple)) and len(raw) == 3:
                try:
                    sp.append((int(raw[0]), str(raw[1]), float(raw[2])))
                except Exception:
                    continue

        price_after: dict[Horizon, float] = {}
        for h in ALLOWED_HORIZONS:
            if h in (data.get("price_after") or {}):
                try:
                    price_after[h] = float(data["price_after"][h])
                except Exception:
                    continue

        move_pct: dict[Horizon, float] = {}
        for h in ALLOWED_HORIZONS:
            if h in (data.get("move_pct") or {}):
                try:
                    move_pct[h] = float(data["move_pct"][h])
                except Exception:
                    continue

        bias = str(data.get("bias", "HOLD")).upper()
        if bias not in ("BUY", "SELL", "HOLD"):
            bias = "HOLD"

        return cls(
            snapshot_id=str(data.get("snapshot_id", "")),
            ts_iso=str(data.get("ts_iso", "")),
            symbol=str(data.get("symbol", "")),
            timeframe=str(data.get("timeframe", "")),
            price_at_snapshot=float(data.get("price_at_snapshot", 0.0) or 0.0),
            pattern=str(data.get("pattern", "UNKNOWN")),
            bias=bias,
            confidence=float(data.get("confidence", 0.0) or 0.0),
            key_features=[str(x) for x in (data.get("key_features") or [])],
            price_signature=[float(x) for x in (data.get("price_signature") or [])],
            volume_signature=[float(x) for x in (data.get("volume_signature") or [])],
            structure_points=sp,
            price_after=price_after,
            move_pct=move_pct,
            actual_outcome=(
                str(data["actual_outcome"]) if data.get("actual_outcome") is not None else None
            ),
            vision_correct=(
                bool(data["vision_correct"]) if data.get("vision_correct") is not None else None
            ),
        )


@dataclass
class VisionCalibration:
    calibrated_confidence: float
    historical_winrate: float | None = None
    expected_move_3d: float | None = None
    risk_reward_hist: float | None = None
    nsm_score: float | None = None
    reliability: str = "low"


@dataclass
class EnhancedVisionResult:
    snapshot: VisionSnapshot
    twins_count: int
    calibration: VisionCalibration
    mode: str


def clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def minmax_01(arr: Sequence[float]) -> list[float]:
    vals = [float(x) for x in arr]
    if not vals:
        return []
    lo = min(vals)
    hi = max(vals)
    if hi <= lo:
        return [0.5 for _ in vals]
    span = hi - lo
    return [(v - lo) / span for v in vals]


def local_extrema_points(arr: Sequence[float], order: int = 5) -> list[tuple[int, str, float]]:
    vals = [float(x) for x in arr]
    n = len(vals)
    if n == 0:
        return []
    k = max(1, int(order))
    out: list[tuple[int, str, float]] = []
    for i in range(k, n - k):
        center = vals[i]
        left = vals[i - k : i]
        right = vals[i + 1 : i + 1 + k]
        if not left or not right:
            continue
        if center >= max(left) and center >= max(right):
            out.append((i, "H", center))
        elif center <= min(left) and center <= min(right):
            out.append((i, "L", center))
    return out


def compute_price_signature(closes: Sequence[float], bars: int = 60) -> list[float]:
    if len(closes) < bars:
        return []
    return minmax_01(closes[-bars:])


def compute_volume_signature(volumes: Sequence[float], bars: int = 60) -> list[float]:
    if len(volumes) < bars:
        return []
    return minmax_01(volumes[-bars:])


def compute_structure_points(
    closes: Sequence[float], bars: int = 60, order: int = 5
) -> list[tuple[int, str, float]]:
    if len(closes) < bars:
        return []
    return local_extrema_points(closes[-bars:], order=order)


def l2_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    err = 0.0
    for i in range(n):
        d = float(a[i]) - float(b[i])
        err += d * d
    rmse = math.sqrt(err / n)
    return clamp01(1.0 - rmse)


def dtw_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """DTW相似度: 容忍时间轴伸缩的K线形态匹配。
    price_signature已归一化, DTW距离∈[0,1], 转换为相似度。"""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0.0
    # Sakoe-Chiba band: 限制弯曲窗口, 降低O(n*m)到O(n*w)
    w = max(abs(n - m), min(n, m) // 4, 3)
    INF = float("inf")
    # 仅保留两行, 节省内存
    prev = [INF] * (m + 1)
    prev[0] = 0.0
    for i in range(1, n + 1):
        curr = [INF] * (m + 1)
        j_lo = max(1, i - w)
        j_hi = min(m, i + w)
        for j in range(j_lo, j_hi + 1):
            cost = abs(float(a[i - 1]) - float(b[j - 1]))
            curr[j] = cost + min(prev[j], curr[j - 1], prev[j - 1])
        prev = curr
    dist = prev[m] / max(n, m)
    return clamp01(1.0 - dist)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return clamp01((dot / math.sqrt(na * nb) + 1.0) / 2.0)


def structure_similarity(
    a: Sequence[tuple[int, str, float]], b: Sequence[tuple[int, str, float]]
) -> float:
    if not a or not b:
        return 0.0
    aa = [(int(i), str(t), float(v)) for i, t, v in a]
    bb = [(int(i), str(t), float(v)) for i, t, v in b]
    max_idx = max(max(i for i, _, _ in aa), max(i for i, _, _ in bb), 1)

    used: set[int] = set()
    score_sum = 0.0
    for i1, t1, v1 in aa:
        best_j = -1
        best_score = -1.0
        for j, (i2, t2, v2) in enumerate(bb):
            if j in used or t1 != t2:
                continue
            idx_sim = 1.0 - min(abs(i1 - i2) / max_idx, 1.0)
            val_sim = 1.0 - min(abs(v1 - v2), 1.0)
            pair_score = 0.6 * idx_sim + 0.4 * val_sim
            if pair_score > best_score:
                best_score = pair_score
                best_j = j
        if best_j >= 0:
            used.add(best_j)
            score_sum += best_score

    denom = max(len(aa), len(bb), 1)
    return clamp01(score_sum / denom)


def context_similarity(cur: VisionSnapshot, hist: VisionSnapshot) -> float:
    pat_sim = 1.0 if cur.pattern == hist.pattern else 0.0
    bias_sim = 1.0 if cur.bias == hist.bias else 0.0
    tf_sim = 1.0 if cur.timeframe == hist.timeframe else 0.0
    conf_sim = 1.0 - min(abs(float(cur.confidence) - float(hist.confidence)), 1.0)

    cur_set = set(cur.key_features)
    hist_set = set(hist.key_features)
    if cur_set or hist_set:
        feat_sim = len(cur_set & hist_set) / max(len(cur_set | hist_set), 1)
    else:
        feat_sim = 0.0

    return clamp01(0.25 * pat_sim + 0.20 * bias_sim + 0.15 * tf_sim + 0.20 * conf_sim + 0.20 * feat_sim)


def recency_weight(ts_iso: str) -> float:
    try:
        ts = _parse_ts(ts_iso)
    except Exception:
        return 0.7
    age_days = max((datetime.now(timezone.utc) - ts).total_seconds() / 86400.0, 0.0)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.9
    if age_days <= 90:
        return 0.8
    if age_days <= 180:
        return 0.7
    return 0.6


def weighted_winrate(weighted: Sequence[tuple[VisionSnapshot, float]]) -> float:
    num = 0.0
    den = 0.0
    for snap, w in weighted:
        if snap.vision_correct is None:
            continue
        ww = max(float(w), 0.0)
        den += ww
        if snap.vision_correct:
            num += ww
    if den <= 1e-12:
        return 0.5
    return clamp01(num / den)


def weighted_move_stats(
    weighted: Sequence[tuple[VisionSnapshot, float]], horizon: Horizon
) -> tuple[float, float]:
    _assert_horizon(horizon)
    items: list[tuple[float, float]] = []
    for snap, w in weighted:
        if horizon not in snap.move_pct:
            continue
        try:
            items.append((float(snap.move_pct[horizon]), max(float(w), 0.0)))
        except Exception:
            continue
    if not items:
        return 0.0, 0.0
    den = sum(w for _, w in items)
    if den <= 1e-12:
        return 0.0, 0.0
    mean = sum(v * w for v, w in items) / den
    var = sum(w * (v - mean) * (v - mean) for v, w in items) / den
    return mean, math.sqrt(max(var, 0.0))


def write_json_atomic(path: str, obj: object) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_vision_", suffix=".json", dir=directory or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def log_warn(msg: str) -> None:
    logger.warning(msg)


def log_observe_payload(symbol: str, action: str, payload: EnhancedVisionResult) -> None:
    root = os.path.join("state", "vision_cache")
    os.makedirs(root, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(root, f"observe_{day}.jsonl")
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol": symbol,
        "action": action,
        "mode": payload.mode,
        "twins_count": payload.twins_count,
        "snapshot_id": payload.snapshot.snapshot_id,
        "pattern": payload.snapshot.pattern,
        "bias": payload.snapshot.bias,
        "calibration": asdict(payload.calibration),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class VisionCache:
    def __init__(
        self,
        root_dir: str = os.path.join("state", "vision_cache"),
        db_path: str | None = None,
    ):
        self.root_dir = root_dir
        self.snapshots_dir = os.path.join(root_dir, "snapshots")
        self.db_path = db_path or os.path.join(root_dir, "index.db")

    def _ensure_ready(self) -> None:
        os.makedirs(self.snapshots_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    bias TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    ts_iso TEXT NOT NULL,
                    has_outcome INTEGER NOT NULL DEFAULT 0,
                    updated_unix REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vc_query
                ON snapshots(pattern, bias, timeframe, ts_iso DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vc_pending
                ON snapshots(has_outcome, ts_iso DESC)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def path_for(self, snap: VisionSnapshot) -> str:
        safe_symbol = _safe_name(snap.symbol)
        return os.path.join(self.snapshots_dir, safe_symbol, f"{snap.snapshot_id}.json")

    def upsert_index(self, snap: VisionSnapshot) -> None:
        self._ensure_ready()
        has_outcome = 1 if snap.actual_outcome is not None and snap.vision_correct is not None else 0
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshots(snapshot_id, symbol, pattern, bias, timeframe, ts_iso, has_outcome, updated_unix)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    pattern=excluded.pattern,
                    bias=excluded.bias,
                    timeframe=excluded.timeframe,
                    ts_iso=excluded.ts_iso,
                    has_outcome=excluded.has_outcome,
                    updated_unix=excluded.updated_unix
                """,
                (
                    snap.snapshot_id,
                    snap.symbol,
                    snap.pattern,
                    snap.bias,
                    snap.timeframe,
                    snap.ts_iso,
                    has_outcome,
                    time.time(),
                ),
            )
            conn.commit()

    def save(self, snap: VisionSnapshot) -> None:
        self._ensure_ready()
        write_json_atomic(self.path_for(snap), snap.to_dict())
        try:
            self.upsert_index(snap)
        except Exception as exc:
            log_warn(f"[VISION_CACHE][INDEX_FAIL] id={snap.snapshot_id} err={type(exc).__name__}")

    def update(self, snap: VisionSnapshot) -> None:
        self.save(snap)

    def select_ids(self, pattern: str, bias: Bias, timeframe: str, limit: int = 5000) -> list[str]:
        self._ensure_ready()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id
                FROM snapshots
                WHERE pattern = ? AND bias = ? AND timeframe = ?
                ORDER BY ts_iso DESC
                LIMIT ?
                """,
                (pattern, bias, timeframe, int(limit)),
            ).fetchall()
        return [str(r[0]) for r in rows]

    def load_snapshots(self, ids: Sequence[str]) -> list[VisionSnapshot]:
        out: list[VisionSnapshot] = []
        for sid in ids:
            path = self._path_for_id(sid)
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                out.append(VisionSnapshot.from_dict(data))
            except Exception:
                continue
        return out

    def query(
        self, pattern: str, bias: Bias, timeframe: str, limit: int = 5000
    ) -> list[VisionSnapshot]:
        ids = self.select_ids(pattern=pattern, bias=bias, timeframe=timeframe, limit=limit)
        return self.load_snapshots(ids)

    def get_pending_backfill(self, limit: int = 2000) -> list[VisionSnapshot]:
        self._ensure_ready()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id
                FROM snapshots
                WHERE has_outcome = 0
                ORDER BY ts_iso ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return self.load_snapshots([str(r[0]) for r in rows])

    def get_all_with_outcomes(self, limit: int = 50000) -> list[VisionSnapshot]:
        self._ensure_ready()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id
                FROM snapshots
                WHERE has_outcome = 1
                ORDER BY ts_iso DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return self.load_snapshots([str(r[0]) for r in rows])

    def _path_for_id(self, snapshot_id: str) -> str | None:
        self._ensure_ready()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT symbol FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if not row:
            return None
        symbol = str(row[0])
        return os.path.join(self.snapshots_dir, _safe_name(symbol), f"{snapshot_id}.json")


def archive_old_snapshots(
    cache: "VisionCache",
    retain_days: int = 365,
) -> dict[str, int]:
    """v3.678: 保留最近retain_days天的snapshot，超期按完整月归档到 archive/YYYY-MM/ 目录。

    归档 = 从活跃目录移到 archive/ + 从索引DB删除。
    归档后的JSON文件仍可手动读取，但不参与孪生匹配。

    Returns: {"archived": N, "deleted_from_db": N, "archive_dir": path}
    """
    cache._ensure_ready()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(int(retain_days), 30))
    # 只归档完整月: cutoff月的第1天作为边界 (确保当月不被归档)
    cutoff_month_start = cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cutoff_iso = cutoff_month_start.strftime("%Y-%m-%dT%H:%M:%S")

    with cache._connect() as conn:
        rows = conn.execute(
            "SELECT snapshot_id, symbol, ts_iso FROM snapshots WHERE ts_iso < ? ORDER BY ts_iso",
            (cutoff_iso,),
        ).fetchall()

    if not rows:
        return {"archived": 0, "deleted_from_db": 0, "archive_dir": ""}

    archive_base = os.path.join(cache.root_dir, "archive")
    archived = 0
    ids_to_delete: list[str] = []

    for snap_id, symbol, ts_iso in rows:
        # 解析月份
        try:
            month_str = ts_iso[:7]  # "YYYY-MM"
        except Exception:
            continue

        src = os.path.join(cache.snapshots_dir, _safe_name(symbol), f"{snap_id}.json")
        if not os.path.exists(src):
            ids_to_delete.append(snap_id)
            continue

        dst_dir = os.path.join(archive_base, month_str, _safe_name(symbol))
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{snap_id}.json")

        try:
            import shutil
            shutil.move(src, dst)
            archived += 1
            ids_to_delete.append(snap_id)
        except Exception as exc:
            log_warn(f"[VISION_CACHE][ARCHIVE_FAIL] id={snap_id} err={type(exc).__name__}")

    # 批量从DB删除
    if ids_to_delete:
        with cache._connect() as conn:
            for batch_start in range(0, len(ids_to_delete), 500):
                batch = ids_to_delete[batch_start : batch_start + 500]
                placeholders = ",".join("?" for _ in batch)
                conn.execute(f"DELETE FROM snapshots WHERE snapshot_id IN ({placeholders})", batch)
            conn.commit()

    # 清理空的品种子目录
    try:
        for d in os.listdir(cache.snapshots_dir):
            full = os.path.join(cache.snapshots_dir, d)
            if os.path.isdir(full) and not os.listdir(full):
                os.rmdir(full)
    except Exception:
        pass

    return {"archived": archived, "deleted_from_db": len(ids_to_delete), "archive_dir": archive_base}


def find_historical_twins(
    current: VisionSnapshot,
    cache: VisionCache,
    top_k: int = 10,
) -> list[tuple[VisionSnapshot, float]]:
    candidates = cache.query(
        pattern=current.pattern,
        bias=current.bias,
        timeframe=current.timeframe,
        limit=5000,
    )

    lv2: list[tuple[VisionSnapshot, float]] = []
    for snap in candidates:
        if snap.snapshot_id == current.snapshot_id:
            continue
        struct_sim = structure_similarity(current.structure_points, snap.structure_points)
        if struct_sim >= 0.60:
            lv2.append((snap, struct_sim))
    lv2.sort(key=lambda x: x[1], reverse=True)
    lv2 = lv2[:50]

    out: list[tuple[VisionSnapshot, float]] = []
    for snap, struct_sim in lv2:
        price_sim = dtw_similarity(current.price_signature, snap.price_signature)
        vol_sim = cosine_similarity(current.volume_signature, snap.volume_signature)
        ctx_sim = context_similarity(current, snap)
        score = 0.30 * struct_sim + 0.40 * price_sim + 0.15 * vol_sim + 0.15 * ctx_sim
        out.append((snap, clamp01(score)))

    out.sort(key=lambda x: x[1], reverse=True)
    return out[: max(int(top_k), 0)]


def calibrate_with_twins(
    vision_result: VisionSnapshot,
    twins: Sequence[tuple[VisionSnapshot, float]],
) -> VisionCalibration:
    if len(twins) < 3:
        return VisionCalibration(
            calibrated_confidence=clamp01(float(vision_result.confidence) * 0.8),
            reliability="low",
        )

    weighted: list[tuple[VisionSnapshot, float]] = []
    for hist, sim in twins:
        if hist.actual_outcome is None:
            continue
        weighted.append((hist, float(sim) * recency_weight(hist.ts_iso)))

    if len(weighted) < 3:
        return VisionCalibration(
            calibrated_confidence=clamp01(float(vision_result.confidence) * 0.85),
            reliability="low",
        )

    hist_winrate = weighted_winrate(weighted)
    exp_3d, std_3d = weighted_move_stats(weighted, horizon="3d")
    calibrated = clamp01(0.7 * float(vision_result.confidence) + 0.3 * hist_winrate)

    reliability = "low"
    if len(weighted) >= 30:
        reliability = "high"
    elif len(weighted) >= 10:
        reliability = "medium"

    return VisionCalibration(
        calibrated_confidence=calibrated,
        historical_winrate=hist_winrate,
        expected_move_3d=exp_3d,
        risk_reward_hist=(abs(exp_3d) / max(std_3d, 1e-6)) if std_3d is not None else None,
        reliability=reliability,
    )


def compute_point_nsm(current: VisionSnapshot, cache: VisionCache) -> float:
    twins = find_historical_twins(current, cache, top_k=10)
    scored = [(snap, sim) for snap, sim in twins if snap.vision_correct is not None]
    if not scored:
        return 0.0
    num = 0.0
    den = 0.0
    for snap, sim in scored:
        w = max(float(sim), 0.0)
        den += w
        if snap.vision_correct:
            num += w
    if den <= 1e-12:
        return 0.0
    return clamp01(num / den)


def nsm_aware_calibration(
    current: VisionSnapshot,
    base_calibration: VisionCalibration,
    cache: VisionCache,
) -> VisionCalibration:
    nsm = compute_point_nsm(current, cache)
    alpha = 1.0 if nsm >= 0.7 else 0.6 if nsm >= 0.4 else 0.3
    calibrated_conf = clamp01(
        alpha * float(base_calibration.calibrated_confidence)
        + (1.0 - alpha) * float(current.confidence)
    )
    return VisionCalibration(
        calibrated_confidence=calibrated_conf,
        historical_winrate=base_calibration.historical_winrate,
        expected_move_3d=base_calibration.expected_move_3d,
        risk_reward_hist=base_calibration.risk_reward_hist,
        nsm_score=nsm,
        reliability=base_calibration.reliability,
    )


def build_snapshot(symbol: str, chart_image: Any, df: Any) -> VisionSnapshot:
    del chart_image
    closes = _extract_numeric_series(df, ["close", "Close", "c"])
    vols = _extract_numeric_series(df, ["volume", "Volume", "v"])

    price_at = float(closes[-1]) if closes else 0.0
    attrs = getattr(df, "attrs", {}) if df is not None else {}
    if not isinstance(attrs, dict):
        attrs = {}

    ts_iso = str(attrs.get("ts_iso") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    timeframe = str(attrs.get("timeframe") or "4h")
    pattern = str(attrs.get("pattern") or "UNKNOWN").upper()

    raw_bias = str(attrs.get("bias") or "HOLD").upper()
    bias: Bias = "HOLD"
    if raw_bias in ("BUY", "SELL", "HOLD"):
        bias = raw_bias

    confidence = clamp01(float(attrs.get("confidence") or 0.5))
    key_features = [str(x) for x in (attrs.get("key_features") or [])]

    payload = f"{symbol}|{ts_iso}|{pattern}|{bias}|{confidence:.6f}|{price_at:.6f}"
    snapshot_id = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]

    return VisionSnapshot(
        snapshot_id=snapshot_id,
        ts_iso=ts_iso,
        symbol=symbol,
        timeframe=timeframe,
        price_at_snapshot=price_at,
        pattern=pattern,
        bias=bias,
        confidence=confidence,
        key_features=key_features,
        price_signature=compute_price_signature(closes, bars=60),
        volume_signature=compute_volume_signature(vols, bars=60),
        structure_points=compute_structure_points(closes, bars=60, order=5),
    )


def enhanced_vision(
    symbol: str,
    chart_image: Any,
    df: Any,
    cache: VisionCache,
    mode: GateMode = "observe",
) -> EnhancedVisionResult:
    snap = build_snapshot(symbol=symbol, chart_image=chart_image, df=df)
    cache.save(snap)
    twins = find_historical_twins(snap, cache, top_k=10)
    base = calibrate_with_twins(snap, twins)
    calibrated = nsm_aware_calibration(snap, base, cache)
    return EnhancedVisionResult(
        snapshot=snap,
        twins_count=len(twins),
        calibration=calibrated,
        mode=mode,
    )


def enforce_gate_with_policy(
    ev: EnhancedVisionResult,
    action: str,
    mode: Literal["soft", "full"],
) -> tuple[bool, str]:
    if mode not in ("soft", "full"):
        return True, "invalid_mode"

    act = str(action).upper()
    if act not in ("BUY", "SELL", "HOLD"):
        return True, "unknown_action"
    if act == "HOLD":
        return True, "hold_passthrough"

    conf = float(ev.calibration.calibrated_confidence)
    conf_thr = 0.50 if mode == "soft" else 0.55
    if conf < conf_thr:
        return False, f"low_calibrated_conf:{conf:.3f}<{conf_thr:.3f}"

    if ev.twins_count < 3:
        return False, "insufficient_twins"

    wr = ev.calibration.historical_winrate
    if wr is not None and wr < 0.45:
        return False, f"low_hist_winrate:{wr:.3f}"

    exp_move = ev.calibration.expected_move_3d
    if exp_move is not None:
        if act == "BUY" and exp_move < -0.003:
            return False, f"negative_expected_move_3d:{exp_move:.4f}"
        if act == "SELL" and exp_move > 0.003:
            return False, f"positive_expected_move_3d:{exp_move:.4f}"

    return True, "policy_pass"


def vision_gate(
    symbol: str,
    action: str,
    chart: Any,
    df: Any,
    cache: VisionCache,
    mode: GateMode = "observe",
) -> tuple[bool, str]:
    if mode == "observe":
        try:
            ev = enhanced_vision(symbol=symbol, chart_image=chart, df=df, cache=cache, mode=mode)
            try:
                log_observe_payload(symbol=symbol, action=action, payload=ev)
            except Exception as log_exc:
                log_warn(f"[VISION_CACHE][OBS_LOG_FAIL] symbol={symbol} err={type(log_exc).__name__}")
            return True, "obs_only"
        except Exception as exc:
            log_warn(f"[VISION_CACHE][FAIL_OPEN] symbol={symbol} mode={mode} err={type(exc).__name__}")
            return True, "fail_open_exception"

    try:
        ev = enhanced_vision(symbol=symbol, chart_image=chart, df=df, cache=cache, mode=mode)
        allowed, reason = enforce_gate_with_policy(ev, action, mode="soft" if mode == "soft" else "full")
        if mode == "soft" and not allowed:
            return True, f"soft_would_block:{reason}"
        return allowed, reason
    except Exception as exc:
        log_warn(f"[VISION_CACHE][FAIL_OPEN] symbol={symbol} mode={mode} err={type(exc).__name__}")
        return True, "fail_open_exception"


def due(h: Horizon, ts_iso: str) -> bool:
    _assert_horizon(h)
    ts = _parse_ts(ts_iso)
    return datetime.now(timezone.utc) >= ts + timedelta(seconds=HORIZON_SECONDS[h])


def pct(new_px: float, old_px: float) -> float:
    if old_px <= 0:
        return 0.0
    return (float(new_px) - float(old_px)) / float(old_px)


def classify_outcome(move_pct_3d: float) -> str:
    if move_pct_3d >= 0.02:
        return "UP_STRONG"
    if move_pct_3d >= 0.005:
        return "UP_WEAK"
    if move_pct_3d <= -0.02:
        return "DOWN_STRONG"
    if move_pct_3d <= -0.005:
        return "DOWN_WEAK"
    return "FLAT"


def direction_match(bias: Bias, move_pct_3d: float) -> bool:
    if bias == "HOLD":
        return abs(move_pct_3d) < 0.005
    if bias == "BUY":
        return move_pct_3d > 0.0
    return move_pct_3d < 0.0


def get_price_at(symbol: str, ts_iso: str, horizon: Horizon) -> float | None:
    _assert_horizon(horizon)
    try:
        import pandas as pd  # type: ignore
        import yfinance as yf  # type: ignore
    except Exception:
        return None

    base_ts = _parse_ts(ts_iso)
    target_ts = base_ts + timedelta(seconds=HORIZON_SECONDS[horizon])
    start = (target_ts - timedelta(days=2)).strftime("%Y-%m-%d")
    end = (target_ts + timedelta(days=2)).strftime("%Y-%m-%d")
    yf_symbol = _to_yf_symbol(symbol)

    try:
        df = yf.download(
            yf_symbol,
            start=start,
            end=end,
            interval="1h",
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        return None

    if df is None or len(df) == 0:
        return None

    try:
        idx = pd.to_datetime(df.index, utc=True)
        close_col = "Close" if "Close" in df.columns else "close"
        closes = df[close_col]
        diffs = abs(idx - target_ts)
        best_pos = int(diffs.argmin())
        delta_sec = float(diffs[best_pos].total_seconds())
    except Exception:
        return None

    tolerance_sec = 4 * 3600 if horizon in ("1h", "4h") else 12 * 3600
    if delta_sec > tolerance_sec:
        return None

    try:
        return float(closes.iloc[best_pos])
    except Exception:
        return None


def backfill_snapshots(cache: VisionCache) -> int:
    updated = 0
    for snap in cache.get_pending_backfill():
        changed = False
        for h in ALLOWED_HORIZONS:
            if h in snap.price_after:
                continue
            try:
                if not due(h, snap.ts_iso):
                    continue
            except Exception:
                continue

            px = get_price_at(snap.symbol, snap.ts_iso, h)
            if px is None:
                continue
            snap.price_after[h] = px
            snap.move_pct[h] = pct(px, snap.price_at_snapshot)
            changed = True

        if "3d" in snap.move_pct and snap.actual_outcome is None:
            snap.actual_outcome = classify_outcome(snap.move_pct["3d"])
            snap.vision_correct = direction_match(snap.bias, snap.move_pct["3d"])
            changed = True

        if changed:
            cache.update(snap)
            updated += 1
    return updated


def find_patterns_below_accuracy(
    snaps: Sequence[VisionSnapshot], threshold: float, min_samples: int
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, Bias, str], list[bool]] = {}
    for s in snaps:
        if s.vision_correct is None:
            continue
        key = (s.pattern, s.bias, s.timeframe)
        buckets.setdefault(key, []).append(bool(s.vision_correct))

    out: list[dict[str, Any]] = []
    for (pattern, bias, timeframe), vals in buckets.items():
        n = len(vals)
        if n < int(min_samples):
            continue
        acc = sum(1 for v in vals if v) / n
        if acc < threshold:
            out.append(
                {
                    "pattern": pattern,
                    "bias": bias,
                    "timeframe": timeframe,
                    "samples": n,
                    "accuracy": round(acc, 4),
                }
            )
    out.sort(key=lambda x: (x["accuracy"], -x["samples"]))
    return out


def compare_feature_presence(snaps: Sequence[VisionSnapshot]) -> dict[str, dict[str, float]]:
    good_total = 0
    bad_total = 0
    good: dict[str, int] = {}
    bad: dict[str, int] = {}
    for s in snaps:
        if s.vision_correct is None:
            continue
        features = set(s.key_features)
        if s.vision_correct:
            good_total += 1
            for f in features:
                good[f] = good.get(f, 0) + 1
        else:
            bad_total += 1
            for f in features:
                bad[f] = bad.get(f, 0) + 1

    keys = set(good) | set(bad)
    out: dict[str, dict[str, float]] = {}
    for k in keys:
        gp = good.get(k, 0) / max(good_total, 1)
        bp = bad.get(k, 0) / max(bad_total, 1)
        out[k] = {
            "good_presence": round(gp, 6),
            "bad_presence": round(bp, 6),
            "delta": round(gp - bp, 6),
            "support": int(good.get(k, 0) + bad.get(k, 0)),
        }
    return out


def top_positive_features(feature_delta: dict[str, dict[str, float]], k: int = 10) -> list[dict[str, Any]]:
    rows = [{"feature": f, **m} for f, m in feature_delta.items()]
    rows.sort(key=lambda x: (x["delta"], x["support"]), reverse=True)
    return rows[: max(int(k), 0)]


def top_negative_features(feature_delta: dict[str, dict[str, float]], k: int = 10) -> list[dict[str, Any]]:
    rows = [{"feature": f, **m} for f, m in feature_delta.items()]
    rows.sort(key=lambda x: (x["delta"], -x["support"]))
    return rows[: max(int(k), 0)]


def write_monthly_report(report: dict[str, Any]) -> str:
    root = os.path.join("state", "vision_cache")
    os.makedirs(root, exist_ok=True)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    path = os.path.join(root, f"evolution_{month}.json")
    write_json_atomic(path, report)
    return path


def evolution_analysis(cache: VisionCache) -> dict[str, Any]:
    snaps = cache.get_all_with_outcomes()
    weak = find_patterns_below_accuracy(snaps, threshold=0.50, min_samples=10)
    feature_delta = compare_feature_presence(snaps)
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "samples": len(snaps),
        "weak_patterns": weak,
        "success_features": top_positive_features(feature_delta),
        "failure_features": top_negative_features(feature_delta),
    }
    write_monthly_report(report)
    return report


def _extract_numeric_series(df: Any, candidates: Sequence[str]) -> list[float]:
    if df is None:
        return []
    cols = getattr(df, "columns", None)
    if cols is None:
        return []
    col_map = {str(c).lower(): c for c in cols}
    for c in candidates:
        real = col_map.get(c.lower())
        if real is None:
            continue
        try:
            series = df[real]
            return [float(x) for x in series.tolist()]
        except Exception:
            continue
    return []


def _safe_name(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep) or "unknown"


def _parse_ts(ts_iso: str) -> datetime:
    raw = str(ts_iso).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _assert_horizon(h: str) -> None:
    if h not in ALLOWED_HORIZONS:
        raise ValueError(f"Unsupported horizon: {h}")


def _to_yf_symbol(symbol: str) -> str:
    mapping = {
        "BTCUSDC": "BTC-USD",
        "ETHUSDC": "ETH-USD",
        "SOLUSDC": "SOL-USD",
        "ZECUSDC": "ZEC-USD",
    }
    return mapping.get(symbol, symbol)


__all__ = [
    "VisionSnapshot",
    "VisionCalibration",
    "EnhancedVisionResult",
    "minmax_01",
    "local_extrema_points",
    "compute_price_signature",
    "compute_volume_signature",
    "compute_structure_points",
    "structure_similarity",
    "l2_similarity",
    "dtw_similarity",
    "cosine_similarity",
    "context_similarity",
    "VisionCache",
    "find_historical_twins",
    "calibrate_with_twins",
    "nsm_aware_calibration",
    "compute_point_nsm",
    "enhanced_vision",
    "vision_gate",
    "enforce_gate_with_policy",
    "due",
    "backfill_snapshots",
    "archive_old_snapshots",
    "evolution_analysis",
]
