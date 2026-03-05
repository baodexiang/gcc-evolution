"""
modules/knn/orchestrator.py — L4 编排自治
==========================================
统一接口(record_and_query)、Phase2抑制、知识卡增强、准确率追踪。
回填+增强编排、漂移检测查询、准确率→L5闭环。
gcc-evo五层架构: L4 编排自治层
依赖: L1 models, L2 store+matcher, L3 evolution, L5 alignment
"""
from __future__ import annotations

import os
import re
import json
import time

import numpy as np
from datetime import datetime, timezone

from .models import (
    PluginKNNResult, plugin_log, ROOT, logger,
    _ACCURACY_FILE, KNN_BYPASS_THRESHOLD,
    PLUGIN_KNN_PHASE2, PHASE2_MIN_SAMPLES,
    KNN_K, KNN_MIN_SAMPLES, KNN_FUTURE_BARS,
    PRICE_SHAPE_WINDOW, VOL_SHAPE_WINDOW, ATR_WINDOW,
    INDICATOR_WEIGHT, SHAPE_WEIGHT,
    DRIFT_K_MULTIPLIER, DRIFT_CONFIDENCE_DECAY,
    MIXUP_PROB,
)
from .store import PluginKNNDB
from .matcher import knn_match
from .evolution import (
    detect_drift, adaptive_k,
    alpha_schedule, augment_feature,
    cutmix_features, linear_mix,
    _load_aug_stats, _save_aug_stats,
)
from .alignment import (
    feedback_to_retriever, create_knn_experience_cards,
    sync_evo_tuning, check_accuracy_drift,
)


# ============================================================
# 全局单例
# ============================================================
_plugin_knn_db: PluginKNNDB | None = None


def get_plugin_knn_db() -> PluginKNNDB:
    """获取全局PluginKNNDB单例"""
    global _plugin_knn_db
    if _plugin_knn_db is None:
        _plugin_knn_db = PluginKNNDB()
    return _plugin_knn_db


# ============================================================
# 准确率追踪 + 自动bypass
# ============================================================
_accuracy_cache: dict = {}
_accuracy_cache_ts: float = 0


def load_knn_accuracy() -> dict:
    """加载KNN准确率映射(60s缓存)"""
    global _accuracy_cache, _accuracy_cache_ts
    if time.time() - _accuracy_cache_ts < 60:
        return _accuracy_cache
    try:
        if _ACCURACY_FILE.exists():
            with open(_ACCURACY_FILE, "r") as f:
                _accuracy_cache = json.load(f)
        else:
            _accuracy_cache = {}
    except Exception:
        _accuracy_cache = {}
    _accuracy_cache_ts = time.time()
    return _accuracy_cache


def should_bypass_knn(plugin_name: str, symbol: str) -> bool:
    """低准确率的外挂×品种组合自动bypass KNN查询"""
    acc_map = load_knn_accuracy()
    key = f"{plugin_name}_{symbol}"
    acc = acc_map.get(key)
    if acc is None:
        return False
    if isinstance(acc, dict):
        acc = acc.get("accuracy")
    if acc is not None and acc < KNN_BYPASS_THRESHOLD:
        return True
    return False


def save_knn_accuracy(acc_map: dict):
    """保存准确率映射"""
    try:
        os.makedirs("state", exist_ok=True)
        with open(_ACCURACY_FILE, "w") as f:
            json.dump(acc_map, f, indent=2)
    except Exception:
        pass


# ============================================================
# 回填编排 (从store.py移入, L4负责调用L3增强)
# ============================================================
def _try_mixup(db: PluginKNNDB, key: str, feat: np.ndarray) -> np.ndarray | None:
    """GCC-0140: 从同plugin其他品种中随机选一个维度匹配的特征做Mix-up"""
    dim = len(feat)
    key_parts = key.split("_", 1)
    if len(key_parts) < 2:
        return None
    plugin_prefix = key_parts[0]
    candidates = []
    for db_key in db.get_all_keys():
        if db_key == key:
            continue
        db_parts = db_key.split("_", 1)
        if len(db_parts) < 2:
            continue
        if db_parts[0] != plugin_prefix:
            continue
        data = db.get_history(db_key)
        if data and data["features"].shape[1] == dim and len(data["features"]) >= 10:
            candidates.append(db_key)
    if not candidates:
        return None
    partner_key = candidates[np.random.randint(len(candidates))]
    partner_data = db.get_history(partner_key)
    partner_feats = partner_data["features"]
    idx = np.random.randint(len(partner_feats))
    partner_feat = partner_feats[idx]
    lam = np.random.uniform(0.6, 0.9)
    if np.random.random() < 0.5:
        return cutmix_features(feat, partner_feat, lam)
    else:
        return linear_mix(feat, partner_feat, lam)


def _update_accuracy(db: PluginKNNDB):
    """回填后重算准确率 → L5闭环"""
    acc_map = {}
    try:
        for key in db.get_all_keys():
            if key.startswith("generic_"):
                continue
            data = db.get_history(key)
            if data is None:
                continue
            rets = data.get("returns")
            if rets is None or len(rets) == 0:
                continue
            n_total = len(rets)
            n_win = int(np.sum(rets > 0))
            acc = n_win / n_total if n_total > 0 else 0.0
            acc_map[key] = {
                "accuracy": round(acc, 4),
                "total": n_total,
                "wins": n_win,
            }
        acc_map["_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_knn_accuracy(acc_map)
        plugin_log(f"[KEY-007][ACCURACY] 准确率更新: {len(acc_map)-1}个key")
        # L5 gcc-evo闭环
        feedback_to_retriever(acc_map)
        create_knn_experience_cards(acc_map)
        sync_evo_tuning()
        check_accuracy_drift(acc_map)
    except Exception as e:
        plugin_log(f"[KEY-007][ACCURACY] 更新异常: {e}")


def backfill_returns(db: PluginKNNDB, get_price_func=None) -> int:
    """回填未来收益 + L3增强: 扫描pending, 10根4H bar后的收益率"""
    pending = db.get_pending()
    if not pending or get_price_func is None:
        return 0

    now = datetime.now(timezone.utc)
    filled = 0
    remaining = []
    _filled_records = []

    for rec in pending:
        try:
            rec_time = datetime.fromisoformat(rec["recorded_at"].replace("Z", "+00:00"))
            hours_passed = (now - rec_time).total_seconds() / 3600
            if hours_passed < KNN_FUTURE_BARS * 4:
                remaining.append(rec)
                continue

            future_price = get_price_func(rec["symbol"], rec["recorded_at"])
            if future_price and future_price > 0 and rec["close_price"] > 0:
                raw_return = (future_price - rec["close_price"]) / rec["close_price"]
                if rec["direction"] == "SELL":
                    raw_return = -raw_return
                feat_arr = np.array(rec["features"])
                rec_regime = rec.get("regime", "unknown")
                db.add_to_history(rec["key"], feat_arr, raw_return, regime=rec_regime)
                filled += 1
                _filled_records.append((rec["key"], feat_arr, raw_return, rec_regime))
            else:
                if hours_passed > 168:
                    continue
                remaining.append(rec)
        except Exception:
            remaining.append(rec)

    # GCC-0139/0140: 批量增强 (L3 evolution)
    if _filled_records:
        _aug_stats = _load_aug_stats()
        _alpha = alpha_schedule(_aug_stats.get("epoch", 0))
        for _fk, _ff, _fr, _freg in _filled_records:
            if np.random.random() < _alpha:
                _aug_feat = augment_feature(_ff, "jitter")
                _aug_ret = _fr * (1.0 + np.random.uniform(-0.01, 0.01))
                db.add_to_history(_fk, _aug_feat, _aug_ret, regime=_freg)
                _aug_stats["total_augmented"] = _aug_stats.get("total_augmented", 0) + 1
            if np.random.random() < MIXUP_PROB:
                _mix_feat = _try_mixup(db, _fk, _ff)
                if _mix_feat is not None:
                    _mix_ret = _fr * (1.0 + np.random.uniform(-0.02, 0.02))
                    db.add_to_history(_fk, _mix_feat, _mix_ret, regime=_freg)
                    _aug_stats["total_augmented"] = _aug_stats.get("total_augmented", 0) + 1
        _aug_stats["epoch"] = _aug_stats.get("epoch", 0) + len(_filled_records)
        _save_aug_stats(_aug_stats)

    db.commit_backfill(remaining, save_history=(filled > 0))

    if filled > 0:
        _update_accuracy(db)

    return filled


# ============================================================
# KNN查询编排 (从store.py移入, L4负责调用L3漂移检测)
# ============================================================
def query_knn(db: PluginKNNDB, plugin_name: str, symbol: str,
              current_features: np.ndarray, k: int = KNN_K,
              regime: str = "unknown",
              bars: list = None) -> PluginKNNResult | None:
    """
    查询历史相似情况(四层增强):
    1. Regime分区 2. 特征维度加权 3. 距离反比 4. PSI概念漂移检测
    """
    if current_features is None or len(current_features) == 0:
        return None
    key = f"{plugin_name}_{symbol}"
    fallback_generic = False

    data = db.get_history(key)
    if data is not None and len(data["features"]) >= KNN_MIN_SAMPLES:
        feat_db = data["features"]
        ret_db = data["returns"]
    else:
        generic_key = f"generic_{symbol}"
        gdata = db.get_history(generic_key)
        if gdata is not None and len(gdata["features"]) >= KNN_MIN_SAMPLES:
            feat_db = gdata["features"]
            ret_db = gdata["returns"]
            key = generic_key
            data = gdata
            fallback_generic = True
        else:
            topic = "crypto" if symbol.endswith("USDC") else "equity"
            found_topic_key = None
            for db_key in db.get_all_keys():
                if not db_key.startswith("generic_"):
                    continue
                db_sym = db_key.replace("generic_", "")
                db_topic = "crypto" if db_sym.endswith("USDC") else "equity"
                tdata = db.get_history(db_key)
                if db_topic == topic and tdata and len(tdata["features"]) >= KNN_MIN_SAMPLES:
                    found_topic_key = db_key
                    break
            if found_topic_key:
                data = db.get_history(found_topic_key)
                feat_db = data["features"]
                ret_db = data["returns"]
                key = found_topic_key
                fallback_generic = True
            else:
                return None

    dim = len(current_features)
    db_dim = feat_db.shape[1]
    if db_dim != dim:
        if fallback_generic and dim > PRICE_SHAPE_WINDOW and db_dim > PRICE_SHAPE_WINDOW:
            current_features = current_features[-PRICE_SHAPE_WINDOW:]
            feat_db = feat_db[:, -PRICE_SHAPE_WINDOW:]
            dim = PRICE_SHAPE_WINDOW
        else:
            return None

    regimes = data.get("regimes", [])
    use_feat, use_ret = feat_db, ret_db
    if regime != "unknown" and regimes and len(regimes) == len(ret_db):
        regime_mask = np.array([r == regime for r in regimes])
        n_same = int(regime_mask.sum())
        if n_same >= KNN_MIN_SAMPLES:
            use_feat = feat_db[regime_mask]
            use_ret = ret_db[regime_mask]

    # L3: 漂移检测
    _drift_detected = False
    if bars:
        _drift_detected, _psi, _ks_p = detect_drift(use_ret, bars)
        if _drift_detected:
            plugin_log(f"[PLUGIN_KNN][DRIFT] {plugin_name}_{symbol} "
                       f"PSI={_psi:.3f} KS_p={_ks_p:.3f} → K×{DRIFT_K_MULTIPLIER}")

    # L3: 自适应K
    actual_k = min(adaptive_k(len(use_feat)), len(use_feat))
    if _drift_detected:
        actual_k = min(actual_k * DRIFT_K_MULTIPLIER, len(use_feat))

    _ext_dim = PRICE_SHAPE_WINDOW + VOL_SHAPE_WINDOW + ATR_WINDOW + 1
    indicator_dim = dim - _ext_dim
    if indicator_dim > 0:
        fw = np.concatenate([
            np.full(indicator_dim, INDICATOR_WEIGHT),
            np.full(PRICE_SHAPE_WINDOW, SHAPE_WEIGHT),
            np.full(VOL_SHAPE_WINDOW, 1.5),
            np.full(ATR_WINDOW, 2.0),
            np.full(1, 2.0),
        ])
    else:
        fw = np.ones(dim)

    sample_ages = None
    timestamps = data.get("timestamps", [])
    if timestamps and len(timestamps) == len(ret_db):
        ts_arr = np.array(timestamps, dtype=float)
        if len(use_ret) < len(ret_db) and regime != "unknown":
            regimes_list = data.get("regimes", [])
            if regimes_list and len(regimes_list) == len(ret_db):
                regime_mask = np.array([r == regime for r in regimes_list])
                ts_arr = ts_arr[regime_mask]
        if len(ts_arr) == len(use_ret):
            now_ts = time.time()
            sample_ages = (now_ts - ts_arr) / 86400.0
            sample_ages = np.clip(sample_ages, 0, 365)

    all_regimes = data.get("regimes", [])
    if len(use_ret) < len(ret_db) and regime != "unknown" and all_regimes:
        regime_mask_r = np.array([r == regime for r in all_regimes])
        use_regimes = [r for r, m in zip(all_regimes, regime_mask_r) if m]
    else:
        use_regimes = all_regimes if len(all_regimes) == len(use_ret) else []

    # L2: KNN匹配算法
    result = knn_match(current_features, use_feat, use_ret,
                       k=actual_k, feature_weights=fw,
                       sample_ages_days=sample_ages,
                       sample_regimes=use_regimes,
                       current_regime=regime)
    if _drift_detected and result:
        result.confidence *= DRIFT_CONFIDENCE_DECAY
        result.reason += f" [DRIFT: PSI={_psi:.3f}]"
    return result


# ============================================================
# 知识卡增强
# ============================================================
_KNOWLEDGE_CARDS_DIR = ROOT / ".GCC" / "skill" / "cards" / "plugin"
_knowledge_cache: dict = {}
_knowledge_cache_ts: float = 0


def load_plugin_knowledge_cards() -> dict:
    """加载外挂知识卡 → 提取可量化的交易规则"""
    global _knowledge_cache, _knowledge_cache_ts
    if time.time() - _knowledge_cache_ts < 300:
        return _knowledge_cache
    rules_file = ROOT / "state" / "plugin_knn_knowledge_rules.json"
    try:
        if rules_file.exists():
            with open(rules_file, "r", encoding="utf-8") as f:
                _knowledge_cache = json.load(f)
        else:
            _knowledge_cache = {}
    except Exception:
        _knowledge_cache = {}
    _knowledge_cache_ts = time.time()
    return _knowledge_cache


def _eval_simple_condition(condition: str, values: dict) -> bool:
    """安全评估简单条件表达式(支持and/or)"""
    if " and " in condition:
        parts = condition.split(" and ")
        return all(_eval_single(p.strip(), values) for p in parts)
    if " or " in condition:
        parts = condition.split(" or ")
        return any(_eval_single(p.strip(), values) for p in parts)
    return _eval_single(condition.strip(), values)


def _eval_single(expr: str, values: dict) -> bool:
    """评估单个比较: var op num"""
    m = re.match(r'(\w+)\s*(>=|<=|==|!=|>|<)\s*(-?[\d.]+)', expr)
    if not m:
        return False
    var_name, op, num_str = m.group(1), m.group(2), m.group(3)
    if var_name not in values:
        return False
    val = float(values[var_name])
    num = float(num_str)
    if op == ">": return val > num
    if op == "<": return val < num
    if op == ">=": return val >= num
    if op == "<=": return val <= num
    if op == "==": return abs(val - num) < 1e-9
    if op == "!=": return abs(val - num) >= 1e-9
    return False


def apply_knowledge_bias(plugin_name: str, action: str,
                         indicator_values: dict,
                         knn_result: PluginKNNResult | None) -> PluginKNNResult | None:
    """知识卡增强: 用知识卡规则调整KNN结果"""
    rules = load_plugin_knowledge_cards().get(plugin_name, [])
    if not rules:
        return knn_result

    matched_biases = []
    for rule in rules:
        try:
            condition = rule.get("condition", "")
            if not condition:
                continue
            if _eval_simple_condition(condition, indicator_values):
                matched_biases.append({
                    "bias": rule.get("bias", "NEUTRAL"),
                    "weight": float(rule.get("weight", 0.1)),
                    "source": rule.get("source", "unknown"),
                })
        except Exception:
            continue

    if not matched_biases:
        return knn_result

    buy_weight = sum(m["weight"] for m in matched_biases if m["bias"] == "BUY")
    sell_weight = sum(m["weight"] for m in matched_biases if m["bias"] == "SELL")
    kb_bias = "BUY" if buy_weight > sell_weight else ("SELL" if sell_weight > buy_weight else "NEUTRAL")
    kb_conf = abs(buy_weight - sell_weight)

    sources = [m["source"] for m in matched_biases[:3]]
    plugin_log(
        f"[PLUGIN_KNN][知识卡] {plugin_name} 匹配{len(matched_biases)}条规则 → "
        f"bias={kb_bias} conf={kb_conf:.2f} sources={sources}"
    )

    if knn_result is None:
        if kb_conf > 0.2:
            return PluginKNNResult(
                win_rate=0.5 + (0.1 if kb_bias == "BUY" else -0.1),
                avg_return=0.0,
                sample_count=0,
                best_match_dist=999,
                bias=kb_bias,
                confidence=min(kb_conf, 0.5),
                reason=f"知识卡: {', '.join(sources)}",
            )
        return None

    knn_weight = 0.7
    kb_weight_factor = 0.3
    if knn_result.bias == kb_bias and kb_bias != "NEUTRAL":
        boosted_conf = min(1.0, knn_result.confidence + kb_conf * kb_weight_factor)
        return PluginKNNResult(
            win_rate=knn_result.win_rate,
            avg_return=knn_result.avg_return,
            sample_count=knn_result.sample_count,
            best_match_dist=knn_result.best_match_dist,
            bias=knn_result.bias,
            confidence=boosted_conf,
            reason=f"{knn_result.reason} + 知识卡增强({', '.join(sources)})",
        )
    elif knn_result.bias != "NEUTRAL" and kb_bias != "NEUTRAL" and knn_result.bias != kb_bias:
        reduced_conf = max(0.0, knn_result.confidence - kb_conf * kb_weight_factor)
        return PluginKNNResult(
            win_rate=knn_result.win_rate,
            avg_return=knn_result.avg_return,
            sample_count=knn_result.sample_count,
            best_match_dist=knn_result.best_match_dist,
            bias=knn_result.bias if reduced_conf > 0.1 else "NEUTRAL",
            confidence=reduced_conf,
            reason=f"{knn_result.reason} + 知识卡冲突({', '.join(sources)})",
        )

    return knn_result


# ============================================================
# 统一接口: record_and_query
# ============================================================
def plugin_knn_record_and_query(
    plugin_name: str,
    symbol: str,
    features,
    action: str,
    close_price: float = 0,
    indicator_values: dict = None,
    regime: str = "unknown",
    bars: list = None,
) -> PluginKNNResult | None:
    """统一入口: 记录特征 + 查询KNN + 知识卡增强 → 返回结果"""
    try:
        if features is None:
            return None

        import time as _t
        _knn_t0 = _t.perf_counter()

        db = get_plugin_knn_db()
        db.record(plugin_name, symbol, features, action, close_price, regime=regime)

        if should_bypass_knn(plugin_name, symbol):
            plugin_log(f"[PLUGIN_KNN] {symbol} {plugin_name} KNN bypass (低准确率)")
            return None

        result = query_knn(db, plugin_name, symbol, features, regime=regime, bars=bars)

        _knn_elapsed = (_t.perf_counter() - _knn_t0) * 1000
        try:
            from dualpath_profiler import profiler as _dp
            _dp.record(f"knn_{plugin_name}_{symbol}", _knn_elapsed)
        except Exception:
            pass

        if indicator_values:
            result = apply_knowledge_bias(plugin_name, action, indicator_values, result)

        if result:
            plugin_log(
                f"[PLUGIN_KNN] {symbol} {plugin_name} {action} → "
                f"历史胜率{result.win_rate:.0%} "
                f"均收益{result.avg_return:.2%} "
                f"bias={result.bias} conf={result.confidence:.2f} "
                f"dist={result.best_match_dist:.2f} "
                f"n={result.sample_count}"
            )
        return result
    except Exception as e:
        logger.debug(f"[PLUGIN_KNN] {symbol} {plugin_name} 异常: {e}")
        return None


# ============================================================
# Phase2抑制
# ============================================================
def plugin_knn_should_suppress(action: str, knn_result: PluginKNNResult | None,
                                plugin_name: str = "", symbol: str = "") -> bool:
    """Phase2判断: KNN反向+高置信 → 应该抑制信号?"""
    if not knn_result:
        return False
    if knn_result.confidence < 0.3:
        return False

    phase2_active = PLUGIN_KNN_PHASE2
    if not phase2_active and plugin_name and symbol:
        key = f"{plugin_name}_{symbol}"
        acc_data = load_knn_accuracy()
        key_info = acc_data.get(key)
        if isinstance(key_info, dict) and key_info.get("total", 0) >= PHASE2_MIN_SAMPLES:
            phase2_active = True
            acc_val = key_info.get("accuracy", 1.0)
            if acc_val >= KNN_BYPASS_THRESHOLD:
                return False
            plugin_log(f"[KEY-007][Phase2] {key} 启用抑制检查 (样本={key_info['total']}, acc={acc_val:.2%})")

    if not phase2_active:
        return False

    if action == "BUY" and knn_result.bias == "SELL":
        return True
    if action == "SELL" and knn_result.bias == "BUY":
        return True
    return False
