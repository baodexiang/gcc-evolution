"""
modules/knn/alignment.py — L5 人类对齐
========================================
gcc-evo闭环: 准确率反哺Retriever、高精度经验卡自动创建、
gcc-evo反向调参、人类锚点准确率偏离检测。
gcc-evo五层架构: L5 人类对齐层
"""

import json
import time
import numpy as np
from datetime import datetime, timezone

from .models import (
    plugin_log, ROOT, _EVO_TUNE_FILE,
    KNN_MIN_SAMPLES,
)


# ============================================================
# GCC-0051: 准确率反哺Retriever
# ============================================================
def feedback_to_retriever(acc_map: dict):
    """KNN准确率反哺Retriever — 高准确率品种的知识卡获得更高检索权重"""
    try:
        from gcc_evolution.experience_store import GlobalMemory
    except ImportError:
        return

    try:
        gm = GlobalMemory()
        key007_cards = gm.get_by_key("KEY-007")
        if not key007_cards:
            gm.close()
            return

        updated = 0
        for db_key, info in acc_map.items():
            if db_key.startswith("_") or not isinstance(info, dict):
                continue
            acc = info.get("accuracy", 0)
            total = info.get("total", 0)
            if total < KNN_MIN_SAMPLES:
                continue
            parts = db_key.split("_", 1)
            if len(parts) < 2:
                continue
            plugin_name = parts[0].lower()
            symbol = parts[1].upper()
            for card in key007_cards:
                card_text = card.searchable_text().upper()
                if plugin_name.upper() in card_text or symbol in card_text:
                    if card.downstream_avg != acc:
                        card.downstream_avg = acc
                        gm.store(card)
                        updated += 1
        gm.close()
        if updated > 0:
            plugin_log(f"[KEY-007][RETRIEVER] 反哺{updated}张知识卡 downstream_avg")
    except Exception as e:
        plugin_log(f"[KEY-007][RETRIEVER] 反哺异常(静默): {e}")


# ============================================================
# GCC-0190: 高精度模式自动写经验卡
# ============================================================
def create_knn_experience_cards(acc_map: dict):
    """accuracy>70% + sample>=30 → 创建ExperienceCard, 30天去重"""
    try:
        from gcc_evolution.experience_store import GlobalMemory
        from gcc_evolution.models import ExperienceCard, ExperienceType
    except ImportError:
        return

    dedup_file = ROOT / "state" / "knn_card_dedup.json"
    dedup = {}
    if dedup_file.exists():
        try:
            dedup = json.loads(dedup_file.read_text())
        except Exception:
            dedup = {}

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_ts = time.time()
    created = 0

    try:
        gm = GlobalMemory()
        for db_key, info in acc_map.items():
            if db_key.startswith("_") or not isinstance(info, dict):
                continue
            acc = info.get("accuracy", 0)
            total = info.get("total", 0)
            if acc < 0.70 or total < 30:
                continue
            last_created = dedup.get(db_key, 0)
            if now_ts - last_created < 30 * 86400:
                continue
            parts = db_key.split("_", 1)
            if len(parts) < 2:
                continue
            plugin_name, symbol = parts[0], parts[1]
            card = ExperienceCard(
                exp_type=ExperienceType.SUCCESS,
                trigger_task_type="knn_pattern",
                trigger_symptom=f"{plugin_name} signal on {symbol}",
                trigger_keywords=[plugin_name.lower(), symbol.lower(), "knn", "high_accuracy"],
                strategy=f"KNN validates {plugin_name} signals for {symbol} with {acc:.0%} accuracy ({total} samples)",
                key_insight=f"{plugin_name} on {symbol} achieves {acc:.0%} win rate — trust this signal",
                confidence=round(min(acc, 0.95), 3),
                downstream_avg=round(acc, 4),
                key="KEY-007",
                tags=["knn", "auto_created", plugin_name.lower()],
                faithfulness_score=1.0,
                faithfulness_checked=True,
            )
            gm.store(card)
            dedup[db_key] = now_ts
            created += 1
            plugin_log(f"[KNN_CARD_CREATE] {db_key} acc={acc:.2%} n={total} → 经验卡已写入")

        gm.close()
        if dedup:
            dedup_file.write_text(json.dumps(dedup, indent=2))
        if created > 0:
            plugin_log(f"[KNN_CARD_CREATE] 本轮创建{created}张高精度经验卡")
    except Exception as e:
        plugin_log(f"[KNN_CARD_CREATE] 异常(静默): {e}")


# ============================================================
# GCC-0191: gcc-evo→KNN反向调参
# ============================================================
def sync_evo_tuning():
    """从gcc-evo高质量KEY-007经验卡提取模式, 生成参数调优建议"""
    try:
        from gcc_evolution.experience_store import GlobalMemory
    except ImportError:
        return

    try:
        gm = GlobalMemory()
        key007_cards = gm.get_by_key("KEY-007")
        gm.close()
        if not key007_cards:
            return

        elite = [c for c in key007_cards
                 if c.confidence >= 0.7 and c.downstream_avg >= 0.6]
        if not elite:
            return

        pattern_acc = {}
        for card in elite:
            for kw in card.trigger_keywords:
                if kw in ("knn", "high_accuracy", "auto_created"):
                    continue
                if kw not in pattern_acc:
                    pattern_acc[kw] = []
                pattern_acc[kw].append(card.downstream_avg)

        tune = {"_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

        avg_acc = np.mean([c.downstream_avg for c in elite]) if elite else 0.5
        if avg_acc > 0.75 and len(elite) >= 5:
            tune["k_adjust"] = "sharper"
            tune["suggested_k_cap"] = 50
            plugin_log(f"[KNN_EVO_TUNE] 高精度模式(avg={avg_acc:.2%}) → K上限降至50")
        elif avg_acc < 0.55:
            tune["k_adjust"] = "smoother"
            tune["suggested_k_cap"] = 100
            plugin_log(f"[KNN_EVO_TUNE] 低精度模式(avg={avg_acc:.2%}) → K上限升至100")

        tune["elite_count"] = len(elite)
        tune["avg_accuracy"] = round(avg_acc, 4)
        tune["patterns"] = {k: round(np.mean(v), 4) for k, v in pattern_acc.items()
                            if len(v) >= 2}

        _EVO_TUNE_FILE.write_text(json.dumps(tune, indent=2, ensure_ascii=False))
        plugin_log(f"[KNN_EVO_TUNE] 同步{len(elite)}张精英卡 → {_EVO_TUNE_FILE.name}")
    except Exception as e:
        plugin_log(f"[KNN_EVO_TUNE] 异常(静默): {e}")


# ============================================================
# GCC-0192: L5人类锚点 — KNN准确率偏离检测
# ============================================================
def check_accuracy_drift(acc_map: dict):
    """对比实际准确率 vs 人工预期阈值, 偏离>15%触发告警"""
    anchor_file = ROOT / "state" / "knn_accuracy_anchors.json"
    drift_log_file = ROOT / "state" / "knn_drift_log.jsonl"

    if not anchor_file.exists():
        default_anchors = {
            "_comment": "人工设定各品种KNN准确率预期阈值, min=最低容忍, expected=预期水平",
            "_template": {"min_accuracy": 0.45, "expected_accuracy": 0.60},
        }
        try:
            anchor_file.write_text(json.dumps(default_anchors, indent=2))
            plugin_log("[KNN_DRIFT] 创建默认锚点模板: state/knn_accuracy_anchors.json")
        except Exception:
            pass
        return

    try:
        anchors = json.loads(anchor_file.read_text())
    except Exception:
        return

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    drift_events = []

    for db_key, info in acc_map.items():
        if db_key.startswith("_") or not isinstance(info, dict):
            continue
        acc = info.get("accuracy", 0)
        total = info.get("total", 0)
        if total < 20:
            continue

        anchor = anchors.get(db_key, anchors.get("_template"))
        if not anchor or not isinstance(anchor, dict):
            continue

        expected = anchor.get("expected_accuracy", 0.60)
        min_acc = anchor.get("min_accuracy", 0.45)
        drift_delta = expected - acc

        if drift_delta > 0.15:
            event = {
                "ts": now_str,
                "key": db_key,
                "actual": round(acc, 4),
                "expected": expected,
                "min": min_acc,
                "drift": round(drift_delta, 4),
                "level": "CRITICAL" if acc < min_acc else "WARNING",
                "total": total,
            }
            drift_events.append(event)
            plugin_log(f"[KNN_DRIFT] {event['level']} {db_key} "
                       f"actual={acc:.2%} expected={expected:.2%} "
                       f"drift={drift_delta:.2%} n={total}")

    if drift_events:
        try:
            with open(drift_log_file, "a") as f:
                for ev in drift_events:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception:
            pass
