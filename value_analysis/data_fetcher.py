from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import importlib
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class QuotaBudget:
    daily_limit: int = 250
    used: int = 0

    def consume(self, units: int = 1) -> bool:
        if self.used + units > self.daily_limit:
            return False
        self.used += units
        return True


@dataclass
class CacheEntry:
    value: Dict[str, Any]
    expires_at: datetime


@dataclass
class ValueDataCache:
    entries: Dict[str, CacheEntry] = field(default_factory=dict)

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        self.entries[key] = CacheEntry(
            value=value,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self.entries.get(key)
        if not entry:
            return None
        if datetime.now(timezone.utc) > entry.expires_at:
            self.entries.pop(key, None)
            return None
        return entry.value


def mark_degraded(missing_ratio: float) -> str:
    return "degraded" if missing_ratio > 0.40 else "ok"


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _linear_low_better(value: Optional[float], good: float, bad: float) -> float:
    if value is None:
        return 0.0
    x = float(value)
    if x <= good:
        return 2.0
    if x >= bad:
        return -2.0
    ratio = (x - good) / (bad - good)
    return _clip(2.0 - 4.0 * ratio, -2.0, 2.0)


def _linear_high_better(value: Optional[float], good: float, bad: float) -> float:
    if value is None:
        return 0.0
    x = float(value)
    if x >= good:
        return 2.0
    if x <= bad:
        return -2.0
    ratio = (x - bad) / (good - bad)
    return _clip(-2.0 + 4.0 * ratio, -2.0, 2.0)


def _read_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        payload = resp.read().decode("utf-8")
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("expected JSON object")
    return raw


def _nested_value(obj: Dict[str, Any], *path: str) -> Optional[float]:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    if isinstance(cur, (int, float)):
        return float(cur)
    if isinstance(cur, dict):
        raw = cur.get("raw")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _compute_returns(closes: list[float]) -> Dict[str, Optional[float]]:
    def _ret(days: int) -> Optional[float]:
        if len(closes) <= days:
            return None
        prev = closes[-(days + 1)]
        now = closes[-1]
        if prev == 0:
            return None
        return now / prev - 1.0

    return {
        "ret_1m": _ret(21),
        "ret_3m": _ret(63),
        "ret_6m": _ret(126),
    }


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _pick_first_numeric(row: Dict[str, Any], keys: list[str]) -> Optional[float]:
    for key in keys:
        val = _safe_float(row.get(key))
        if val is not None:
            return val
    return None


def _openbb_client() -> Any:
    try:
        module = importlib.import_module("openbb")
    except Exception as exc:
        raise RuntimeError("openbb package not available; install with pip install openbb") from exc
    obb = getattr(module, "obb", None)
    if obb is None:
        raise RuntimeError("openbb package loaded but obb client is unavailable")
    return obb


def _openbb_to_dataframe(output: Any) -> Any:
    if hasattr(output, "to_dataframe"):
        return output.to_dataframe()
    if hasattr(output, "to_df"):
        return output.to_df()
    raise ValueError("openbb output has no dataframe converter")


def _openbb_historical_closes_equity(ticker: str) -> list[float]:
    obb = _openbb_client()
    out = obb.equity.price.historical(ticker, provider="yfinance")
    df = _openbb_to_dataframe(out)
    if "close" not in df.columns:
        raise ValueError(f"openbb equity historical close missing for {ticker}")
    closes = [float(v) for v in df["close"].tolist() if isinstance(v, (int, float))]
    if len(closes) < 130:
        raise ValueError(f"openbb equity historical insufficient rows for {ticker}")
    return closes


def _openbb_historical_closes_crypto(symbol: str) -> list[float]:
    obb = _openbb_client()
    s = symbol.upper()
    if s.endswith("USDC"):
        pair = f"{s[:-4]}-USD"
    else:
        pair = s.replace("/", "-")
    out = obb.crypto.price.historical(pair, provider="yfinance")
    df = _openbb_to_dataframe(out)
    if "close" not in df.columns:
        raise ValueError(f"openbb crypto historical close missing for {symbol}")
    closes = [float(v) for v in df["close"].tolist() if isinstance(v, (int, float))]
    if len(closes) < 130:
        raise ValueError(f"openbb crypto historical insufficient rows for {symbol}")
    return closes


def _refresh_yfinance_cookies() -> None:
    """清除yfinance cookie缓存，强制下次请求重新获取cookie。
    解决长时间运行进程中Yahoo Finance session过期(401)问题。"""
    try:
        from yfinance.cache import get_cookie_cache
        cc = get_cookie_cache()
        # 清除所有已缓存的cookie strategy
        for strategy in ["basic", "csrf", None]:
            try:
                cc.store(strategy, None)
            except Exception:
                pass
    except Exception:
        pass


_yf_cookie_refreshed_ts: float = 0.0


def _openbb_equity_bundle(ticker: str) -> Dict[str, Optional[float]]:
    global _yf_cookie_refreshed_ts
    obb = _openbb_client()

    def _latest_row(call: Any) -> Dict[str, Any]:
        try:
            out = call()
            df = _openbb_to_dataframe(out)
            if len(df.index) == 0:
                return {}
            return df.iloc[-1].to_dict()
        except Exception:
            return {}

    metrics = _latest_row(lambda: obb.equity.fundamental.metrics(ticker, provider="yfinance"))
    income = _latest_row(lambda: obb.equity.fundamental.income(ticker, provider="yfinance", limit=1))
    balance = _latest_row(lambda: obb.equity.fundamental.balance(ticker, provider="yfinance", limit=1))
    cash = _latest_row(lambda: obb.equity.fundamental.cash(ticker, provider="yfinance", limit=1))

    # 401 retry: 全空说明可能cookie过期，刷新后重试一次
    if not metrics and not income and not balance and not cash:
        import time as _time_yf
        if _time_yf.time() - _yf_cookie_refreshed_ts > 300:  # 5min冷却防频繁刷新
            _yf_cookie_refreshed_ts = _time_yf.time()
            _refresh_yfinance_cookies()
            # 重试
            metrics = _latest_row(lambda: obb.equity.fundamental.metrics(ticker, provider="yfinance"))
            income = _latest_row(lambda: obb.equity.fundamental.income(ticker, provider="yfinance", limit=1))
            balance = _latest_row(lambda: obb.equity.fundamental.balance(ticker, provider="yfinance", limit=1))
            cash = _latest_row(lambda: obb.equity.fundamental.cash(ticker, provider="yfinance", limit=1))

    if not metrics and not income and not balance and not cash:
        raise ValueError(f"openbb equity fundamental unavailable for {ticker}")

    pe = _pick_first_numeric(metrics, ["pe_ratio", "trailing_pe", "forward_pe"])
    pb = _pick_first_numeric(metrics, ["price_to_book", "pb_ratio"])
    ev_ebitda = _pick_first_numeric(metrics, ["enterprise_to_ebitda", "ev_to_ebitda", "enterprise_value_to_ebitda"])

    market_cap = _pick_first_numeric(metrics, ["market_cap"])
    free_cash_flow = _pick_first_numeric(cash, ["free_cash_flow"])
    fcf_yield = _pick_first_numeric(metrics, ["fcf_yield", "free_cash_flow_yield"])
    if fcf_yield is None and free_cash_flow is not None and market_cap is not None and market_cap > 0:
        fcf_yield = free_cash_flow / market_cap

    roe = _pick_first_numeric(metrics, ["return_on_equity"])
    roa = _pick_first_numeric(metrics, ["return_on_assets"])
    operating_margin = _pick_first_numeric(metrics, ["operating_margin"])
    gross_margin = _pick_first_numeric(metrics, ["gross_margin"])

    current_ratio = _pick_first_numeric(metrics, ["current_ratio", "quick_ratio"])
    debt_to_equity = _pick_first_numeric(metrics, ["debt_to_equity"])
    total_debt = _pick_first_numeric(balance, ["total_debt"])
    total_assets = _pick_first_numeric(balance, ["total_assets"])
    debt_to_assets = None
    if total_debt is not None and total_assets is not None and total_assets > 0:
        debt_to_assets = total_debt / total_assets

    operating_cash_flow = _pick_first_numeric(cash, ["operating_cash_flow", "cash_flow_from_continuing_operating_activities"])
    total_revenue = _pick_first_numeric(income, ["total_revenue", "operating_revenue"])
    ocf_margin = None
    if operating_cash_flow is not None and total_revenue is not None and total_revenue != 0:
        ocf_margin = operating_cash_flow / total_revenue

    profile_row = _latest_row(lambda: obb.equity.profile(ticker, provider="yfinance"))
    sector = profile_row.get("sector") if isinstance(profile_row.get("sector"), str) else None
    industry_category = (
        profile_row.get("industry_category")
        if isinstance(profile_row.get("industry_category"), str)
        else None
    )

    return {
        "pe": pe,
        "pb": pb,
        "ev_ebitda": ev_ebitda,
        "fcf_yield": fcf_yield,
        "roe": roe,
        "roa": roa,
        "operating_margin": operating_margin,
        "gross_margin": gross_margin,
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "debt_to_assets": debt_to_assets,
        "ocf_margin": ocf_margin,
        "sector": sector,
        "industry_category": industry_category,
    }


def fetch_openbb_profile(ticker: str) -> Dict[str, Any]:
    symbol = ticker.strip().upper()
    if symbol.endswith("USDC"):
        closes = _openbb_historical_closes_crypto(symbol)
        returns = _compute_returns(closes)
        momentum_scores = {
            "ret_1m": _linear_high_better(returns["ret_1m"], good=0.20, bad=-0.20),
            "ret_3m": _linear_high_better(returns["ret_3m"], good=0.45, bad=-0.45),
            "ret_6m": _linear_high_better(returns["ret_6m"], good=0.80, bad=-0.80),
        }
        missing_raw_fields = [
            "pe",
            "pb",
            "ev_ebitda",
            "fcf_yield",
            "roe",
            "roa",
            "operating_margin",
            "gross_margin",
            "current_ratio",
            "debt_to_equity",
            "debt_to_assets",
            "ocf_margin",
        ]
        return {
            "source": "live.openbb.crypto",
            "valuation_scores": {"pe": 0.0, "pb": 0.0, "ev_ebitda": 0.0, "fcf_yield": 0.0},
            "valuation_weights": {"pe": 0.30, "pb": 0.20, "ev_ebitda": 0.25, "fcf_yield": 0.25},
            "momentum_scores": momentum_scores,
            "momentum_weights": {"ret_1m": 0.30, "ret_3m": 0.35, "ret_6m": 0.35},
            "audit_opinion": "standard",
            "altman_z": 3.0,
            "quality_key_missing": False,
            "confidence_score": 0.45,
            "missing_raw_fields": missing_raw_fields,
            "raw_metrics": {
                "ret_1m": returns["ret_1m"],
                "ret_3m": returns["ret_3m"],
                "ret_6m": returns["ret_6m"],
            },
        }

    closes = _openbb_historical_closes_equity(symbol)
    returns = _compute_returns(closes)
    bundle = _openbb_equity_bundle(symbol)
    pe = bundle.get("pe")
    pb = bundle.get("pb")
    ev_ebitda = bundle.get("ev_ebitda")
    fcf_yield = bundle.get("fcf_yield")
    roe = bundle.get("roe")
    roa = bundle.get("roa")
    operating_margin = bundle.get("operating_margin")
    gross_margin = bundle.get("gross_margin")
    current_ratio = bundle.get("current_ratio")
    debt_to_equity = bundle.get("debt_to_equity")
    debt_to_assets = bundle.get("debt_to_assets")
    ocf_margin = bundle.get("ocf_margin")
    sector = bundle.get("sector")
    industry_category = bundle.get("industry_category")

    valuation_scores = {
        "pe": _linear_low_better(pe, good=15.0, bad=45.0),
        "pb": _linear_low_better(pb, good=2.0, bad=10.0),
        "ev_ebitda": _linear_low_better(ev_ebitda, good=8.0, bad=25.0),
        "fcf_yield": _linear_high_better(fcf_yield, good=0.08, bad=0.0),
    }
    momentum_scores = {
        "ret_1m": _linear_high_better(returns["ret_1m"], good=0.12, bad=-0.12),
        "ret_3m": _linear_high_better(returns["ret_3m"], good=0.25, bad=-0.25),
        "ret_6m": _linear_high_better(returns["ret_6m"], good=0.40, bad=-0.40),
    }
    profitability_scores = {
        "roe": _linear_high_better(roe, good=0.20, bad=0.0),
        "roa": _linear_high_better(roa, good=0.08, bad=0.0),
        "operating_margin": _linear_high_better(operating_margin, good=0.20, bad=0.0),
        "gross_margin": _linear_high_better(gross_margin, good=0.45, bad=0.10),
    }
    balance_scores = {
        "current_ratio": _linear_high_better(current_ratio, good=2.0, bad=1.0),
        "debt_to_equity": _linear_low_better(debt_to_equity, good=0.50, bad=3.00),
        "debt_to_assets": _linear_low_better(debt_to_assets, good=0.25, bad=0.80),
    }
    cashflow_scores = {
        "fcf_yield": _linear_high_better(fcf_yield, good=0.08, bad=0.0),
        "ocf_margin": _linear_high_better(ocf_margin, good=0.15, bad=0.0),
    }

    raw_pairs = {
        "pe": pe,
        "pb": pb,
        "ev_ebitda": ev_ebitda,
        "fcf_yield": fcf_yield,
        "roe": roe,
        "roa": roa,
        "operating_margin": operating_margin,
        "gross_margin": gross_margin,
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "debt_to_assets": debt_to_assets,
        "ocf_margin": ocf_margin,
        "ret_1m": returns["ret_1m"],
        "ret_3m": returns["ret_3m"],
        "ret_6m": returns["ret_6m"],
    }
    missing_raw_fields = [key for key, val in raw_pairs.items() if val is None]
    missing_count = len(missing_raw_fields)
    confidence_score = max(0.20, min(1.00, 1.0 - (missing_count / 15.0)))

    return {
        "source": "live.openbb.equity",
        "valuation_scores": valuation_scores,
        "valuation_weights": {"pe": 0.30, "pb": 0.20, "ev_ebitda": 0.25, "fcf_yield": 0.25},
        "momentum_scores": momentum_scores,
        "momentum_weights": {"ret_1m": 0.30, "ret_3m": 0.35, "ret_6m": 0.35},
        "profitability_scores": profitability_scores,
        "profitability_weights": {"roe": 0.30, "roa": 0.20, "operating_margin": 0.25, "gross_margin": 0.25},
        "balance_scores": balance_scores,
        "balance_weights": {"current_ratio": 0.40, "debt_to_equity": 0.40, "debt_to_assets": 0.20},
        "cashflow_scores": cashflow_scores,
        "cashflow_weights": {"fcf_yield": 0.50, "ocf_margin": 0.50},
        "audit_opinion": "standard",
        "altman_z": 2.2,
        "quality_key_missing": missing_count >= 5,
        "confidence_score": confidence_score,
        "missing_raw_fields": missing_raw_fields,
        "raw_metrics": {
            "pe": pe,
            "pb": pb,
            "ev_ebitda": ev_ebitda,
            "fcf_yield": fcf_yield,
            "roe": roe,
            "roa": roa,
            "operating_margin": operating_margin,
            "gross_margin": gross_margin,
            "current_ratio": current_ratio,
            "debt_to_equity": debt_to_equity,
            "debt_to_assets": debt_to_assets,
            "ocf_margin": ocf_margin,
            "sector": sector,
            "industry_category": industry_category,
            "ret_1m": returns["ret_1m"],
            "ret_3m": returns["ret_3m"],
            "ret_6m": returns["ret_6m"],
        },
    }


def _yahoo_quote_summary(ticker: str) -> Dict[str, Any]:
    params = {
        "modules": "summaryDetail,defaultKeyStatistics,financialData",
        "corsDomain": "finance.yahoo.com",
    }
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?{urlencode(params)}"
    raw = _read_json(url)
    result = raw.get("quoteSummary", {}).get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    raise ValueError(f"quoteSummary unavailable for {ticker}")


def _yahoo_quote_fast(ticker: str) -> Dict[str, Any]:
    params = {"symbols": ticker}
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?{urlencode(params)}"
    raw = _read_json(url)
    result = raw.get("quoteResponse", {}).get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    raise ValueError(f"quote endpoint unavailable for {ticker}")


def _yfinance_daily_closes(ticker: str) -> list[float]:
    """Yahoo接口受限(401等)时，回退到yfinance拉取日线收盘。"""
    global _yf_cookie_refreshed_ts
    try:
        import yfinance as yf
    except Exception as exc:
        raise ValueError("yfinance package not available") from exc

    def _fetch_once() -> list[float]:
        hist = yf.Ticker(ticker).history(period="1y", interval="1d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            return []
        closes = [float(v) for v in hist["Close"].tolist() if isinstance(v, (int, float))]
        return closes

    closes = _fetch_once()
    if len(closes) >= 130:
        return closes

    # cookie刷新后重试一次（5分钟内只刷新一次）
    import time as _time_yf
    if _time_yf.time() - _yf_cookie_refreshed_ts > 300:
        _yf_cookie_refreshed_ts = _time_yf.time()
        _refresh_yfinance_cookies()
        closes = _fetch_once()
        if len(closes) >= 130:
            return closes

    raise ValueError(f"insufficient yfinance daily close data for {ticker}")


def _yahoo_daily_closes(ticker: str) -> list[float]:
    params = {
        "range": "1y",
        "interval": "1d",
        "includePrePost": "false",
        "events": "div,splits",
    }
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?{urlencode(params)}"
    try:
        raw = _read_json(url)
        result = raw.get("chart", {}).get("result")
        if not (isinstance(result, list) and result and isinstance(result[0], dict)):
            raise ValueError(f"chart unavailable for {ticker}")
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        out = [float(v) for v in closes if isinstance(v, (int, float))]
        if len(out) < 130:
            raise ValueError(f"insufficient daily close data for {ticker}")
        return out
    except Exception:
        # 关键兜底：Yahoo接口401/限流时，改走yfinance历史接口
        return _yfinance_daily_closes(ticker)


def fetch_us_equity_profile_live(ticker: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    quote_fast: Dict[str, Any] = {}
    try:
        summary = _yahoo_quote_summary(ticker)
    except Exception:
        try:
            quote_fast = _yahoo_quote_fast(ticker)
        except Exception:
            quote_fast = {}

    closes = _yahoo_daily_closes(ticker)

    pe = _nested_value(summary, "summaryDetail", "trailingPE")
    pb = _nested_value(summary, "defaultKeyStatistics", "priceToBook")
    ev = _nested_value(summary, "defaultKeyStatistics", "enterpriseValue")
    ebitda = _nested_value(summary, "financialData", "ebitda")
    fcf = _nested_value(summary, "financialData", "freeCashflow")
    market_cap = _nested_value(summary, "summaryDetail", "marketCap")

    if not summary:
        pe = pe if pe is not None else _safe_float(quote_fast.get("trailingPE"))
        pb = pb if pb is not None else _safe_float(quote_fast.get("priceToBook"))
        ev = ev if ev is not None else _safe_float(quote_fast.get("enterpriseValue"))
        ebitda = ebitda if ebitda is not None else _safe_float(quote_fast.get("ebitda"))
        fcf = fcf if fcf is not None else _safe_float(quote_fast.get("freeCashflow"))
        market_cap = market_cap if market_cap is not None else _safe_float(quote_fast.get("marketCap"))

    ev_ebitda = None
    if ev is not None and ebitda is not None and ebitda > 0:
        ev_ebitda = ev / ebitda

    fcf_yield = None
    if fcf is not None and market_cap is not None and market_cap > 0:
        fcf_yield = fcf / market_cap

    returns = _compute_returns(closes)

    valuation_scores = {
        "pe": _linear_low_better(pe, good=15.0, bad=45.0),
        "pb": _linear_low_better(pb, good=2.0, bad=10.0),
        "ev_ebitda": _linear_low_better(ev_ebitda, good=8.0, bad=25.0),
        "fcf_yield": _linear_high_better(fcf_yield, good=0.08, bad=0.0),
    }
    momentum_scores = {
        "ret_1m": _linear_high_better(returns["ret_1m"], good=0.12, bad=-0.12),
        "ret_3m": _linear_high_better(returns["ret_3m"], good=0.25, bad=-0.25),
        "ret_6m": _linear_high_better(returns["ret_6m"], good=0.40, bad=-0.40),
    }

    missing_count = sum(
        1
        for x in [pe, pb, ev_ebitda, fcf_yield, returns["ret_1m"], returns["ret_3m"], returns["ret_6m"]]
        if x is None
    )
    quality_key_missing = missing_count >= 3

    return {
        "source": "live.yahoo",
        "valuation_scores": valuation_scores,
        "valuation_weights": {"pe": 0.30, "pb": 0.20, "ev_ebitda": 0.25, "fcf_yield": 0.25},
        "momentum_scores": momentum_scores,
        "momentum_weights": {"ret_1m": 0.30, "ret_3m": 0.35, "ret_6m": 0.35},
        "audit_opinion": "standard",
        "altman_z": 2.2,
        "quality_key_missing": quality_key_missing,
        "raw_metrics": {
            "pe": pe,
            "pb": pb,
            "ev_ebitda": ev_ebitda,
            "fcf_yield": fcf_yield,
            "ret_1m": returns["ret_1m"],
            "ret_3m": returns["ret_3m"],
            "ret_6m": returns["ret_6m"],
        },
    }


def _binance_daily_closes(symbol: str) -> list[float]:
    params = {"symbol": symbol.upper(), "interval": "1d", "limit": 220}
    url = f"https://api.binance.com/api/v3/klines?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        payload = resp.read().decode("utf-8")
    rows = json.loads(payload)
    if not isinstance(rows, list) or len(rows) < 130:
        raise ValueError(f"insufficient klines for {symbol}")
    closes: list[float] = []
    for row in rows:
        if isinstance(row, list) and len(row) >= 5:
            try:
                closes.append(float(row[4]))
            except Exception:
                continue
    if len(closes) < 130:
        raise ValueError(f"insufficient parsed closes for {symbol}")
    return closes


def fetch_crypto_profile_live(symbol: str) -> Dict[str, Any]:
    closes = _binance_daily_closes(symbol)
    returns = _compute_returns(closes)
    momentum_scores = {
        "ret_1m": _linear_high_better(returns["ret_1m"], good=0.20, bad=-0.20),
        "ret_3m": _linear_high_better(returns["ret_3m"], good=0.45, bad=-0.45),
        "ret_6m": _linear_high_better(returns["ret_6m"], good=0.80, bad=-0.80),
    }
    return {
        "source": "live.binance",
        "valuation_scores": {"pe": 0.0, "pb": 0.0, "ev_ebitda": 0.0, "fcf_yield": 0.0},
        "valuation_weights": {"pe": 0.30, "pb": 0.20, "ev_ebitda": 0.25, "fcf_yield": 0.25},
        "momentum_scores": momentum_scores,
        "momentum_weights": {"ret_1m": 0.30, "ret_3m": 0.35, "ret_6m": 0.35},
        "audit_opinion": "standard",
        "altman_z": 3.0,
        "quality_key_missing": False,
        "raw_metrics": {
            "ret_1m": returns["ret_1m"],
            "ret_3m": returns["ret_3m"],
            "ret_6m": returns["ret_6m"],
        },
    }


def fetch_schwab_profile(ticker: str) -> Dict[str, Any]:
    """从 Schwab instruments API 获取基本面数据 (FUNDAMENTAL projection)。
    数据比 Yahoo 更全: PE/PB/PCF + ROE/ROA/margins + currentRatio/debtToEquity。
    """
    from schwab_data_provider import get_provider
    provider = get_provider()
    client = provider._get_client()
    resp = client.get_instruments(ticker, client.Instrument.Projection.FUNDAMENTAL)
    assert resp.status_code == 200, f"Schwab HTTP {resp.status_code}"
    data = resp.json()
    # get_instruments returns {"instruments": [{fundamental: {...}, ...}]}
    inst = None
    instruments = data.get("instruments", [])
    if isinstance(instruments, list) and instruments:
        inst = instruments[0]
    if not inst:
        # fallback: try direct key lookup
        inst = data.get(ticker) or data.get(ticker.upper())
    if not inst or "fundamental" not in inst:
        raise ValueError(f"Schwab no fundamental data for {ticker}")
    f = inst["fundamental"]

    pe = _safe_float(f.get("peRatio"))
    pb = _safe_float(f.get("pbRatio"))
    pcf = _safe_float(f.get("pcfRatio"))
    market_cap = _safe_float(f.get("marketCap"))

    # EV/EBITDA: Schwab 无直接字段，用 pcfRatio 作 FCF yield 替代
    # FCF yield ≈ 1/pcfRatio (Price/CashFlow 的倒数)
    fcf_yield = (1.0 / pcf) if pcf and pcf > 0 else None

    # Profitability
    roe = _safe_float(f.get("returnOnEquity"))
    roa = _safe_float(f.get("returnOnAssets"))
    gross_margin = _safe_float(f.get("grossMarginTTM"))
    net_margin = _safe_float(f.get("netProfitMarginTTM"))
    op_margin = _safe_float(f.get("operatingMarginTTM"))

    # Balance sheet
    current_ratio = _safe_float(f.get("currentRatio"))
    quick_ratio = _safe_float(f.get("quickRatio"))
    debt_to_equity = _safe_float(f.get("totalDebtToEquity"))
    lt_debt_to_equity = _safe_float(f.get("ltDebtToEquity"))

    # Altman Z 近似: 用可用字段估算
    # Z = 1.2*WC/TA + 1.4*RE/TA + 3.3*EBIT/TA + 0.6*MC/TL + 1.0*Sales/TA
    # Schwab 没有完整资产负债表，用 currentRatio 和 debtToEquity 近似
    altman_z = 2.2  # default
    if current_ratio is not None and debt_to_equity is not None:
        # 简化近似: current_ratio>2 + low debt → 健康
        wc_proxy = max(0, (current_ratio - 1.0) * 0.5)  # WC/TA proxy
        mc_tl_proxy = (100.0 / max(debt_to_equity, 1.0)) * 0.6 if debt_to_equity else 3.0
        margin_proxy = (op_margin / 100.0 * 3.3) if op_margin else 0.0
        altman_z = round(1.2 * wc_proxy + margin_proxy + mc_tl_proxy + 1.0, 2)
        altman_z = max(0.5, min(altman_z, 8.0))

    # Momentum: 用 Schwab K线获取日线价格
    closes = []
    try:
        df = provider.get_kline(ticker, interval="1d", bars=150)
        if df is not None and len(df) >= 30:
            closes = df["close"].tolist()
    except Exception:
        pass
    returns = _compute_returns(closes)

    valuation_scores = {
        "pe": _linear_low_better(pe, good=15.0, bad=45.0),
        "pb": _linear_low_better(pb, good=2.0, bad=10.0),
        "ev_ebitda": 0.0,  # Schwab 无 EV/EBITDA
        "fcf_yield": _linear_high_better(fcf_yield, good=0.08, bad=0.0),
    }
    momentum_scores = {
        "ret_1m": _linear_high_better(returns["ret_1m"], good=0.12, bad=-0.12),
        "ret_3m": _linear_high_better(returns["ret_3m"], good=0.25, bad=-0.25),
        "ret_6m": _linear_high_better(returns["ret_6m"], good=0.40, bad=-0.40),
    }
    profitability_scores = {
        "roe": _linear_high_better(roe, good=15.0, bad=0.0) if roe else 0.0,
        "roa": _linear_high_better(roa, good=8.0, bad=0.0) if roa else 0.0,
        "gross_margin": _linear_high_better(gross_margin, good=40.0, bad=10.0) if gross_margin else 0.0,
    }
    balance_scores = {
        "current_ratio": _linear_high_better(current_ratio, good=2.0, bad=0.8) if current_ratio else 0.0,
        "quick_ratio": _linear_high_better(quick_ratio, good=1.5, bad=0.5) if quick_ratio else 0.0,
        "debt_to_equity": _linear_low_better(debt_to_equity, good=30.0, bad=150.0) if debt_to_equity else 0.0,
    }
    cashflow_scores = {
        "fcf_yield": _linear_high_better(fcf_yield, good=0.08, bad=0.0) if fcf_yield else 0.0,
        "op_margin": _linear_high_better(op_margin, good=20.0, bad=0.0) if op_margin else 0.0,
    }

    missing_count = sum(1 for x in [pe, pb, fcf_yield, returns["ret_1m"],
                                     returns["ret_3m"], returns["ret_6m"], roe] if x is None)
    quality_key_missing = missing_count >= 4
    confidence = 0.85 if missing_count <= 2 else (0.70 if missing_count <= 4 else 0.55)

    return {
        "source": "live.schwab",
        "valuation_scores": valuation_scores,
        "valuation_weights": {"pe": 0.35, "pb": 0.25, "ev_ebitda": 0.0, "fcf_yield": 0.40},
        "momentum_scores": momentum_scores,
        "momentum_weights": {"ret_1m": 0.30, "ret_3m": 0.35, "ret_6m": 0.35},
        "profitability_scores": profitability_scores,
        "profitability_weights": {"roe": 0.40, "roa": 0.30, "gross_margin": 0.30},
        "balance_scores": balance_scores,
        "balance_weights": {"current_ratio": 0.35, "quick_ratio": 0.30, "debt_to_equity": 0.35},
        "cashflow_scores": cashflow_scores,
        "cashflow_weights": {"fcf_yield": 0.50, "op_margin": 0.50},
        "audit_opinion": "standard",
        "altman_z": altman_z,
        "quality_key_missing": quality_key_missing,
        "confidence_score": confidence,
        "missing_raw_fields": [k for k, v in {"pe": pe, "pb": pb, "fcf_yield": fcf_yield,
                                               "roe": roe, "roa": roa}.items() if v is None],
        "raw_metrics": {
            "pe": pe, "pb": pb, "pcf_ratio": pcf, "fcf_yield": fcf_yield,
            "roe": roe, "roa": roa, "gross_margin": gross_margin,
            "net_margin": net_margin, "op_margin": op_margin,
            "current_ratio": current_ratio, "quick_ratio": quick_ratio,
            "debt_to_equity": debt_to_equity, "market_cap": market_cap,
            "altman_z": altman_z, "beta": _safe_float(f.get("beta")),
            "eps": _safe_float(f.get("epsTTM")),
            "ret_1m": returns["ret_1m"], "ret_3m": returns["ret_3m"], "ret_6m": returns["ret_6m"],
        },
    }


def fetch_live_profile(ticker: str) -> Dict[str, Any]:
    """优先链: Schwab(美股) → OpenBB → Yahoo。加密走 Binance。"""
    symbol = ticker.strip().upper()
    if symbol.endswith("USDC") or symbol.endswith("USDT"):
        return fetch_crypto_profile_live(symbol)
    # 美股: Schwab优先
    try:
        return fetch_schwab_profile(symbol)
    except Exception:
        pass
    try:
        return fetch_openbb_profile(symbol)
    except Exception:
        pass
    return fetch_us_equity_profile_live(symbol)
