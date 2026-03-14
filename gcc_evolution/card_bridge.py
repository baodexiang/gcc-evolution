"""CardBridge v1.1 — 知识卡活化桥接层 + 因果记忆检索

v1.0: 扫描JSON卡片 → 建立索引 → 规则匹配 → 蒸馏
v1.1: + 因果记忆检索 (arXiv:2601.11958 Agentic Nowcasting Layer B)
      record_activation()带市场情境 → query_contextual()按情境聚合历史正确率
      → 返回"在当前情境下表现最好的规则"，不是简单的全量匹配

数据流:
  skill/cards/**/*.json  ← Source of Truth
  state/card_index.json  ← 索引 (启动时生成)
  state/card_activations.jsonl  ← 激活日志 (追加写入, v1.1含情境字段)
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")

# Paths — gcc_evolution/card_bridge.py → gcc_evolution/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CARDS_ROOT = _PROJECT_ROOT / ".GCC" / "skill" / "cards"
_STATE_DIR = _PROJECT_ROOT / "state"
_INDEX_PATH = _STATE_DIR / "card_index.json"
_ACTIVATIONS_PATH = _STATE_DIR / "card_activations.jsonl"

import sys

# GCC-0199: 回调注入日志 — 默认print, 主程序可通过set_card_bridge_logger注入log_to_server
_logger_fn = None  # 由主程序注入


def set_card_bridge_logger(fn):
    """GCC-0199: 主程序调用此函数注入log_to_server, 解耦循环依赖"""
    global _logger_fn
    _logger_fn = fn


def _log(msg: str):
    """CardBridge 内部日志。优先用注入的logger(写server.log), 回退print"""
    tagged = f"[CARD-BRIDGE] {msg}"
    if _logger_fn:
        try:
            _logger_fn(tagged)
            return
        except Exception:
            pass
    print(tagged, flush=True)

class CardBridge:
    """知识卡活化桥接层"""

    def __init__(self, cards_root=None):
        self._cards_root = Path(cards_root) if cards_root else _CARDS_ROOT
        self._cards = {}        # {card_id: card_dict}
        self._by_module = {}    # {module: [card_id, ...]}
        self._by_type = {}      # {type: [card_id, ...]}
        self._activation_buf = []  # 激活日志缓冲

    # ── 索引 ──────────────────────────────────────────────

    def load_index(self) -> int:
        """扫描所有 *.json 卡片，建立索引。返回索引卡片数量。"""
        self._cards.clear()
        self._by_module.clear()
        self._by_type.clear()

        for json_path in self._cards_root.rglob("*.json"):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    card = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            card_id = card.get("id")
            if not card_id:
                continue

            # 保存路径以便蒸馏后回写
            card["_path"] = str(json_path)
            self._cards[card_id] = card

            # 按 module 索引
            module = (card.get("system_mapping") or {}).get("module", "")
            if module:
                self._by_module.setdefault(module, []).append(card_id)

            # 按 type 索引
            ctype = card.get("type", "")
            if ctype:
                self._by_type.setdefault(ctype, []).append(card_id)

        # 持久化索引
        self._save_index()
        modules = list(self._by_module.keys())
        _log(f"[INDEX] 加载完成: {len(self._cards)}张卡, 模块={modules}")
        return len(self._cards)

    def _save_index(self):
        """保存索引到 state/card_index.json"""
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        index = {
            "updated": datetime.now(_NY).isoformat(),
            "total": len(self._cards),
            "by_module": {m: ids for m, ids in self._by_module.items()},
            "by_type": {t: ids for t, ids in self._by_type.items()},
            "cards": {
                cid: {
                    "title": c.get("title", ""),
                    "type": c.get("type", ""),
                    "confidence": c.get("confidence", 0.5),
                    "quality": c.get("quality", "extracted"),
                    "module": (c.get("system_mapping") or {}).get("module", ""),
                    "rules_count": len(c.get("rules", [])),
                }
                for cid, c in self._cards.items()
            },
        }
        with open(_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    # ── 查询 ──────────────────────────────────────────────

    def query(self, module=None, card_type=None, keywords=None,
              min_confidence=0.3) -> list:
        """查询匹配的知识卡规则。

        返回: [{card_id, title, rules, confidence, quality, module}, ...]
        """
        candidates = set(self._cards.keys())

        if module:
            candidates &= set(self._by_module.get(module, []))
        if card_type:
            candidates &= set(self._by_type.get(card_type, []))

        results = []
        for cid in candidates:
            card = self._cards[cid]
            conf = card.get("confidence", 0.5)
            if conf < min_confidence:
                continue

            # 关键词过滤 (标题 + summary)
            if keywords:
                haystack = (card.get("title", "") + " " +
                            (card.get("content", {}).get("summary", ""))).lower()
                if not any(kw.lower() in haystack for kw in keywords):
                    continue

            results.append({
                "card_id": cid,
                "title": card.get("title", ""),
                "rules": card.get("rules", []),
                "confidence": conf,
                "quality": card.get("quality", "extracted"),
                "module": (card.get("system_mapping") or {}).get("module", ""),
            })

        # 按confidence降序
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results

    # ── 因果记忆检索 (v1.1, arXiv:2601.11958 Layer B) ────

    def query_contextual(self, module=None, card_type=None,
                         context=None, min_samples=3) -> list:
        """因果记忆检索: 返回在当前情境下历史表现最好的规则。

        与 query() 的区别:
          query()     → 返回所有confidence>=阈值的卡, 按静态confidence排序
          contextual  → 读历史激活+结果, 按"当前情境下的实际正确率"排序

        context: {"trend": "UP", "regime": "bull", ...}
        min_samples: 至少N次同情境激活才参与排名(防小样本)

        返回: [{card_id, title, rules, confidence, ctx_correct_rate,
                ctx_samples, module, rank_source}, ...]
              rank_source="causal" 表示有因果数据排序
              rank_source="static" 表示回退到静态confidence
        """
        # 1. 先用 query() 获取候选卡, 跳过deprecated
        candidates = self.query(module=module, card_type=card_type,
                                min_confidence=0.0)  # 不用confidence过滤,让因果数据说话
        # 加载deprecated列表, 过滤掉已淘汰的卡
        _dep_file = _STATE_DIR / "card_deprecated.json"
        _deprecated = set()
        if _dep_file.exists():
            try:
                _deprecated = set(json.loads(_dep_file.read_text(encoding="utf-8")))
            except Exception:
                pass
        if _deprecated:
            candidates = [c for c in candidates if c["card_id"] not in _deprecated]
        if not candidates:
            return []

        # 2. 加载因果记忆
        causal = self._load_causal_memory(context)

        # 3. 给每张卡打因果分
        for card in candidates:
            cid = card["card_id"]
            mem = causal.get(cid)
            if mem and mem["total"] >= min_samples:
                card["ctx_correct_rate"] = mem["correct"] / mem["total"]
                card["ctx_samples"] = mem["total"]
                card["rank_source"] = "causal"
            else:
                card["ctx_correct_rate"] = None
                card["ctx_samples"] = mem["total"] if mem else 0
                card["rank_source"] = "static"

        # 4. 排序: 有因果数据的按正确率降序排前面, 没有的按confidence排后面
        causal_cards = [c for c in candidates if c["rank_source"] == "causal"]
        static_cards = [c for c in candidates if c["rank_source"] == "static"]
        causal_cards.sort(key=lambda x: x["ctx_correct_rate"], reverse=True)
        static_cards.sort(key=lambda x: x["confidence"], reverse=True)

        # 因果数据中正确率 < 30% 的降到末尾(flagged)
        good = [c for c in causal_cards if c["ctx_correct_rate"] >= 0.30]
        bad = [c for c in causal_cards if c["ctx_correct_rate"] < 0.30]

        return good + static_cards + bad

    def _load_causal_memory(self, context=None) -> dict:
        """加载因果记忆: 按情境过滤历史激活, 聚合每张卡的正确率。

        返回: {card_id: {"total": int, "correct": int}}
        """
        if not _ACTIVATIONS_PATH.exists():
            return {}

        # 解析情境匹配条件
        want_trend = (context or {}).get("trend", "").upper()
        want_regime = (context or {}).get("regime", "").lower()

        activations = {}   # {card_id: [activation_entries]}
        outcomes = {}      # {(card_id, symbol): [bool, ...]}

        with open(_ACTIVATIONS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cid = entry.get("card_id", "")
                if entry.get("type") == "outcome":
                    key = (cid, entry.get("symbol", ""))
                    outcomes.setdefault(key, []).append(entry.get("correct", False))
                elif entry.get("result") in ("correct", "incorrect"):
                    # gcc-tm经验卡: 激活+结果在同一条记录里
                    ctx = entry.get("ctx", {})
                    if want_trend and ctx.get("trend", "").upper() != want_trend:
                        continue
                    if want_regime and ctx.get("regime", "").lower() != want_regime:
                        continue
                    activations.setdefault(cid, []).append(entry)
                    key = (cid, entry.get("symbol", ""))
                    outcomes.setdefault(key, []).append(entry["result"] == "correct")
                else:
                    # 知识卡激活: 结果后续通过 outcome 条目回填
                    ctx = entry.get("ctx", {})
                    if want_trend and ctx.get("trend", "").upper() != want_trend:
                        continue
                    if want_regime and ctx.get("regime", "").lower() != want_regime:
                        continue
                    activations.setdefault(cid, []).append(entry)

        # 聚合: 把outcome按card_id汇总
        card_stats = {}
        all_outcomes_by_card = defaultdict(list)
        for (cid, sym), results in outcomes.items():
            all_outcomes_by_card[cid].extend(results)

        for cid in set(list(activations.keys()) + list(all_outcomes_by_card.keys())):
            outs = all_outcomes_by_card.get(cid, [])
            card_stats[cid] = {
                "total": len(outs),
                "correct": sum(1 for o in outs if o),
            }

        return card_stats

    # ── 激活记录 ──────────────────────────────────────────

    def record_activation(self, card_id, rule_index, symbol, action,
                          price, result=None, context=None):
        """记录规则激活事件 (主程序调用)。追加到 card_activations.jsonl

        v1.1: context字典存储市场情境, 用于因果记忆检索:
          {"trend": "UP/DOWN/SIDE", "regime": "bull/bear/sideways",
           "volatility": "high/low", "pos_ratio": 0.0~1.0}
        """
        entry = {
            "ts": datetime.now(_NY).isoformat(),
            "card_id": card_id,
            "rule_index": rule_index,
            "symbol": symbol,
            "action": action,
            "price": price,
            "result": result,  # None=待验证, "correct"/"incorrect"
        }
        if context:
            entry["ctx"] = context
        self._activation_buf.append(entry)
        self._flush_activations()
        _log(f"[ACTIVATION] {symbol} {action} card={card_id} rule#{rule_index} price={price}")

    def record_outcome(self, card_id, rule_index, symbol, correct: bool):
        """回填结果 (16h后验证)"""
        entry = {
            "ts": datetime.now(_NY).isoformat(),
            "card_id": card_id,
            "rule_index": rule_index,
            "symbol": symbol,
            "type": "outcome",
            "correct": correct,
        }
        self._activation_buf.append(entry)
        self._flush_activations()

    def _flush_activations(self):
        """写入缓冲到 JSONL 文件"""
        if not self._activation_buf:
            return
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_ACTIVATIONS_PATH, "a", encoding="utf-8") as f:
            for entry in self._activation_buf:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._activation_buf.clear()

    # ── 蒸馏 ──────────────────────────────────────────────

    def distill(self) -> dict:
        """蒸馏: 计算每张卡的有效性。

        读 card_activations.jsonl → 按card_id聚合 →
        更新卡片JSON的confidence/quality字段。

        返回: {card_id: {activations, outcomes, correct_rate, new_confidence, status}}
        """
        # 读取所有激活记录
        activations = defaultdict(list)   # {card_id: [activation_entries]}
        outcomes = defaultdict(list)      # {card_id: [outcome_entries]}

        if _ACTIVATIONS_PATH.exists():
            with open(_ACTIVATIONS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cid = entry.get("card_id", "")
                    if entry.get("type") == "outcome":
                        outcomes[cid].append(entry)
                    else:
                        activations[cid].append(entry)

        report = {}
        now = datetime.now(_NY)

        for cid, card in self._cards.items():
            act_count = len(activations.get(cid, []))
            out_list = outcomes.get(cid, [])
            out_count = len(out_list)
            correct_count = sum(1 for o in out_list if o.get("correct"))
            correct_rate = correct_count / out_count if out_count > 0 else None

            # 判断最后激活时间
            last_act_ts = None
            if activations.get(cid):
                try:
                    last_act_ts = max(a["ts"] for a in activations[cid])
                except (KeyError, ValueError):
                    pass

            # 蒸馏规则
            status = "active"
            new_confidence = card.get("confidence", 0.5)

            if out_count >= 5:  # GCC-0198: 降低阈値 10→　(2025-03-08)
                if correct_rate >= 0.70:
                    status = "validated"
                    new_confidence = 0.9
                elif correct_rate < 0.30:
                    status = "flagged"
                    new_confidence = 0.3

            # 6个月无激活 → stale
            if last_act_ts:
                try:
                    last_dt = datetime.fromisoformat(last_act_ts)
                    if (now - last_dt) > timedelta(days=180):
                        status = "stale"
                except (ValueError, TypeError):
                    pass
            elif act_count == 0:
                # 从未激活但已存在较久
                status = "inactive"

            # 回写卡片
            if status in ("validated", "flagged"):
                card["confidence"] = new_confidence
                card["quality"] = status
                self._write_card(card)

            report[cid] = {
                "title": card.get("title", ""),
                "activations": act_count,
                "outcomes": out_count,
                "correct_rate": round(correct_rate, 3) if correct_rate is not None else None,
                "new_confidence": new_confidence,
                "status": status,
            }

        validated = sum(1 for v in report.values() if v["status"] == "validated")
        flagged   = sum(1 for v in report.values() if v["status"] == "flagged")
        inactive  = sum(1 for v in report.values() if v["status"] == "inactive")
        _log(f"[DISTILL] 总卡={len(report)}, 有效激活={", ".join(str(v['activations']) for v in report.values() if v['activations']>0)[:60] or '0条'}, "
             f"validated={validated} flagged={flagged} inactive={inactive}")
        return report

    def prune_deprecated(self) -> dict:
        """定期淘汰: 将低正确率的卡标记为deprecated, query_contextual会跳过。

        淘汰规则:
          知识卡: 正确率<30% 且样本≥5 → deprecated
          经验卡: 正确率<20% 且样本≥5 → deprecated

        返回: {deprecated: int, total_checked: int, details: [...]}
        """
        causal = self._load_causal_memory()
        deprecated_list = []

        # 读取已有的deprecated列表
        _dep_file = _STATE_DIR / "card_deprecated.json"
        existing = set()
        if _dep_file.exists():
            try:
                existing = set(json.loads(_dep_file.read_text(encoding="utf-8")))
            except Exception:
                pass

        for cid, stats in causal.items():
            if stats["total"] < 5:
                continue
            rate = stats["correct"] / stats["total"]
            is_exp = cid.startswith("EXP_TM_")
            threshold = 0.20 if is_exp else 0.30

            if rate < threshold:
                existing.add(cid)
                deprecated_list.append({
                    "card_id": cid,
                    "type": "experience" if is_exp else "knowledge",
                    "correct_rate": round(rate, 3),
                    "samples": stats["total"],
                })

        # 写入deprecated列表
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _dep_file.write_text(
            json.dumps(sorted(existing), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        _log(f"[PRUNE] 淘汰{len(deprecated_list)}张卡 (总检查{len(causal)})")
        return {
            "deprecated": len(deprecated_list),
            "total_checked": len(causal),
            "details": deprecated_list,
        }

    def distill_to_skills(self) -> dict:
        """蒸馏: 正确率>60%且样本≥10的卡 → 提取为skill写入gcc_skills.json。

        知识卡: 合并相似规则为一条skill
        经验卡: 提取品种×方向的特征模式为skill

        蒸馏后源卡标记distilled, 不再参与card层评分。
        返回: {new_skills: int, distilled_cards: int, skills: [...]}
        """
        causal = self._load_causal_memory()
        _skills_file = _STATE_DIR / "gcc_skills.json"
        _distilled_file = _STATE_DIR / "card_distilled.json"

        # 加载已有skill和已蒸馏列表
        existing_skills = []
        if _skills_file.exists():
            try:
                existing_skills = json.loads(_skills_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing_ids = {s.get("skill_id") for s in existing_skills}

        distilled_set = set()
        if _distilled_file.exists():
            try:
                distilled_set = set(json.loads(_distilled_file.read_text(encoding="utf-8")))
            except Exception:
                pass

        new_skills = []
        newly_distilled = []

        for cid, stats in causal.items():
            if cid in distilled_set:
                continue  # 已蒸馏过
            if stats["total"] < 10:
                continue  # 样本不足
            rate = stats["correct"] / stats["total"]
            if rate < 0.60:
                continue  # 不够好

            is_exp = cid.startswith("EXP_TM_")
            skill_id = f"SK_{cid}"
            if skill_id in existing_ids:
                continue  # 已存在

            if is_exp:
                # 经验卡: EXP_TM_BTCUSDC_BUY → 品种方向模式
                parts = cid.replace("EXP_TM_", "").rsplit("_", 1)
                sym = parts[0] if len(parts) == 2 else cid
                act = parts[1] if len(parts) == 2 else "BUY"
                skill = {
                    "skill_id": skill_id,
                    "type": "experience",
                    "name": f"{sym} {act} 实战验证模式",
                    "direction": act,
                    "symbols": [sym],
                    "correct_rate": round(rate, 3),
                    "samples": stats["total"],
                    "source_cards": [cid],
                    "created": datetime.now(_NY).isoformat(),
                }
            else:
                # 知识卡: 从卡片内容提取规则
                card = self._cards.get(cid, {})
                rules = card.get("rules", [])
                rule_text = ""
                if rules:
                    rule_text = str(rules[0].get("then", "") if isinstance(rules[0], dict) else rules[0])
                # 方向推断
                direction = "NEUTRAL"
                rt = rule_text.upper()
                if any(w in rt for w in ("买", "BUY", "做多", "LONG", "BULLISH")):
                    direction = "BUY"
                elif any(w in rt for w in ("卖", "SELL", "做空", "SHORT", "BEARISH")):
                    direction = "SELL"

                skill = {
                    "skill_id": skill_id,
                    "type": "knowledge",
                    "name": card.get("title", cid)[:80],
                    "direction": direction,
                    "rule": rule_text[:200],
                    "correct_rate": round(rate, 3),
                    "samples": stats["total"],
                    "source_cards": [cid],
                    "created": datetime.now(_NY).isoformat(),
                }

            new_skills.append(skill)
            newly_distilled.append(cid)

        # 写入
        if new_skills:
            all_skills = existing_skills + new_skills
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            _skills_file.write_text(
                json.dumps(all_skills, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            distilled_set.update(newly_distilled)
            _distilled_file.write_text(
                json.dumps(sorted(distilled_set), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log(f"[DISTILL→SKILL] 新增{len(new_skills)}条skill, 蒸馏{len(newly_distilled)}张卡")

        return {
            "new_skills": len(new_skills),
            "distilled_cards": len(newly_distilled),
            "skills": new_skills,
        }

    @staticmethod
    def is_deprecated(card_id: str) -> bool:
        """检查卡是否被淘汰"""
        _dep_file = _STATE_DIR / "card_deprecated.json"
        if not _dep_file.exists():
            return False
        try:
            deprecated = json.loads(_dep_file.read_text(encoding="utf-8"))
            return card_id in deprecated
        except Exception:
            return False

    def _write_card(self, card):
        """回写卡片JSON (更新confidence/quality)"""
        path = card.get("_path")
        if not path or not os.path.exists(path):
            return
        # 读原始文件保留格式
        try:
            with open(path, "r", encoding="utf-8") as f:
                original = json.load(f)
            original["confidence"] = card["confidence"]
            original["quality"] = card["quality"]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(original, f, ensure_ascii=False, indent=2)
        except (OSError, json.JSONDecodeError):
            pass

    # ── 报告 ──────────────────────────────────────────────

    def get_effectiveness_report(self) -> str:
        """生成蒸馏报告 (gcc-evo card-report 命令用)"""
        report = self.distill()
        if not report:
            return "  No card data available."

        lines = [
            f"  ✦ Card Effectiveness Report",
            f"  {'═' * 55}",
            f"  Total cards: {len(report)}",
            "",
        ]

        # 分组统计
        by_status = defaultdict(list)
        for cid, info in report.items():
            by_status[info["status"]].append((cid, info))

        status_icons = {
            "validated": "✅", "active": "🔵", "flagged": "⚠️",
            "stale": "💤", "inactive": "⬜",
        }

        for status in ["validated", "active", "flagged", "stale", "inactive"]:
            items = by_status.get(status, [])
            if not items:
                continue
            icon = status_icons.get(status, "?")
            lines.append(f"  {icon} {status.upper()} ({len(items)})")
            for cid, info in sorted(items, key=lambda x: -(x[1]["activations"])):
                rate_str = f"{info['correct_rate']:.0%}" if info["correct_rate"] is not None else "n/a"
                lines.append(
                    f"     {cid}: {info['title'][:30]} "
                    f"act={info['activations']} rate={rate_str} "
                    f"conf={info['new_confidence']:.1f}"
                )
            lines.append("")

        return "\n".join(lines)

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> dict:
        """返回索引统计"""
        return {
            "total": len(self._cards),
            "modules": {m: len(ids) for m, ids in self._by_module.items()},
            "types": {t: len(ids) for t, ids in self._by_type.items()},
        }


# ========================================================================
# GCC-0174 S5a-S5c: 知识卡4H价格回填 + 准确率统计 + Phase门控
# ========================================================================

import threading as _threading174
import logging as _logging174

_CARD_ACC_FILE = _STATE_DIR / "card_signal_accuracy.json"
_CARD_ACC_LAST_RUN = 0.0
_CARD_ACC_LOCK = _threading174.Lock()
_CARD_PHASE_CACHE: dict = {}
_CARD_PHASE_CACHE_TS: float = 0.0


def card_acc_backfill():
    """S5a+S5b: 读card_activations.jsonl, 4H后回填价格判对错, 统计准确率。

    流程:
    1. 读JSONL中result=None且ts超过4H的记录
    2. 用yfinance取4H后价格, 判CORRECT/INCORRECT/NEUTRAL
    3. 写回outcome到JSONL
    4. 按card_id×symbol聚合准确率, 写state/card_signal_accuracy.json

    5分钟最多跑一次。
    """
    global _CARD_ACC_LAST_RUN
    with _CARD_ACC_LOCK:
        now = time.time()
        if now - _CARD_ACC_LAST_RUN < 300:
            return
        _CARD_ACC_LAST_RUN = now

    if not _ACTIVATIONS_PATH.exists():
        return

    # 读所有记录
    activations = []  # result=None, 待回填
    outcomes = []     # type=outcome, 已有结果
    all_lines = []

    with open(_ACTIVATIONS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            all_lines.append(entry)
            if entry.get("type") == "outcome":
                outcomes.append(entry)
            elif entry.get("result") is None:
                activations.append(entry)

    # 回填: 找超过4H且未验证的激活
    now_dt = datetime.now(_NY)
    backfilled_outcomes = []

    for act in activations:
        ts_str = act.get("ts", "")
        try:
            act_dt = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue

        # 需要超过4H
        if (now_dt - act_dt).total_seconds() < 4 * 3600:
            continue

        # 已有outcome则跳过
        cid = act.get("card_id", "")
        sym = act.get("symbol", "")
        price_at = act.get("price", 0)
        if not cid or not sym or not price_at:
            continue

        # 检查是否已有此激活的outcome
        already_has = any(
            o.get("card_id") == cid and o.get("symbol") == sym
            and abs(datetime.fromisoformat(o.get("ts", "1970-01-01")).timestamp()
                    - act_dt.timestamp()) < 300
            for o in outcomes
        )
        if already_has:
            continue

        # 取4H后价格
        try:
            from timeframe_params import REVERSE_SYMBOL_MAP
            yf_sym = sym
            for yf_s, main_s in REVERSE_SYMBOL_MAP.items():
                if main_s == sym:
                    yf_sym = yf_s
                    break

            import yfinance as yf
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="2d", interval="1h")
            if hist.empty:
                continue

            # 找4H后的收盘价
            target_dt = act_dt + timedelta(hours=4)
            # 取最接近target_dt的行
            hist.index = hist.index.tz_convert(_NY) if hist.index.tz else hist.index.tz_localize(_NY)
            closest_idx = hist.index.searchsorted(target_dt)
            if closest_idx >= len(hist):
                closest_idx = len(hist) - 1
            price_4h = float(hist.iloc[closest_idx]["Close"])

            # 判断: action=UP→涨=CORRECT, action=DOWN→跌=CORRECT
            action = act.get("action", "").upper()
            pct_change = (price_4h - price_at) / price_at * 100

            if abs(pct_change) < 0.5:
                result = "NEUTRAL"
                correct = None
            elif action in ("UP", "BUY"):
                correct = pct_change > 0
                result = "CORRECT" if correct else "INCORRECT"
            elif action in ("DOWN", "SELL"):
                correct = pct_change < 0
                result = "CORRECT" if correct else "INCORRECT"
            else:
                result = "NEUTRAL"
                correct = None

            # 记录outcome
            if correct is not None:
                backfilled_outcomes.append({
                    "ts": now_dt.isoformat(),
                    "card_id": cid,
                    "rule_index": act.get("rule_index", 0),
                    "symbol": sym,
                    "type": "outcome",
                    "correct": correct,
                    "price_at_signal": price_at,
                    "price_4h_later": price_4h,
                    "pct_change": round(pct_change, 2),
                })
                outcomes.append(backfilled_outcomes[-1])

        except Exception:
            continue

    # 追加outcome到JSONL
    if backfilled_outcomes:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_ACTIVATIONS_PATH, "a", encoding="utf-8") as f:
            for entry in backfilled_outcomes:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # S5b: 统计 card_id × symbol 准确率
    stats = {}
    overall = {"correct": 0, "incorrect": 0, "neutral": 0, "decisive": 0}

    for o in outcomes:
        if o.get("type") != "outcome":
            continue
        cid = o.get("card_id", "")
        sym = o.get("symbol", "")
        key = f"{cid}_{sym}"
        correct = o.get("correct")

        if key not in stats:
            stats[key] = {"card_id": cid, "symbol": sym,
                          "correct": 0, "incorrect": 0, "decisive": 0}

        if correct is True:
            stats[key]["correct"] += 1
            stats[key]["decisive"] += 1
            overall["correct"] += 1
            overall["decisive"] += 1
        elif correct is False:
            stats[key]["incorrect"] += 1
            stats[key]["decisive"] += 1
            overall["incorrect"] += 1
            overall["decisive"] += 1

    # Phase建议
    entries = {}
    for key, s in stats.items():
        decisive = s["decisive"]
        acc = s["correct"] / decisive if decisive > 0 else 0
        if decisive >= 8 and acc >= 0.60:
            phase = 2
        elif decisive >= 5 and acc < 0.35:
            phase = 1
        else:
            phase = 0
        entries[key] = {
            "card_id": s["card_id"], "symbol": s["symbol"],
            "correct": s["correct"], "incorrect": s["incorrect"],
            "decisive": decisive, "accuracy": round(acc, 4),
            "suggested_phase": phase,
        }

    ov_decisive = overall["decisive"]
    result_data = {
        "updated_at": datetime.now(_NY).strftime("%Y-%m-%d %H:%M:%S"),
        "overall": {
            "correct": overall["correct"], "incorrect": overall["incorrect"],
            "decisive": ov_decisive,
            "accuracy": round(overall["correct"] / ov_decisive, 4) if ov_decisive > 0 else 0,
        },
        "backfilled": len(backfilled_outcomes),
        "entries": entries,
    }

    try:
        _CARD_ACC_FILE.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
        _logging174.getLogger("CardBridge").info(
            f"[GCC-0174][CARD_ACC] 回填完成: +{len(backfilled_outcomes)}条, "
            f"{ov_decisive}decisive, acc={result_data['overall']['accuracy']:.1%}")
    except Exception as _e:
        _logging174.getLogger("CardBridge").warning(
            f"[GCC-0174][CARD_ACC] 写入失败: {_e}")


_CARD_KNN_EVO_FILE = _STATE_DIR / "card_knn_evolution.jsonl"
_CARD_KNN_LAST_RUN = 0.0
_CARD_KNN_LOCK = _threading174.Lock()


def card_knn_evolve():
    """每日KNN进化: 读accuracy→更新confidence/quality→记录升降级。24h节流。"""
    global _CARD_KNN_LAST_RUN
    with _CARD_KNN_LOCK:
        now = time.time()
        if now - _CARD_KNN_LAST_RUN < 24 * 3600:
            return
        _CARD_KNN_LAST_RUN = now

    if not _CARD_ACC_FILE.exists():
        _logging174.getLogger("CardBridge").info("[GCC-0174][KNN] card_signal_accuracy.json不存在, 跳过")
        return

    try:
        data = json.loads(_CARD_ACC_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _logging174.getLogger("CardBridge").warning(f"[GCC-0174][KNN] 读取accuracy失败: {e}")
        return

    entries = data.get("entries", {})
    if not entries:
        return

    # 按card_id聚合所有symbol数据
    card_agg = defaultdict(lambda: {"correct": 0, "incorrect": 0, "decisive": 0})
    for key, ent in entries.items():
        cid = ent.get("card_id", "")
        if not cid:
            continue
        card_agg[cid]["correct"] += ent.get("correct", 0)
        card_agg[cid]["incorrect"] += ent.get("incorrect", 0)
        card_agg[cid]["decisive"] += ent.get("decisive", 0)

    # KNN评分 + 回写卡片 + 记录日志
    evo_lines = []
    now_ts = datetime.now(_NY).isoformat()
    promote_n = demote_n = archive_n = 0

    for cid, agg in card_agg.items():
        decisive = agg["decisive"]
        accuracy = agg["correct"] / decisive if decisive > 0 else 0

        # 读卡片当前状态
        card_path = None
        old_conf = 0.5
        old_quality = "extracted"
        for jp in _CARDS_ROOT.rglob("*.json"):
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    c = json.load(f)
                if c.get("id") == cid:
                    card_path = jp
                    old_conf = c.get("confidence", 0.5)
                    old_quality = c.get("quality", "extracted")
                    break
            except (json.JSONDecodeError, OSError):
                continue

        # KNN评分规则
        if decisive < 5:
            action = "hold"
            new_conf = 0.5
            new_quality = old_quality  # 样本不足，保持原样
        elif accuracy >= 0.70 and decisive >= 10:
            action = "promote"
            new_conf = 0.9
            new_quality = "validated"
            promote_n += 1
        elif accuracy >= 0.55 and decisive >= 8:
            action = "trusted"
            new_conf = 0.7
            new_quality = "active"
        elif accuracy < 0.20 and decisive >= 10:
            action = "archive"
            new_conf = 0.1
            new_quality = "inactive"
            archive_n += 1
        elif accuracy < 0.35 and decisive >= 5:
            action = "demote"
            new_conf = 0.3
            new_quality = "flagged"
            demote_n += 1
        else:
            action = "hold"
            new_conf = round(0.5 * (1 + accuracy), 3)
            new_quality = old_quality

        # 回写卡片JSON
        if card_path and (new_conf != old_conf or new_quality != old_quality):
            try:
                with open(card_path, "r", encoding="utf-8") as f:
                    original = json.load(f)
                original["confidence"] = new_conf
                original["quality"] = new_quality
                with open(card_path, "w", encoding="utf-8") as f:
                    json.dump(original, f, ensure_ascii=False, indent=2)
            except (OSError, json.JSONDecodeError):
                pass

        # 进化日志
        evo_lines.append(json.dumps({
            "ts": now_ts, "card_id": cid, "action": action,
            "accuracy": round(accuracy, 4), "decisive": decisive,
            "old_conf": old_conf, "new_conf": new_conf,
        }, ensure_ascii=False))

    # 追加写入进化JSONL
    if evo_lines:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CARD_KNN_EVO_FILE, "a", encoding="utf-8") as f:
            for line in evo_lines:
                f.write(line + "\n")

    _logging174.getLogger("CardBridge").info(
        f"[GCC-0174][KNN] 每日进化完成: {len(card_agg)}卡 "
        f"promote={promote_n} demote={demote_n} archive={archive_n}")

    return {"total": len(card_agg), "promote": promote_n, "demote": demote_n, "archive": archive_n}


def card_acc_get_phase(card_id: str, symbol: str) -> int:
    """S5c: 获取指定卡片×品种的Phase。0=样本不足, 1=降级, 2=信任。5分钟缓存"""
    global _CARD_PHASE_CACHE, _CARD_PHASE_CACHE_TS
    now = time.time()
    if now - _CARD_PHASE_CACHE_TS > 300 or not _CARD_PHASE_CACHE:
        if not _CARD_ACC_FILE.exists():
            _CARD_PHASE_CACHE = {}
            _CARD_PHASE_CACHE_TS = now
            return 0
        try:
            data = json.loads(_CARD_ACC_FILE.read_text(encoding="utf-8"))
            _CARD_PHASE_CACHE = data.get("entries", {})
            _CARD_PHASE_CACHE_TS = now
        except Exception:
            _CARD_PHASE_CACHE = {}
            _CARD_PHASE_CACHE_TS = now
            return 0
    key = f"{card_id}_{symbol}"
    entry = _CARD_PHASE_CACHE.get(key, {})
    return entry.get("suggested_phase", 0)
