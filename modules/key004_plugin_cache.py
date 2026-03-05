from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol, Sequence


logger = logging.getLogger(__name__)

ALLOWED_TIMEFRAMES: tuple[str, ...] = ("4h", "1d", "3d", "1w")
ALLOWED_HORIZONS: tuple[str, ...] = ALLOWED_TIMEFRAMES


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_iso(dt: datetime | None = None) -> str:
    use = dt or _utc_now()
    return use.isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str) -> datetime:
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _assert_timeframe(timeframe: str) -> None:
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")


@dataclass
class FeatureVector:
    symbol: str
    timeframe: str
    plugin_name: str
    timestamp: int
    features_dict: dict[str, Any]
    ohlcv: dict[str, float] = field(default_factory=dict)
    kline_signature: dict[str, float] = field(default_factory=dict)
    version: str = "v1.0"
    regime_label: str = "unknown"
    created_at: str = field(default_factory=_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CacheMetadata:
    cache_id: str
    created_at: str
    updated_at: str
    hit_count: int = 0
    miss_count: int = 0
    last_validation: str | None = None

    @property
    def hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0


@dataclass
class KlineSignature:
    open_close_ratio: float
    high_low_ratio: float
    body_ratio: float
    volume_ma_ratio: float
    atr_ratio: float

    def to_vector(self) -> list[float]:
        return [
            float(self.open_close_ratio),
            float(self.high_low_ratio),
            float(self.body_ratio),
            float(self.volume_ma_ratio),
            float(self.atr_ratio),
        ]

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class MFEMAEResult:
    mfe_pct: float
    mae_pct: float
    mfe_bars: int
    mae_bars: int
    mfe_price: float
    mae_price: float


@dataclass
class CacheVersion:
    version_id: str
    timestamp: str
    plugin_name: str
    changes: dict[str, Any]
    status: str
    description: str = ""


@dataclass
class DeltaEvalRequest:
    feature_name: str
    baseline_version: str
    candidate_version: str
    baseline_metrics: dict[str, float]
    candidate_metrics: dict[str, float]
    regime_split: dict[str, dict[str, float]]


@dataclass
class DeltaEvalResult:
    request_id: str
    status: str
    delta_icir: float
    delta_win_rate: float
    delta_sample_n: int
    regime_stability: float
    approval_reason: str
    rejection_reason: str = ""


@dataclass
class CacheMetrics:
    timestamp: str
    hit_rate: float
    miss_rate: float
    fallback_rate: float
    feature_drift: dict[str, float]
    version_distribution: dict[str, int]
    avg_query_time_ms: float


class MarketDataLoader(Protocol):
    def load_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        ...


class PluginAdapter(Protocol):
    def compute(
        self,
        plugin_name: str,
        symbol: str,
        timeframe: str,
        bars: list[dict[str, Any]],
        idx: int,
    ) -> dict[str, Any] | None:
        ...


class CacheStorageBackend:
    def __init__(self, db_path: str = os.path.join("state", "cache", "key004_features.db")):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS feature_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    plugin_name TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    features_json TEXT NOT NULL,
                    ohlcv_json TEXT,
                    kline_signature_json TEXT,
                    version TEXT NOT NULL,
                    regime_label TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, timeframe, plugin_name, timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_fv_exact
                    ON feature_vectors(symbol, timeframe, plugin_name, timestamp);
                CREATE INDEX IF NOT EXISTS idx_fv_regime
                    ON feature_vectors(symbol, timeframe, regime_label, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_fv_plugin
                    ON feature_vectors(symbol, timeframe, plugin_name, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_fv_plugin_version
                    ON feature_vectors(plugin_name, version);

                CREATE TABLE IF NOT EXISTS cache_metadata (
                    cache_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    miss_count INTEGER NOT NULL DEFAULT 0,
                    last_validation TEXT
                );
                """
            )
            conn.commit()

    def write_feature_vector(self, fv: FeatureVector) -> bool:
        try:
            _assert_timeframe(fv.timeframe)
            payload = (
                fv.symbol,
                fv.timeframe,
                fv.plugin_name,
                int(fv.timestamp),
                json.dumps(fv.features_dict, ensure_ascii=True, separators=(",", ":")),
                json.dumps(fv.ohlcv, ensure_ascii=True, separators=(",", ":")),
                json.dumps(fv.kline_signature, ensure_ascii=True, separators=(",", ":")),
                fv.version,
                fv.regime_label,
                fv.created_at,
            )
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO feature_vectors
                    (symbol, timeframe, plugin_name, timestamp, features_json, ohlcv_json,
                     kline_signature_json, version, regime_label, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, timeframe, plugin_name, timestamp) DO UPDATE SET
                        features_json=excluded.features_json,
                        ohlcv_json=excluded.ohlcv_json,
                        kline_signature_json=excluded.kline_signature_json,
                        version=excluded.version,
                        regime_label=excluded.regime_label,
                        created_at=excluded.created_at
                    """,
                    payload,
                )
                conn.commit()
            return True
        except Exception as exc:
            logger.warning("[KEY004][CACHE_WRITE_FAIL] %s", type(exc).__name__)
            return False

    def query_feature_vector(
        self,
        symbol: str,
        timeframe: str,
        plugin_name: str,
        timestamp: int,
    ) -> FeatureVector | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM feature_vectors
                    WHERE symbol=? AND timeframe=? AND plugin_name=? AND timestamp=?
                    """,
                    (symbol, timeframe, plugin_name, int(timestamp)),
                ).fetchone()
            return self._row_to_fv(row)
        except Exception as exc:
            logger.warning("[KEY004][CACHE_QUERY_FAIL] %s", type(exc).__name__)
            return None

    def batch_query_by_regime(
        self,
        symbol: str,
        timeframe: str,
        regime: str,
        limit: int = 100,
    ) -> list[FeatureVector]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM feature_vectors
                    WHERE symbol=? AND timeframe=? AND regime_label=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (symbol, timeframe, regime, int(limit)),
                ).fetchall()
            return [fv for row in rows if (fv := self._row_to_fv(row)) is not None]
        except Exception as exc:
            logger.warning("[KEY004][CACHE_BATCH_REGIME_FAIL] %s", type(exc).__name__)
            return []

    def batch_query_by_plugin(
        self,
        symbol: str,
        timeframe: str,
        plugin_name: str,
        limit: int = 1000,
    ) -> list[FeatureVector]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM feature_vectors
                    WHERE symbol=? AND timeframe=? AND plugin_name=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (symbol, timeframe, plugin_name, int(limit)),
                ).fetchall()
            return [fv for row in rows if (fv := self._row_to_fv(row)) is not None]
        except Exception as exc:
            logger.warning("[KEY004][CACHE_BATCH_PLUGIN_FAIL] %s", type(exc).__name__)
            return []

    def version_distribution(self) -> dict[str, int]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT version, COUNT(*) AS c FROM feature_vectors GROUP BY version"
                ).fetchall()
            return {str(r["version"]): int(r["c"]) for r in rows}
        except Exception:
            return {}

    def list_plugin_feature_vectors(
        self,
        plugin_name: str,
        limit: int = 5000,
    ) -> list[FeatureVector]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM feature_vectors
                    WHERE plugin_name=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (plugin_name, int(limit)),
                ).fetchall()
            return [fv for row in rows if (fv := self._row_to_fv(row)) is not None]
        except Exception:
            return []

    def upsert_metadata(self, meta: CacheMetadata) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cache_metadata
                    (cache_id, created_at, updated_at, hit_count, miss_count, last_validation)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        hit_count=excluded.hit_count,
                        miss_count=excluded.miss_count,
                        last_validation=excluded.last_validation
                    """,
                    (
                        meta.cache_id,
                        meta.created_at,
                        meta.updated_at,
                        int(meta.hit_count),
                        int(meta.miss_count),
                        meta.last_validation,
                    ),
                )
                conn.commit()
        except Exception:
            return

    def get_metadata(self, cache_id: str) -> CacheMetadata:
        now_iso = _utc_iso()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM cache_metadata WHERE cache_id=?", (cache_id,)
                ).fetchone()
            if row is None:
                meta = CacheMetadata(
                    cache_id=cache_id,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                self.upsert_metadata(meta)
                return meta
            return CacheMetadata(
                cache_id=str(row["cache_id"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                hit_count=int(row["hit_count"]),
                miss_count=int(row["miss_count"]),
                last_validation=(str(row["last_validation"]) if row["last_validation"] else None),
            )
        except Exception:
            return CacheMetadata(cache_id=cache_id, created_at=now_iso, updated_at=now_iso)

    @staticmethod
    def _row_to_fv(row: sqlite3.Row | None) -> FeatureVector | None:
        if row is None:
            return None
        try:
            return FeatureVector(
                symbol=str(row["symbol"]),
                timeframe=str(row["timeframe"]),
                plugin_name=str(row["plugin_name"]),
                timestamp=int(row["timestamp"]),
                features_dict=_safe_json_loads(row["features_json"], {}),
                ohlcv=_safe_json_loads(row["ohlcv_json"], {}),
                kline_signature=_safe_json_loads(row["kline_signature_json"], {}),
                version=str(row["version"]),
                regime_label=str(row["regime_label"] or "unknown"),
                created_at=str(row["created_at"]),
            )
        except Exception:
            return None


def compute_atr(bars: Sequence[dict[str, Any]], period: int = 14) -> float:
    if not bars or period <= 0:
        return 0.0
    trs: list[float] = []
    prev_close: float | None = None
    for bar in bars:
        high = _safe_float(bar.get("high"))
        low = _safe_float(bar.get("low"))
        close = _safe_float(bar.get("close"))
        if prev_close is None:
            tr = max(high - low, 0.0)
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(max(tr, 0.0))
        prev_close = close
    if not trs:
        return 0.0
    window = trs[-min(period, len(trs)) :]
    return float(sum(window) / max(len(window), 1))


def compute_kline_signature(
    ohlcv: dict[str, Any],
    historical_data: Sequence[dict[str, Any]] | None = None,
) -> KlineSignature:
    o = _safe_float(ohlcv.get("open"))
    h = _safe_float(ohlcv.get("high"))
    low_price = _safe_float(ohlcv.get("low"))
    c = _safe_float(ohlcv.get("close"))
    v = _safe_float(ohlcv.get("volume"))

    open_close_ratio = (c - o) / o if abs(o) > 1e-12 else 0.0
    high_low_ratio = (h - low_price) / low_price if abs(low_price) > 1e-12 else 0.0
    body_ratio = abs(c - o) / max(h - low_price, 1e-12)

    bars = list(historical_data or [])
    if bars and len(bars) >= 20:
        vol_ma20 = sum(_safe_float(b.get("volume")) for b in bars[-20:]) / 20.0
        volume_ma_ratio = v / vol_ma20 if vol_ma20 > 1e-12 else 1.0
        atr14 = compute_atr(bars, period=14)
        atr_ratio = atr14 / c if abs(c) > 1e-12 else 0.0
    else:
        volume_ma_ratio = 1.0
        atr_ratio = 0.02

    return KlineSignature(
        open_close_ratio=open_close_ratio,
        high_low_ratio=high_low_ratio,
        body_ratio=body_ratio,
        volume_ma_ratio=volume_ma_ratio,
        atr_ratio=atr_ratio,
    )


def cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    n = min(len(vec1), len(vec2))
    if n == 0:
        return 0.0
    dot = 0.0
    a_norm = 0.0
    b_norm = 0.0
    for i in range(n):
        a = _safe_float(vec1[i])
        b = _safe_float(vec2[i])
        dot += a * b
        a_norm += a * a
        b_norm += b * b
    if a_norm <= 1e-12 or b_norm <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, dot / math.sqrt(a_norm * b_norm)))


def aggregate_similar_features(
    similar_features: Sequence[tuple[FeatureVector, float]],
) -> dict[str, Any]:
    if not similar_features:
        return {}

    numeric_sum: dict[str, float] = {}
    numeric_weight: dict[str, float] = {}
    enum_votes: dict[str, dict[str, float]] = {}

    for fv, score in similar_features:
        w = max(_safe_float(score), 0.0)
        if w <= 0:
            continue
        for key, value in fv.features_dict.items():
            if isinstance(value, (int, float)):
                numeric_sum[key] = numeric_sum.get(key, 0.0) + float(value) * w
                numeric_weight[key] = numeric_weight.get(key, 0.0) + w
            elif isinstance(value, str):
                votes = enum_votes.setdefault(key, {})
                votes[value] = votes.get(value, 0.0) + w

    out: dict[str, Any] = {}
    for key, total in numeric_sum.items():
        den = numeric_weight.get(key, 0.0)
        if den > 1e-12:
            out[key] = total / den
    for key, votes in enum_votes.items():
        if votes:
            out[key] = max(votes.items(), key=lambda item: item[1])[0]
    return out


class CacheQueryEngine:
    def __init__(self, cache_backend: CacheStorageBackend, cache_id: str = "key004_default"):
        self.cache = cache_backend
        self.cache_id = cache_id
        self.hit_count = 0
        self.miss_count = 0
        self._query_times_ms: list[float] = []

    def query_exact(
        self,
        symbol: str,
        timeframe: str,
        plugin_name: str,
        timestamp: int,
    ) -> FeatureVector | None:
        start = time.perf_counter()
        fv = self.cache.query_feature_vector(symbol, timeframe, plugin_name, timestamp)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._query_times_ms.append(elapsed_ms)
        if len(self._query_times_ms) > 2000:
            self._query_times_ms = self._query_times_ms[-1000:]

        meta = self.cache.get_metadata(self.cache_id)
        if fv:
            self.hit_count += 1
            meta.hit_count += 1
        else:
            self.miss_count += 1
            meta.miss_count += 1
        meta.updated_at = _utc_iso()
        self.cache.upsert_metadata(meta)
        return fv

    def query_similar(
        self,
        symbol: str,
        timeframe: str,
        plugin_name: str,
        current_ohlcv: dict[str, Any],
        historical_data: Sequence[dict[str, Any]] | None = None,
        k: int = 5,
    ) -> list[tuple[FeatureVector, float]]:
        current_sig = compute_kline_signature(current_ohlcv, historical_data)
        records = self.cache.batch_query_by_plugin(symbol, timeframe, plugin_name, limit=1000)
        if not records:
            return []

        scored: list[tuple[FeatureVector, float]] = []
        for fv in records:
            if fv.kline_signature:
                hist_sig = KlineSignature(
                    open_close_ratio=_safe_float(fv.kline_signature.get("open_close_ratio")),
                    high_low_ratio=_safe_float(fv.kline_signature.get("high_low_ratio")),
                    body_ratio=_safe_float(fv.kline_signature.get("body_ratio")),
                    volume_ma_ratio=_safe_float(fv.kline_signature.get("volume_ma_ratio"), 1.0),
                    atr_ratio=_safe_float(fv.kline_signature.get("atr_ratio"), 0.02),
                )
            else:
                hist_sig = compute_kline_signature(fv.ohlcv)
            sim = cosine_similarity(current_sig.to_vector(), hist_sig.to_vector())
            scored.append((fv, sim))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(0, int(k))]

    def query_by_regime(
        self,
        symbol: str,
        timeframe: str,
        regime: str,
        limit: int = 100,
    ) -> list[FeatureVector]:
        return self.cache.batch_query_by_regime(symbol, timeframe, regime, limit=limit)

    def get_hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0

    def avg_query_time_ms(self) -> float:
        if not self._query_times_ms:
            return 0.0
        return sum(self._query_times_ms) / len(self._query_times_ms)


@dataclass
class BackfillTask:
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    plugins: list[str]
    status: str = "pending"
    progress: int = 0
    error_msg: str | None = None


class BackfillScheduler:
    def __init__(
        self,
        cache_backend: CacheStorageBackend,
        market_data_loader: MarketDataLoader,
        plugin_adapter: PluginAdapter,
    ):
        self.cache = cache_backend
        self.data_loader = market_data_loader
        self.plugin_adapter = plugin_adapter

    def create_backfill_plan(
        self,
        symbols: Sequence[str],
        timeframes: Sequence[str],
        plugins: Sequence[str],
        days_back: int = 120,
    ) -> list[BackfillTask]:
        end_date = _utc_now()
        start_date = end_date - timedelta(days=max(1, int(days_back)))
        tasks: list[BackfillTask] = []
        for symbol in symbols:
            for timeframe in timeframes:
                if timeframe not in ALLOWED_TIMEFRAMES:
                    continue
                tasks.append(
                    BackfillTask(
                        symbol=str(symbol),
                        timeframe=str(timeframe),
                        start_date=start_date,
                        end_date=end_date,
                        plugins=[str(p) for p in plugins],
                    )
                )
        return tasks

    def run_backfill(self, tasks: Sequence[BackfillTask]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "total": len(tasks),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "tasks": [],
            "start_time": _utc_iso(),
        }
        for task in tasks:
            task_result = self._run_single_task(task)
            result["tasks"].append(task_result)
            status = task_result.get("status", "failed")
            if status == "completed":
                result["completed"] += 1
            elif status == "skipped":
                result["skipped"] += 1
            else:
                result["failed"] += 1
        result["end_time"] = _utc_iso()
        return result

    def _run_single_task(self, task: BackfillTask) -> dict[str, Any]:
        task.status = "running"
        feature_count = 0
        try:
            bars = self.data_loader.load_ohlcv(
                symbol=task.symbol,
                timeframe=task.timeframe,
                start_date=task.start_date,
                end_date=task.end_date,
            )
            if not bars:
                task.status = "skipped"
                return {
                    "symbol": task.symbol,
                    "timeframe": task.timeframe,
                    "status": "skipped",
                    "reason": "no_data",
                }

            for idx, bar in enumerate(bars):
                timestamp = int(_safe_float(bar.get("timestamp"), 0.0))
                if timestamp <= 0:
                    continue
                regime = self._infer_regime(bars, idx)
                signature = compute_kline_signature(bar, bars[max(0, idx - 60) : idx + 1]).to_dict()
                for plugin_name in task.plugins:
                    features = self.plugin_adapter.compute(
                        plugin_name=plugin_name,
                        symbol=task.symbol,
                        timeframe=task.timeframe,
                        bars=bars,
                        idx=idx,
                    )
                    if not features:
                        continue
                    fv = FeatureVector(
                        symbol=task.symbol,
                        timeframe=task.timeframe,
                        plugin_name=plugin_name,
                        timestamp=timestamp,
                        features_dict=dict(features),
                        ohlcv={
                            "open": _safe_float(bar.get("open")),
                            "high": _safe_float(bar.get("high")),
                            "low": _safe_float(bar.get("low")),
                            "close": _safe_float(bar.get("close")),
                            "volume": _safe_float(bar.get("volume")),
                        },
                        kline_signature=signature,
                        version="v1.0",
                        regime_label=regime,
                    )
                    if self.cache.write_feature_vector(fv):
                        feature_count += 1
                if (idx + 1) % 10 == 0:
                    task.progress = int((idx + 1) * 100 / max(len(bars), 1))

            task.status = "completed"
            task.progress = 100
            return {
                "symbol": task.symbol,
                "timeframe": task.timeframe,
                "status": "completed",
                "feature_count": feature_count,
                "bar_count": len(bars),
            }
        except Exception as exc:
            task.status = "failed"
            task.error_msg = str(exc)
            return {
                "symbol": task.symbol,
                "timeframe": task.timeframe,
                "status": "failed",
                "error": str(exc),
                "feature_count": feature_count,
            }

    @staticmethod
    def _infer_regime(bars: Sequence[dict[str, Any]], idx: int, lookback: int = 48) -> str:
        start = max(0, idx - lookback + 1)
        window = list(bars[start : idx + 1])
        if len(window) < 20:
            return "transition"
        closes = [_safe_float(b.get("close")) for b in window]
        x_mean = (len(closes) - 1) / 2.0
        y_mean = sum(closes) / max(len(closes), 1)
        num = 0.0
        den = 0.0
        for i, close in enumerate(closes):
            dx = i - x_mean
            num += dx * (close - y_mean)
            den += dx * dx
        slope = num / den if den > 1e-12 else 0.0
        atr = compute_atr(window, 14)
        slope_norm = abs(slope) / max(atr, 1e-8)
        if slope_norm >= 0.8:
            return "trend"
        if slope_norm <= 0.3:
            return "range"
        return "transition"


def compute_mfe_mae(
    entry_price: float,
    entry_signal: str,
    subsequent_bars: Sequence[dict[str, Any]],
    lookback_bars: int = 20,
) -> MFEMAEResult:
    base = _safe_float(entry_price)
    if base <= 1e-12 or not subsequent_bars:
        return MFEMAEResult(0.0, 0.0, 0, 0, base, base)

    signal = str(entry_signal).upper()
    mfe_price = base
    mae_price = base
    mfe_bars = 0
    mae_bars = 0
    for i, bar in enumerate(list(subsequent_bars)[: max(1, int(lookback_bars))]):
        high = _safe_float(bar.get("high"), base)
        low = _safe_float(bar.get("low"), base)
        if signal == "SELL":
            if low < mfe_price:
                mfe_price = low
                mfe_bars = i + 1
            if high > mae_price:
                mae_price = high
                mae_bars = i + 1
        else:
            if high > mfe_price:
                mfe_price = high
                mfe_bars = i + 1
            if low < mae_price:
                mae_price = low
                mae_bars = i + 1

    mfe_pct = abs((mfe_price - base) / base) * 100.0
    mae_pct = abs((mae_price - base) / base) * 100.0
    return MFEMAEResult(
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        mfe_bars=mfe_bars,
        mae_bars=mae_bars,
        mfe_price=mfe_price,
        mae_price=mae_price,
    )


class CalibrationMap:
    def __init__(self):
        self.map: dict[tuple[float, str], dict[str, float]] = {}

    @staticmethod
    def _bucket(strength: float) -> float:
        x = max(0.0, min(1.0, _safe_float(strength)))
        return math.floor(x * 5.0) / 5.0

    def build_from_samples(self, samples: Sequence[dict[str, Any]]) -> None:
        grouped: dict[tuple[float, str], list[tuple[float, float]]] = {}
        for row in samples:
            strength = self._bucket(_safe_float(row.get("feature_strength"), 0.0))
            regime = str(row.get("regime", "unknown"))
            mfe = _safe_float(row.get("mfe_pct"), 0.0)
            mae = _safe_float(row.get("mae_pct"), 0.0)
            grouped.setdefault((strength, regime), []).append((mfe, mae))

        out: dict[tuple[float, str], dict[str, float]] = {}
        for key, values in grouped.items():
            if not values:
                continue
            mfes = [v[0] for v in values]
            maes = [v[1] for v in values]
            out[key] = {
                "expected_mfe": sum(mfes) / len(mfes),
                "expected_mae": sum(maes) / len(maes),
                "sample_count": float(len(values)),
            }
        self.map = out

    def lookup(self, strength: float, regime: str) -> dict[str, float] | None:
        return self.map.get((self._bucket(strength), str(regime)))

    def validate_feature(
        self,
        feature_strength: float,
        regime: str,
        actual_mfe: float,
        actual_mae: float,
    ) -> dict[str, Any]:
        expected = self.lookup(feature_strength, regime)
        if not expected:
            return {"valid": False, "reason": "no_calibration_data"}

        exp_mfe = max(expected.get("expected_mfe", 0.0), 1e-6)
        exp_mae = max(expected.get("expected_mae", 0.0), 1e-6)
        mfe_error = abs(_safe_float(actual_mfe) - exp_mfe) / exp_mfe
        mae_error = abs(_safe_float(actual_mae) - exp_mae) / exp_mae
        valid = mfe_error < 0.2 and mae_error < 0.2
        return {
            "valid": valid,
            "mfe_error_pct": mfe_error * 100.0,
            "mae_error_pct": mae_error * 100.0,
            "expected_mfe": exp_mfe,
            "expected_mae": exp_mae,
            "actual_mfe": _safe_float(actual_mfe),
            "actual_mae": _safe_float(actual_mae),
        }


def adf_test(series: Sequence[float], name: str = "") -> dict[str, Any]:
    values = [float(x) for x in series if x is not None]
    if len(values) < 10:
        return {
            "test_name": "ADF",
            "series_name": name,
            "available": False,
            "reason": "insufficient_samples",
            "is_stationary": False,
        }
    try:
        from statsmodels.tsa.stattools import adfuller  # type: ignore

        result = adfuller(values, autolag="AIC")
        p_value = float(result[1])
        return {
            "test_name": "ADF",
            "series_name": name,
            "available": True,
            "statistic": float(result[0]),
            "p_value": p_value,
            "is_stationary": p_value < 0.05,
            "critical_values": dict(result[4]),
        }
    except Exception as exc:
        return {
            "test_name": "ADF",
            "series_name": name,
            "available": False,
            "reason": type(exc).__name__,
            "is_stationary": False,
        }


def kpss_test(series: Sequence[float], name: str = "") -> dict[str, Any]:
    values = [float(x) for x in series if x is not None]
    if len(values) < 10:
        return {
            "test_name": "KPSS",
            "series_name": name,
            "available": False,
            "reason": "insufficient_samples",
            "is_stationary": False,
        }
    try:
        from statsmodels.tsa.stattools import kpss  # type: ignore

        result = kpss(values, regression="c", nlags="auto")
        p_value = float(result[1])
        return {
            "test_name": "KPSS",
            "series_name": name,
            "available": True,
            "statistic": float(result[0]),
            "p_value": p_value,
            "is_stationary": p_value > 0.05,
            "critical_values": dict(result[3]),
        }
    except Exception as exc:
        return {
            "test_name": "KPSS",
            "series_name": name,
            "available": False,
            "reason": type(exc).__name__,
            "is_stationary": False,
        }


def regime_split_test(
    feature_series: Sequence[float],
    regime_labels: Sequence[str],
) -> dict[str, Any]:
    pairs = [(float(v), str(r)) for v, r in zip(feature_series, regime_labels)]
    by_regime: dict[str, list[float]] = {}
    for value, regime in pairs:
        by_regime.setdefault(regime, []).append(value)

    results: dict[str, Any] = {}
    for regime, values in by_regime.items():
        if len(values) < 10:
            continue
        mean = sum(values) / len(values)
        var = sum((x - mean) ** 2 for x in values) / len(values)
        std = math.sqrt(max(var, 0.0))
        results[regime] = {
            "mean": mean,
            "std": std,
            "min": min(values),
            "max": max(values),
            "sample_count": len(values),
            "adf_test": adf_test(values, f"{regime}_feature"),
            "kpss_test": kpss_test(values, f"{regime}_feature"),
        }

    if "trend" in results and "range" in results:
        mean_diff = abs(results["trend"]["mean"] - results["range"]["mean"])
        std_diff = abs(results["trend"]["std"] - results["range"]["std"])
        results["regime_stability"] = {
            "mean_diff": mean_diff,
            "std_diff": std_diff,
            "is_stable": mean_diff < 0.1 and std_diff < 0.1,
        }
    return results


def compute_feature_stability_score(regime_test_results: dict[str, Any]) -> float:
    stability = regime_test_results.get("regime_stability")
    if not isinstance(stability, dict):
        return 0.5
    mean_diff = _safe_float(stability.get("mean_diff"), 0.5)
    std_diff = _safe_float(stability.get("std_diff"), 0.5)
    mean_score = max(0.0, 1.0 - mean_diff * 10.0)
    std_score = max(0.0, 1.0 - std_diff * 10.0)
    return (mean_score + std_score) / 2.0


class VersionManager:
    def __init__(self, version_file: str = os.path.join("state", "cache", "key004_versions.json")):
        self.version_file = version_file
        self.versions: dict[str, CacheVersion] = self._load_versions()

    def _load_versions(self) -> dict[str, CacheVersion]:
        data = _safe_json_loads(self._read_file(), {"versions": []})
        out: dict[str, CacheVersion] = {}
        for row in data.get("versions", []):
            try:
                version = CacheVersion(
                    version_id=str(row["version_id"]),
                    timestamp=str(row["timestamp"]),
                    plugin_name=str(row["plugin_name"]),
                    changes=dict(row.get("changes", {})),
                    status=str(row.get("status", "pending_review")),
                    description=str(row.get("description", "")),
                )
                out[version.version_id] = version
            except Exception:
                continue
        return out

    def _read_file(self) -> str | None:
        try:
            with open(self.version_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def _save_versions(self) -> None:
        parent = os.path.dirname(self.version_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {
            "versions": [
                {
                    "version_id": v.version_id,
                    "timestamp": v.timestamp,
                    "plugin_name": v.plugin_name,
                    "changes": v.changes,
                    "status": v.status,
                    "description": v.description,
                }
                for v in self.versions.values()
            ]
        }
        with open(self.version_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)

    def create_version(
        self,
        plugin_name: str,
        changes: dict[str, Any],
        description: str = "",
    ) -> str:
        existing = [v for v in self.versions if v.startswith(f"{plugin_name}_v")]
        version_id = f"{plugin_name}_v{len(existing) + 1}.0"
        self.versions[version_id] = CacheVersion(
            version_id=version_id,
            timestamp=_utc_iso(),
            plugin_name=plugin_name,
            changes=dict(changes),
            status="pending_review",
            description=description,
        )
        self._save_versions()
        return version_id

    def compare_versions(self, version_id1: str, version_id2: str) -> dict[str, Any]:
        v1 = self.versions.get(version_id1)
        v2 = self.versions.get(version_id2)
        if not v1 or not v2:
            return {"error": "version_not_found"}
        return {
            "version1": version_id1,
            "version2": version_id2,
            "v1_timestamp": v1.timestamp,
            "v2_timestamp": v2.timestamp,
            "v1_changes": v1.changes,
            "v2_changes": v2.changes,
            "diff": {
                "added_diff": sorted(set(v2.changes.get("added", [])) - set(v1.changes.get("added", []))),
                "removed_diff": sorted(
                    set(v2.changes.get("removed", [])) - set(v1.changes.get("removed", []))
                ),
                "modified_diff": sorted(
                    set(v2.changes.get("modified", [])) - set(v1.changes.get("modified", []))
                ),
            },
        }

    def rollback_version(self, target_version_id: str) -> bool:
        if target_version_id not in self.versions:
            return False
        for version in self.versions.values():
            if version.status == "active":
                version.status = "deprecated"
        self.versions[target_version_id].status = "active"
        self._save_versions()
        return True

    def activate_if_approved(self, version_id: str, delta_result: DeltaEvalResult) -> bool:
        if version_id not in self.versions:
            return False
        if delta_result.status != "approved":
            self.versions[version_id].status = "rejected"
            self._save_versions()
            return False
        for version in self.versions.values():
            if version.status == "active":
                version.status = "deprecated"
        self.versions[version_id].status = "active"
        self._save_versions()
        return True


class CacheFallbackManager:
    def __init__(
        self,
        cache_engine: CacheQueryEngine,
        cache_backend: CacheStorageBackend,
        realtime_compute_fn: Callable[[str, str, str, Sequence[dict[str, Any]]], dict[str, Any]],
    ):
        self.cache = cache_engine
        self.cache_backend = cache_backend
        self.realtime_compute = realtime_compute_fn
        self.fallback_count = 0
        self.fallback_reasons: dict[str, int] = {}
        self.fallback_success = 0
        self.fallback_total = 0

    def get_feature_with_fallback(
        self,
        symbol: str,
        timeframe: str,
        plugin_name: str,
        timestamp: int,
        ohlcv_data: Sequence[dict[str, Any]],
        timeout_ms: int = 100,
    ) -> dict[str, Any]:
        try:
            start = time.perf_counter()
            fv = self.cache.query_exact(symbol, timeframe, plugin_name, timestamp)
            elapsed = (time.perf_counter() - start) * 1000.0
            if fv and elapsed < timeout_ms:
                return dict(fv.features_dict)
            if fv and elapsed >= timeout_ms:
                self._record_fallback("cache_timeout")
            elif not fv:
                self._record_fallback("cache_miss")
        except Exception:
            self._record_fallback("cache_error")

        self.fallback_total += 1
        try:
            computed = self.realtime_compute(symbol, timeframe, plugin_name, ohlcv_data)
            if not computed:
                return {}
            self.fallback_success += 1
            self._async_cache_write(symbol, timeframe, plugin_name, timestamp, computed, ohlcv_data)
            return dict(computed)
        except Exception:
            return {}

    def _record_fallback(self, reason: str) -> None:
        self.fallback_count += 1
        self.fallback_reasons[reason] = self.fallback_reasons.get(reason, 0) + 1

    def _async_cache_write(
        self,
        symbol: str,
        timeframe: str,
        plugin_name: str,
        timestamp: int,
        features: dict[str, Any],
        ohlcv_data: Sequence[dict[str, Any]],
    ) -> None:
        def write_task() -> None:
            try:
                if not ohlcv_data:
                    return
                last_bar = ohlcv_data[-1]
                signature = compute_kline_signature(last_bar, ohlcv_data).to_dict()
                fv = FeatureVector(
                    symbol=symbol,
                    timeframe=timeframe,
                    plugin_name=plugin_name,
                    timestamp=int(timestamp),
                    features_dict=dict(features),
                    ohlcv={
                        "open": _safe_float(last_bar.get("open")),
                        "high": _safe_float(last_bar.get("high")),
                        "low": _safe_float(last_bar.get("low")),
                        "close": _safe_float(last_bar.get("close")),
                        "volume": _safe_float(last_bar.get("volume")),
                    },
                    kline_signature=signature,
                    regime_label="unknown",
                )
                self.cache_backend.write_feature_vector(fv)
            except Exception:
                return

        threading.Thread(target=write_task, daemon=True).start()

    def get_fallback_stats(self) -> dict[str, Any]:
        total_queries = self.cache.hit_count + self.cache.miss_count + self.fallback_count
        fallback_rate = self.fallback_count / total_queries if total_queries > 0 else 0.0
        success_rate = self.fallback_success / self.fallback_total if self.fallback_total > 0 else 1.0
        return {
            "total_fallbacks": self.fallback_count,
            "reasons": dict(self.fallback_reasons),
            "fallback_rate": fallback_rate,
            "fallback_success_rate": success_rate,
        }


class KEY004DeltaEvaluator:
    def __init__(
        self,
        approval_threshold_icir: float = 0.10,
        approval_threshold_win_rate: float = 0.0,
        min_sample_n: int = 50,
        min_regime_stability: float = 0.7,
    ):
        self.approval_threshold_icir = float(approval_threshold_icir)
        self.approval_threshold_win_rate = float(approval_threshold_win_rate)
        self.min_sample_n = int(min_sample_n)
        self.min_regime_stability = float(min_regime_stability)

    def run_delta_eval(self, request: DeltaEvalRequest) -> DeltaEvalResult:
        baseline_icir = _safe_float(request.baseline_metrics.get("icir"))
        baseline_wr = _safe_float(request.baseline_metrics.get("win_rate"))
        baseline_n = int(_safe_float(request.baseline_metrics.get("sample_n"), 0.0))
        candidate_icir = _safe_float(request.candidate_metrics.get("icir"))
        candidate_wr = _safe_float(request.candidate_metrics.get("win_rate"))
        candidate_n = int(_safe_float(request.candidate_metrics.get("sample_n"), 0.0))

        delta_icir = candidate_icir - baseline_icir
        delta_win_rate = candidate_wr - baseline_wr
        delta_sample_n = candidate_n - baseline_n
        regime_stability = self._check_regime_stability(request.regime_split)

        passed = (
            delta_icir > self.approval_threshold_icir
            and delta_win_rate >= self.approval_threshold_win_rate
            and candidate_n >= self.min_sample_n
            and regime_stability >= self.min_regime_stability
            and "trend" in request.regime_split
            and "range" in request.regime_split
        )

        if passed:
            status = "approved"
            approval_reason = (
                f"delta_icir={delta_icir:.3f} > {self.approval_threshold_icir:.3f}; "
                f"delta_win_rate={delta_win_rate:.3f} >= {self.approval_threshold_win_rate:.3f}; "
                f"sample_n={candidate_n} >= {self.min_sample_n}; "
                f"regime_stability={regime_stability:.2f}"
            )
            rejection_reason = ""
        else:
            status = "rejected"
            approval_reason = ""
            rejection_reason = self._build_rejection_reason(
                delta_icir,
                delta_win_rate,
                candidate_n,
                regime_stability,
                request.regime_split,
            )

        return DeltaEvalResult(
            request_id=f"{request.feature_name}_{request.candidate_version}",
            status=status,
            delta_icir=delta_icir,
            delta_win_rate=delta_win_rate,
            delta_sample_n=delta_sample_n,
            regime_stability=regime_stability,
            approval_reason=approval_reason,
            rejection_reason=rejection_reason,
        )

    @staticmethod
    def _check_regime_stability(regime_split: dict[str, dict[str, float]]) -> float:
        trend = regime_split.get("trend", {})
        range_ = regime_split.get("range", {})
        trend_icir = abs(_safe_float(trend.get("icir"), 0.0))
        range_icir = abs(_safe_float(range_.get("icir"), 0.0))
        base = max(trend_icir, range_icir)
        if base <= 1e-9:
            return 0.5
        return max(0.0, 1.0 - abs(trend_icir - range_icir) / base)

    def _build_rejection_reason(
        self,
        delta_icir: float,
        delta_win_rate: float,
        sample_n: int,
        regime_stability: float,
        regime_split: dict[str, dict[str, float]],
    ) -> str:
        reasons: list[str] = []
        if delta_icir <= self.approval_threshold_icir:
            reasons.append(f"delta_icir={delta_icir:.3f} <= {self.approval_threshold_icir:.3f}")
        if delta_win_rate < self.approval_threshold_win_rate:
            reasons.append(
                f"delta_win_rate={delta_win_rate:.3f} < {self.approval_threshold_win_rate:.3f}"
            )
        if sample_n < self.min_sample_n:
            reasons.append(f"sample_n={sample_n} < {self.min_sample_n}")
        if regime_stability < self.min_regime_stability:
            reasons.append(
                f"regime_stability={regime_stability:.2f} < {self.min_regime_stability:.2f}"
            )
        if "trend" not in regime_split or "range" not in regime_split:
            reasons.append("regime_coverage_missing_trend_or_range")
        return "; ".join(reasons)


def run_delta_eval(request: DeltaEvalRequest) -> DeltaEvalResult:
    evaluator = KEY004DeltaEvaluator()
    return evaluator.run_delta_eval(request)


class CacheMonitor:
    def __init__(self, cache_engine: CacheQueryEngine, fallback_manager: CacheFallbackManager):
        self.cache = cache_engine
        self.fallback = fallback_manager
        self.metrics_history: list[CacheMetrics] = []

    def collect_metrics(self) -> CacheMetrics:
        hit_rate = self.cache.get_hit_rate()
        miss_rate = 1.0 - hit_rate
        fallback_stats = self.fallback.get_fallback_stats()
        fallback_rate = _safe_float(fallback_stats.get("fallback_rate"), 0.0)
        feature_drift = self._compute_feature_drift()
        version_distribution = self.cache.cache.version_distribution()
        avg_query_time_ms = self.cache.avg_query_time_ms()
        metrics = CacheMetrics(
            timestamp=_utc_iso(),
            hit_rate=hit_rate,
            miss_rate=miss_rate,
            fallback_rate=fallback_rate,
            feature_drift=feature_drift,
            version_distribution=version_distribution,
            avg_query_time_ms=avg_query_time_ms,
        )
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > 60:
            self.metrics_history = self.metrics_history[-30:]
        return metrics

    def _compute_feature_drift(self) -> dict[str, float]:
        out: dict[str, float] = {}
        plugins = self._known_plugins(limit=100)
        now = _utc_now()
        recent_cutoff = now - timedelta(days=7)
        base_cutoff = now - timedelta(days=37)
        for plugin in plugins:
            vectors = self.cache.cache.list_plugin_feature_vectors(plugin, limit=3000)
            if len(vectors) < 20:
                continue
            recent_vals: list[float] = []
            base_vals: list[float] = []
            for fv in vectors:
                value = self._extract_primary_numeric(fv.features_dict)
                if value is None:
                    continue
                try:
                    ts_dt = datetime.fromtimestamp(int(fv.timestamp), tz=UTC)
                except Exception:
                    ts_dt = _parse_iso(fv.created_at)
                if ts_dt >= recent_cutoff:
                    recent_vals.append(value)
                elif ts_dt >= base_cutoff:
                    base_vals.append(value)
            if len(recent_vals) < 5 or len(base_vals) < 10:
                continue
            recent_mean = sum(recent_vals) / len(recent_vals)
            base_mean = sum(base_vals) / len(base_vals)
            denom = max(abs(base_mean), 1e-6)
            out[plugin] = abs(recent_mean - base_mean) / denom
        return out

    def _known_plugins(self, limit: int = 100) -> list[str]:
        try:
            with self.cache.cache._connect() as conn:  # noqa: SLF001
                rows = conn.execute(
                    "SELECT plugin_name, COUNT(*) AS c FROM feature_vectors GROUP BY plugin_name ORDER BY c DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return [str(r["plugin_name"]) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _extract_primary_numeric(features: dict[str, Any]) -> float | None:
        preferred = ("strength", "confidence", "score", "position_pct", "atr_ratio")
        for key in preferred:
            value = features.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        for value in features.values():
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def check_alerts(self, metrics: CacheMetrics) -> list[str]:
        alerts: list[str] = []
        if metrics.hit_rate < 0.90:
            alerts.append(f"[ALERT] Cache hit rate low: {metrics.hit_rate:.2%}")
        if metrics.fallback_rate > 0.05:
            alerts.append(f"[ALERT] Fallback rate high: {metrics.fallback_rate:.2%}")
        for plugin, drift in metrics.feature_drift.items():
            if drift > 0.2:
                alerts.append(f"[ALERT] Feature drift high for {plugin}: {drift:.3f}")
        return alerts

    def generate_daily_report(self) -> str:
        if not self.metrics_history:
            return "No metrics collected"
        latest = self.metrics_history[-1]
        payload = {
            "timestamp": latest.timestamp,
            "hit_rate": round(latest.hit_rate, 6),
            "miss_rate": round(latest.miss_rate, 6),
            "fallback_rate": round(latest.fallback_rate, 6),
            "feature_drift": latest.feature_drift,
            "version_distribution": latest.version_distribution,
            "avg_query_time_ms": round(latest.avg_query_time_ms, 4),
            "alerts": self.check_alerts(latest),
        }
        return json.dumps(payload, ensure_ascii=True, indent=2)

    def generate_weekly_report(self) -> str:
        if len(self.metrics_history) < 7:
            return "Insufficient data for weekly report"
        weekly = self.metrics_history[-7:]
        avg_hit_rate = sum(m.hit_rate for m in weekly) / len(weekly)
        avg_fallback_rate = sum(m.fallback_rate for m in weekly) / len(weekly)
        trend = "improving" if avg_hit_rate > 0.95 else "stable" if avg_hit_rate > 0.90 else "degrading"
        payload = {
            "period_start": weekly[0].timestamp,
            "period_end": weekly[-1].timestamp,
            "avg_hit_rate": round(avg_hit_rate, 6),
            "avg_fallback_rate": round(avg_fallback_rate, 6),
            "trend": trend,
        }
        return json.dumps(payload, ensure_ascii=True, indent=2)


__all__ = [
    "ALLOWED_HORIZONS",
    "ALLOWED_TIMEFRAMES",
    "FeatureVector",
    "CacheMetadata",
    "KlineSignature",
    "MFEMAEResult",
    "CacheVersion",
    "DeltaEvalRequest",
    "DeltaEvalResult",
    "CacheMetrics",
    "MarketDataLoader",
    "PluginAdapter",
    "CacheStorageBackend",
    "CacheQueryEngine",
    "BackfillTask",
    "BackfillScheduler",
    "compute_atr",
    "compute_kline_signature",
    "cosine_similarity",
    "aggregate_similar_features",
    "compute_mfe_mae",
    "CalibrationMap",
    "adf_test",
    "kpss_test",
    "regime_split_test",
    "compute_feature_stability_score",
    "VersionManager",
    "CacheFallbackManager",
    "KEY004DeltaEvaluator",
    "run_delta_eval",
    "CacheMonitor",
]
