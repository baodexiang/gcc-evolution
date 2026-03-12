from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

THRESHOLD = 0.50
MIN_SAMPLE = 1
WARNING_THRESHOLD = 0.50
RETENTION_DAYS = 7
WINDOW_4H = 4
WINDOW_WEEK = 24 * 7
OBSERVE_ONLY = False


@dataclass
class ValidSignal:
    signal_id: str
    timestamp: str
    direction: str
    source: str
    symbol: str = ""
    price: float = 0.0

@dataclass
class DirectionResult:
    direction: str
    reason: str
    buy_ratio_4h: float
    sell_ratio_4h: float
    buy_ratio_week: float
    sell_ratio_week: float
    sample_4h: int
    sample_week: int


class SignalDirectionFilter:
    def __init__(self, data_dir: str = ".GCC/signal_filter") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.valid_path = self.data_dir / "valid_signals.jsonl"
        self.filtered_path = self.data_dir / "filtered_signals.jsonl"
        self.direction_log_path = self.data_dir / "direction_log.jsonl"
        self.mode_state_path = self.data_dir / "mode_state.json"
        # Runtime mode lives on the instance and is persisted for dashboard/audit readers.
        self.observe_only = bool(OBSERVE_ONLY)
        self._sync_mode_state()

    def _sync_mode_state(self) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "observe_only": bool(self.observe_only),
            "mode": "OBSERVE" if self.observe_only else "ENFORCE",
        }
        try:
            self.mode_state_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def set_observe_only(self, observe_only: bool) -> None:
        self.observe_only = bool(observe_only)
        self._sync_mode_state()

    def get_mode(self) -> str:
        return "OBSERVE" if self.observe_only else "ENFORCE"

    def _parse_ts(self, ts: str) -> datetime:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _get_week_start(self) -> datetime:
        """
        计算本周周一 08:00（本地时间）并转换为 UTC。
        若当前时间早于本周一 08:00，则返回当前时间（等价于本周窗口为空）。
        """
        now_local = datetime.now().astimezone()
        days_since_monday = now_local.weekday()  # 0=Monday
        monday = now_local - timedelta(days=days_since_monday)
        week_start_local = monday.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_local < week_start_local:
            return now_local.astimezone(timezone.utc)
        return week_start_local.astimezone(timezone.utc)

    def _append_jsonl(self, path: Path, obj: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _rewrite_jsonl(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _cleanup_old_signals(self) -> None:
        signals = self._read_jsonl(self.valid_path)
        if not signals:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        kept = [s for s in signals if self._parse_ts(s.get("timestamp", "1970-01-01T00:00:00+00:00")) >= cutoff]
        if len(kept) != len(signals):
            self._rewrite_jsonl(self.valid_path, kept)

    def weekly_reset(self) -> bool:
        """每周一NY 8AM清空信号数据，恢复中性方向。返回True表示已重置。"""
        reset_marker = self.data_dir / "last_weekly_reset.txt"
        from zoneinfo import ZoneInfo
        now_ny = datetime.now(ZoneInfo("America/New_York"))
        if now_ny.weekday() != 0:  # 0=Monday
            return False
        if now_ny.hour < 8:
            return False
        # 本周一已重置过？
        reset_date = now_ny.strftime("%Y-%m-%d")
        if reset_marker.exists():
            last = reset_marker.read_text(encoding="utf-8").strip()
            if last == reset_date:
                return False
        # 清空信号数据
        if self.valid_path.exists():
            self.valid_path.write_text("", encoding="utf-8")
        if self.filtered_path.exists():
            self.filtered_path.write_text("", encoding="utf-8")
        reset_marker.write_text(reset_date, encoding="utf-8")
        return True

    def record_signal(self, signal: ValidSignal) -> None:
        self._cleanup_old_signals()
        obj = asdict(signal)
        obj["direction"] = obj.get("direction", "").lower()
        self._append_jsonl(self.valid_path, obj)

    def _make_result(
        self,
        direction: str,
        reason: str,
        buy_ratio_4h: float,
        sell_ratio_4h: float,
        buy_ratio_week: float,
        sell_ratio_week: float,
        sample_4h: int,
        sample_week: int,
    ) -> DirectionResult:
        result = DirectionResult(
            direction=direction,
            reason=reason,
            buy_ratio_4h=buy_ratio_4h,
            sell_ratio_4h=sell_ratio_4h,
            buy_ratio_week=buy_ratio_week,
            sell_ratio_week=sell_ratio_week,
            sample_4h=sample_4h,
            sample_week=sample_week,
        )
        self._append_jsonl(
            self.direction_log_path,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "direction": result.direction,
                "reason": result.reason,
                "buy_ratio_4h": result.buy_ratio_4h,
                "sell_ratio_4h": result.sell_ratio_4h,
                "buy_ratio_week": result.buy_ratio_week,
                "sell_ratio_week": result.sell_ratio_week,
                "sample_4h": result.sample_4h,
                "sample_week": result.sample_week,
            },
        )
        return result

    def evaluate_direction(self) -> DirectionResult:
        self._cleanup_old_signals()
        signals = self._read_jsonl(self.valid_path)
        now = datetime.now(timezone.utc)
        cutoff_4h = now - timedelta(hours=WINDOW_4H)
        cutoff_week = self._get_week_start()

        signals_4h = [s for s in signals if self._parse_ts(s.get("timestamp", "1970-01-01T00:00:00+00:00")) >= cutoff_4h]
        signals_week = [s for s in signals if self._parse_ts(s.get("timestamp", "1970-01-01T00:00:00+00:00")) >= cutoff_week]

        count_4h = len(signals_4h)
        count_week = len(signals_week)
        buy_4h = sum(1 for s in signals_4h if s.get("direction") == "buy")
        buy_week = sum(1 for s in signals_week if s.get("direction") == "buy")
        sell_4h = count_4h - buy_4h
        sell_week = count_week - buy_week

        if buy_4h < MIN_SAMPLE or sell_4h < MIN_SAMPLE:
            return self._make_result(
                direction="NO_ANSWER",
                reason=f"4h 样本不足（Buy {buy_4h} / Sell {sell_4h}，各需至少 {MIN_SAMPLE} 条）",
                buy_ratio_4h=0.0,
                sell_ratio_4h=0.0,
                buy_ratio_week=0.0,
                sell_ratio_week=0.0,
                sample_4h=count_4h,
                sample_week=count_week,
            )

        if buy_week < MIN_SAMPLE or sell_week < MIN_SAMPLE:
            return self._make_result(
                direction="NO_ANSWER",
                reason=f"本周样本不足（Buy {buy_week} / Sell {sell_week}，各需至少 {MIN_SAMPLE} 条）",
                buy_ratio_4h=0.0,
                sell_ratio_4h=0.0,
                buy_ratio_week=0.0,
                sell_ratio_week=0.0,
                sample_4h=count_4h,
                sample_week=count_week,
            )

        buy_ratio_4h = buy_4h / count_4h if count_4h else 0.0
        sell_ratio_4h = sell_4h / count_4h if count_4h else 0.0
        buy_ratio_week = buy_week / count_week if count_week else 0.0
        sell_ratio_week = sell_week / count_week if count_week else 0.0

        if buy_ratio_4h >= THRESHOLD and buy_ratio_week >= THRESHOLD:
            direction = "BUY_DOMINANT"
            reason = f"BUY占优（4h={buy_ratio_4h:.1%}, week={buy_ratio_week:.1%}）"
        elif sell_ratio_4h >= THRESHOLD and sell_ratio_week >= THRESHOLD:
            direction = "SELL_DOMINANT"
            reason = f"SELL占优（4h={sell_ratio_4h:.1%}, week={sell_ratio_week:.1%}）"
        else:
            direction = "NEUTRAL"
            reason = "方向不一致，维持中性"

        return self._make_result(
            direction=direction,
            reason=reason,
            buy_ratio_4h=buy_ratio_4h,
            sell_ratio_4h=sell_ratio_4h,
            buy_ratio_week=buy_ratio_week,
            sell_ratio_week=sell_ratio_week,
            sample_4h=count_4h,
            sample_week=count_week,
        )

    def filter_signal(self, signal: ValidSignal, direction_result: DirectionResult) -> bool:
        signal_dir = signal.direction.lower()
        would_block = (
            (direction_result.direction == "BUY_DOMINANT" and signal_dir == "sell")
            or (direction_result.direction == "SELL_DOMINANT" and signal_dir == "buy")
        )
        blocked = would_block and (not self.observe_only)

        if would_block:
            self._append_jsonl(
                self.filtered_path,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "signal_id": signal.signal_id,
                    "source": signal.source,
                    "direction": signal_dir,
                    "symbol": signal.symbol,
                    "price": signal.price,
                    "result": direction_result.direction,
                    "reason": direction_result.reason,
                    "observe_only": self.observe_only,
                    "would_block": True,
                    "blocked": blocked,
                    "outcome": "pending",
                    "buy_ratio_4h": direction_result.buy_ratio_4h,
                    "buy_ratio_week": direction_result.buy_ratio_week,
                    "sell_ratio_4h": direction_result.sell_ratio_4h,
                    "sell_ratio_week": direction_result.sell_ratio_week,
                },
            )

        return not blocked

    def backfill_outcomes(self, price_map: Dict[str, float]) -> int:
        """
        4H 反事实价格回填: 对 outcome=pending 且已过 4H 的 block 记录，
        根据 price_map 中该 symbol 当前价格判定 correct/incorrect。

        判定逻辑:
        - Block 了 SELL + 价格涨了 → correct（避免了错卖）
        - Block 了 SELL + 价格跌了 → incorrect（错过了正确卖出）
        - Block 了 BUY + 价格跌了 → correct（避免了错买）
        - Block 了 BUY + 价格涨了 → incorrect（错过了正确买入）

        Returns: 本次回填的记录数。
        """
        rows = self._read_jsonl(self.filtered_path)
        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=4)
        updated = 0

        for row in rows:
            if row.get("outcome") != "pending":
                continue
            block_price = row.get("price", 0)
            sym = row.get("symbol", "")
            if not sym or not block_price:
                continue
            ts = self._parse_ts(row.get("timestamp", "1970-01-01T00:00:00+00:00"))
            if ts > cutoff:
                continue  # 不满4H，跳过
            current_price = price_map.get(sym)
            if current_price is None:
                continue
            change_pct = (current_price - block_price) / block_price if block_price else 0.0
            sig_dir = row.get("direction", "")
            if sig_dir == "sell":
                outcome = "correct" if change_pct > 0 else "incorrect"
            elif sig_dir == "buy":
                outcome = "correct" if change_pct < 0 else "incorrect"
            else:
                continue
            row["outcome"] = outcome
            row["backfill_price"] = current_price
            row["backfill_ts"] = now.isoformat()
            row["price_change_pct"] = round(change_pct * 100, 2)
            updated += 1

        if updated:
            self._rewrite_jsonl(self.filtered_path, rows)
        return updated
