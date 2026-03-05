"""
modules/knn/evolution.py — L3 进化引擎
=======================================
漂移检测、数据增强、自适应K值、WFO回测、Bootstrap、MAB调度。
gcc-evo五层架构: L3 进化引擎层
"""
from __future__ import annotations

import os
import json
import numpy as np
from datetime import datetime, timezone

from .models import (
    PluginKNNResult, plugin_log,
    ROOT, _AUG_FILE, _MAB_STATE_FILE, _EVO_TUNE_FILE,
    PRICE_SHAPE_WINDOW, KNN_FUTURE_BARS, KNN_K, KNN_MIN_SAMPLES,
    PSI_THRESHOLD, STL_PERIOD,
    AUG_TAU, AUG_JITTER_STD,
    WFO_TRAIN_BARS, WFO_VALID_BARS,
    CRYPTO_SYMBOLS, STOCK_SYMBOLS, YF_MAP,
)
from .features import _append_extended_features


# ============================================================
# GCC-0138: PSI概念漂移检测
# ============================================================
def compute_psi(expected: np.ndarray, actual: np.ndarray, bins: int = 0) -> float:
    """Population Stability Index — 检测特征分布漂移"""
    if bins <= 0:
        bins = min(10, max(3, int(np.sqrt(min(len(expected), len(actual))))))
    if len(expected) < bins or len(actual) < bins:
        return 0.0
    eps = 1e-8
    expected_perc = np.histogram(expected, bins=bins)[0] / len(expected) + eps
    actual_perc = np.histogram(actual, bins=bins,
                               range=(expected.min(), expected.max()))[0] / len(actual) + eps
    psi = np.sum((actual_perc - expected_perc) * np.log(actual_perc / expected_perc))
    return float(psi)


def detect_drift(history_returns: np.ndarray, current_bars: list) -> tuple:
    """GCC-0138: 用PSI+KS检测概念漂移"""
    if len(history_returns) < 30 or not current_bars or len(current_bars) < 10:
        return False, 0.0, 1.0
    closes = np.array([b["close"] for b in current_bars[-20:]], dtype=float)
    if len(closes) < 2:
        return False, 0.0, 1.0
    safe_mask = closes[:-1] > 0
    if safe_mask.sum() < 5:
        return False, 0.0, 1.0
    recent_rets = np.diff(closes)[safe_mask] / closes[:-1][safe_mask]
    half = len(history_returns) // 2
    hist_baseline = history_returns[:half]
    if len(hist_baseline) < 10 or len(recent_rets) < 5:
        return False, 0.0, 1.0
    psi = compute_psi(hist_baseline, recent_rets)
    try:
        from scipy.stats import ks_2samp
        _, ks_p = ks_2samp(hist_baseline, recent_rets)
    except Exception:
        ks_p = 1.0
    drift = psi > PSI_THRESHOLD and ks_p < 0.05
    return drift, psi, ks_p


# ============================================================
# GCC-0139: Overfitting-Aware 增强调度
# ============================================================
def alpha_schedule(epoch: int, tau: float = AUG_TAU) -> float:
    """课程调度: α = min(tanh(E/τ) + 0.01, 1.0)"""
    return min(np.tanh(epoch / tau) + 0.01, 1.0)


def augment_feature(feat: np.ndarray, strategy: str = "jitter") -> np.ndarray:
    """对特征向量做微扰增强(jitter/scaling)"""
    if strategy == "jitter":
        noise = np.random.normal(0, AUG_JITTER_STD, feat.shape)
        return feat + noise
    elif strategy == "scaling":
        scale = 1.0 + np.random.uniform(-0.1, 0.1)
        return feat * scale
    return feat


def _load_aug_stats() -> dict:
    """加载增强调度状态"""
    try:
        if _AUG_FILE.exists():
            with open(_AUG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"epoch": 0, "total_augmented": 0}


def _save_aug_stats(stats: dict):
    """保存增强调度状态"""
    try:
        with open(_AUG_FILE, "w") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass


# ============================================================
# GCC-0140: 多股票Mix-up融合
# ============================================================
def cutmix_features(feat_a: np.ndarray, feat_b: np.ndarray, lam: float = 0.5) -> np.ndarray:
    """CutMix: λ比例取A的前段+B的后段"""
    if len(feat_a) != len(feat_b):
        return feat_a
    cut = int(len(feat_a) * lam)
    return np.concatenate([feat_a[:cut], feat_b[cut:]])


def linear_mix(feat_a: np.ndarray, feat_b: np.ndarray, lam: float = 0.7) -> np.ndarray:
    """线性插值: λ*A + (1-λ)*B"""
    if len(feat_a) != len(feat_b):
        return feat_a
    return lam * feat_a + (1 - lam) * feat_b


# ============================================================
# GCC-0050: 自适应K值
# ============================================================
def _load_evo_k_cap() -> int:
    """GCC-0191: 从gcc-evo调优建议读取K值上限"""
    try:
        if _EVO_TUNE_FILE.exists():
            tune = json.loads(_EVO_TUNE_FILE.read_text())
            return tune.get("suggested_k_cap", 80)
    except Exception:
        pass
    return 80


def adaptive_k(n_samples: int) -> int:
    """根据历史库大小自适应K值: K ≈ sqrt(n), 限制在[10, k_cap]"""
    if n_samples <= 0:
        return KNN_K
    k_cap = _load_evo_k_cap()
    k = int(n_samples ** 0.5)
    return max(10, min(k, k_cap))


# ============================================================
# Bootstrap: 用yfinance历史K线滑窗构建KNN历史库
# ============================================================
def bootstrap_from_yfinance(days: int = 365, plugin_name: str = "generic",
                            symbols: list = None, indicator_dim: int = 5) -> dict:
    """用yfinance拉取历史4H K线, 滑窗构建KNN历史库"""
    import yfinance as yf
    from .store import PluginKNNDB
    from .models import VOL_SHAPE_WINDOW, ATR_WINDOW

    if symbols is None:
        symbols = CRYPTO_SYMBOLS + STOCK_SYMBOLS

    db = PluginKNNDB()
    results = {}
    total_dim = indicator_dim + PRICE_SHAPE_WINDOW + VOL_SHAPE_WINDOW + ATR_WINDOW + 1

    for symbol in symbols:
        try:
            ticker = YF_MAP.get(symbol, symbol)
            print(f"[BOOTSTRAP] {symbol} ({ticker}) 拉取{days}天4H数据...")
            period_str = f"{days}d"
            df = yf.download(ticker, period=period_str, interval="1h", progress=False)
            if df is None or len(df) < 100:
                print(f"  跳过: 数据不足 ({len(df) if df is not None else 0}行)")
                continue
            bars_4h = _aggregate_to_4h(df)
            if len(bars_4h) < PRICE_SHAPE_WINDOW + KNN_FUTURE_BARS + 10:
                print(f"  跳过: 4H K线不足 ({len(bars_4h)}根)")
                continue
            print(f"  4H K线: {len(bars_4h)}根")

            key = db._make_key(plugin_name, symbol)
            features_list = []
            returns_list = []
            W = PRICE_SHAPE_WINDOW
            F = KNN_FUTURE_BARS

            for i in range(len(bars_4h) - W - F):
                seg = bars_4h[i: i + W]
                future = bars_4h[i + W: i + W + F]
                indicator = np.zeros(indicator_dim)
                feat = _append_extended_features(indicator, seg)
                if len(feat) != total_dim:
                    continue
                cur_close = seg[-1]["close"]
                fut_close = future[-1]["close"]
                if cur_close > 0:
                    ret = (fut_close - cur_close) / cur_close
                else:
                    ret = 0.0
                features_list.append(feat)
                returns_list.append(ret)

            if features_list:
                feat_arr = np.array(features_list)
                ret_arr = np.array(returns_list)
                db._db[key] = {"features": feat_arr, "returns": ret_arr}
                n = len(ret_arr)
                wr = float(np.sum(ret_arr > 0) / n) if n > 0 else 0
                avg_ret = float(np.mean(ret_arr))
                results[symbol] = {"samples": n, "win_rate": wr, "avg_return": avg_ret}
                print(f"  完成: {n}条 wr={wr:.0%} avg_ret={avg_ret:.2%}")
        except Exception as e:
            print(f"  错误: {e}")
            continue

    db._save()
    print(f"\n[BOOTSTRAP] 总计{len(results)}个品种, 保存到 {db._db}")
    return results


def _aggregate_to_4h(df) -> list:
    """将1H DataFrame聚合为4H bars列表"""
    bars = []
    df = df.reset_index()
    cols = df.columns.tolist()
    col_map = {}
    for c in cols:
        c_str = str(c).lower()
        if 'open' in c_str: col_map['open'] = c
        elif 'high' in c_str: col_map['high'] = c
        elif 'low' in c_str: col_map['low'] = c
        elif 'close' in c_str: col_map['close'] = c
        elif 'volume' in c_str: col_map['volume'] = c
    if not all(k in col_map for k in ['open', 'high', 'low', 'close']):
        return bars
    step = 4
    for i in range(0, len(df) - step + 1, step):
        chunk = df.iloc[i:i + step]
        bar = {
            "open": float(chunk[col_map['open']].iloc[0]),
            "high": float(chunk[col_map['high']].max()),
            "low": float(chunk[col_map['low']].min()),
            "close": float(chunk[col_map['close']].iloc[-1]),
            "volume": float(chunk[col_map.get('volume', col_map['close'])].sum()) if 'volume' in col_map else 0,
        }
        bars.append(bar)
    return bars


def bootstrap_compare(days_list: list = None, plugin_name: str = "generic",
                      symbols: list = None) -> dict:
    """对比不同时间窗口的bootstrap效果"""
    if days_list is None:
        days_list = [365, 730]
    all_results = {}
    for days in days_list:
        print(f"\n{'='*60}")
        print(f"  Bootstrap {days}天 ({days//365}年)")
        print(f"{'='*60}")
        result = bootstrap_from_yfinance(days=days, plugin_name=plugin_name, symbols=symbols)
        all_results[days] = result

    print(f"\n{'='*70}")
    print(f"  对比: {' vs '.join(f'{d}天' for d in days_list)}")
    print(f"{'='*70}")
    print(f"{'品种':<12}", end="")
    for d in days_list:
        print(f"  {'样本':>6}  {'胜率':>6}  {'均收益':>8}", end="")
    print()
    print("-" * 70)
    all_symbols = set()
    for r in all_results.values():
        all_symbols.update(r.keys())
    for sym in sorted(all_symbols):
        print(f"{sym:<12}", end="")
        for d in days_list:
            r = all_results.get(d, {}).get(sym, {})
            if r:
                print(f"  {r['samples']:>6}  {r['win_rate']:>5.0%}  {r['avg_return']:>+7.2%}", end="")
            else:
                print(f"  {'N/A':>6}  {'N/A':>6}  {'N/A':>8}", end="")
        print()
    return all_results


# ============================================================
# GCC-0054: Walk-Forward Optimization
# ============================================================
def wfo_backtest(bars_4h: list, indicator_dim: int = 5) -> dict:
    """Walk-Forward分段验证: 滚动训练→OOS验证, 暴露过拟合"""
    from .matcher import knn_match

    W = PRICE_SHAPE_WINDOW
    F = KNN_FUTURE_BARS
    min_bars = WFO_TRAIN_BARS + WFO_VALID_BARS + W + F
    if len(bars_4h) < min_bars:
        return {"error": f"数据不足: {len(bars_4h)} < {min_bars}", "oos_accuracy": 0, "is_accuracy": 0}

    fold_details = []
    oos_correct = 0
    oos_total = 0
    is_correct = 0
    is_total = 0

    for valid_start in range(WFO_TRAIN_BARS, len(bars_4h) - WFO_VALID_BARS - W - F, WFO_VALID_BARS):
        train_feats = []
        train_rets = []
        train_end = valid_start
        for i in range(max(0, train_end - WFO_TRAIN_BARS), train_end - W - F):
            seg = bars_4h[i: i + W]
            future = bars_4h[i + W: i + W + F]
            if len(seg) < W or len(future) < F:
                continue
            indicator = np.zeros(indicator_dim)
            feat = _append_extended_features(indicator, seg)
            cur_close = seg[-1]["close"]
            fut_close = future[-1]["close"]
            ret = (fut_close - cur_close) / cur_close if cur_close > 0 else 0.0
            train_feats.append(feat)
            train_rets.append(ret)

        if len(train_feats) < KNN_MIN_SAMPLES:
            continue

        train_feat_arr = np.array(train_feats)
        train_ret_arr = np.array(train_rets)
        k = adaptive_k(len(train_feats))

        fold_oos_correct = 0
        fold_oos_total = 0
        for i in range(valid_start, min(valid_start + WFO_VALID_BARS, len(bars_4h) - W - F)):
            seg = bars_4h[i: i + W]
            future = bars_4h[i + W: i + W + F]
            if len(seg) < W or len(future) < F:
                continue
            indicator = np.zeros(indicator_dim)
            feat = _append_extended_features(indicator, seg)
            cur_close = seg[-1]["close"]
            fut_close = future[-1]["close"]
            actual_ret = (fut_close - cur_close) / cur_close if cur_close > 0 else 0.0
            result = knn_match(feat, train_feat_arr, train_ret_arr, k=k)
            predicted_up = result.win_rate > 0.5
            actual_up = actual_ret > 0
            if predicted_up == actual_up:
                fold_oos_correct += 1
            fold_oos_total += 1

        if fold_oos_total > 0:
            fold_acc = fold_oos_correct / fold_oos_total
            fold_details.append({
                "valid_start": valid_start,
                "oos_accuracy": round(fold_acc, 4),
                "train_samples": len(train_feats),
                "valid_samples": fold_oos_total,
            })
            oos_correct += fold_oos_correct
            oos_total += fold_oos_total

    all_feats = []
    all_rets = []
    for i in range(len(bars_4h) - W - F):
        seg = bars_4h[i: i + W]
        future = bars_4h[i + W: i + W + F]
        if len(seg) < W or len(future) < F:
            continue
        indicator = np.zeros(indicator_dim)
        feat = _append_extended_features(indicator, seg)
        cur_close = seg[-1]["close"]
        fut_close = future[-1]["close"]
        ret = (fut_close - cur_close) / cur_close if cur_close > 0 else 0.0
        all_feats.append(feat)
        all_rets.append(ret)

    if all_feats:
        all_feat_arr = np.array(all_feats)
        all_ret_arr = np.array(all_rets)
        k_all = adaptive_k(len(all_feats))
        for i in range(len(all_feats)):
            result = knn_match(all_feat_arr[i], all_feat_arr, all_ret_arr, k=k_all)
            predicted_up = result.win_rate > 0.5
            actual_up = all_rets[i] > 0
            if predicted_up == actual_up:
                is_correct += 1
            is_total += 1

    oos_acc = oos_correct / oos_total if oos_total > 0 else 0.0
    is_acc = is_correct / is_total if is_total > 0 else 0.0
    overfit_gap = is_acc - oos_acc

    return {
        "oos_accuracy": round(oos_acc, 4),
        "is_accuracy": round(is_acc, 4),
        "overfit_gap": round(overfit_gap, 4),
        "n_folds": len(fold_details),
        "oos_total": oos_total,
        "is_total": is_total,
        "fold_details": fold_details,
    }


# ============================================================
# GCC-0053: MAB调度器
# ============================================================
EVOLUTION_ARMS = {
    "feature_volume":   "增加成交量维度到KNN特征",
    "feature_atr":      "增加ATR波动率到KNN特征",
    "feature_regime":   "增加Regime标签到KNN特征",
    "adaptive_k":       "自适应K值选择",
    "regime_rerank":    "Regime感知的邻居重排序",
    "ebbinghaus":       "调整时间衰减权重decay_rate",
    "knowledge_cards":  "增强知识卡规则",
    "wfo":              "Walk-Forward Optimization",
}


class KNNEvolutionMAB:
    """Thompson Sampling MAB: 每个arm维护Beta分布"""

    def __init__(self):
        self.betas: dict = {}
        self._load()

    def _load(self):
        try:
            if _MAB_STATE_FILE.exists():
                with open(_MAB_STATE_FILE, "r") as f:
                    data = json.load(f)
                self.betas = data.get("betas", {})
        except Exception:
            self.betas = {}
        for arm in EVOLUTION_ARMS:
            if arm not in self.betas:
                self.betas[arm] = {"alpha": 1.0, "beta": 1.0}

    def _save(self):
        try:
            os.makedirs("state", exist_ok=True)
            data = {
                "betas": self.betas,
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            with open(_MAB_STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def update(self, arm: str, delta_accuracy: float):
        """更新arm的Beta分布"""
        if arm not in self.betas:
            self.betas[arm] = {"alpha": 1.0, "beta": 1.0}
        if delta_accuracy > 0:
            self.betas[arm]["alpha"] += delta_accuracy * 10
        else:
            self.betas[arm]["beta"] += abs(delta_accuracy) * 10 + 0.5
        self._save()
        plugin_log(f"[KEY-007][MAB] update {arm}: delta={delta_accuracy:+.4f} "
                   f"→ α={self.betas[arm]['alpha']:.1f} β={self.betas[arm]['beta']:.1f}")

    def next_direction(self) -> str:
        """Thompson Sampling: 每个arm从Beta分布采样, 选最大值"""
        best_arm = None
        best_sample = -1.0
        for arm, params in self.betas.items():
            sample = np.random.beta(params["alpha"], params["beta"])
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        plugin_log(f"[KEY-007][MAB] next_direction → {best_arm} (sampled {best_sample:.3f})")
        return best_arm or list(EVOLUTION_ARMS.keys())[0]

    def get_rankings(self) -> list:
        """返回所有arms按期望值排序"""
        rankings = []
        for arm, params in self.betas.items():
            alpha = params["alpha"]
            beta = params["beta"]
            expected = alpha / (alpha + beta)
            desc = EVOLUTION_ARMS.get(arm, "")
            rankings.append({
                "arm": arm, "expected": round(expected, 4),
                "alpha": round(alpha, 1), "beta": round(beta, 1),
                "description": desc,
            })
        rankings.sort(key=lambda x: x["expected"], reverse=True)
        return rankings


# MAB全局单例
_knn_mab: KNNEvolutionMAB | None = None


def get_knn_mab() -> KNNEvolutionMAB:
    """获取全局MAB单例"""
    global _knn_mab
    if _knn_mab is None:
        _knn_mab = KNNEvolutionMAB()
    return _knn_mab
