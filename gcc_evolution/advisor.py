"""
GCC v4.87 — External Advisor
外部建议器基类，引擎不知道具体实现，业务层继承注册。

设计原则：
  引擎只调用统一接口，不关心建议来自图像分析、数值模型还是规则引擎。
  每次建议和人类校正都完整记录，供后续准确率分析。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
import json
import logging

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Direction(str, Enum):
    UP      = "UP"
    DOWN    = "DOWN"
    NEUTRAL = "NEUTRAL"


class AdvisorSource(str, Enum):
    EXTERNAL_ONLY    = "external_only"     # 人类直接接受建议
    HUMAN_CORRECTED  = "human_corrected"   # 人类修正了建议
    HUMAN_ONLY       = "human_only"        # 没有外部建议，纯人类输入


@dataclass
class AdvisorSuggestion:
    """外部建议器输出的建议"""
    direction:   Direction
    confidence:  float          # 0.0 ~ 1.0
    reasoning:   str            # 建议理由（一句话）
    conditions:  list[str] = field(default_factory=list)  # 附加条件
    raw_output:  Any = None     # 原始输出（供记录）
    generated_at: str = field(default_factory=_now)


@dataclass
class AnchorRecord:
    """每日锚定记录，包含建议和人类校正"""
    date:           str
    direction:      Direction
    confidence:     float
    source:         AdvisorSource
    conditions:     list[str] = field(default_factory=list)
    reasoning:      str = ""
    external_suggestion: dict = field(default_factory=dict)  # 原始建议备份
    human_correction:    dict = field(default_factory=dict)  # 人类修正内容
    applied_at:     str = field(default_factory=_now)
    expires_at:     str = ""
    outcome:        str = ""    # 事后填入实际结果（UP/DOWN/NEUTRAL）
    accuracy:       float = -1  # 事后计算准确率，-1表示未评估


class ExternalAdvisor:
    """
    外部建议器基类。业务层继承并实现 get_suggestion()。

    示例：
        class MyAdvisor(ExternalAdvisor):
            def get_suggestion(self, context):
                # 调用图像分析、模型推理等
                return AdvisorSuggestion(
                    direction=Direction.UP,
                    confidence=0.75,
                    reasoning="价格结构显示上升趋势",
                )
    """

    def get_suggestion(self, context: dict) -> AdvisorSuggestion | None:
        """
        context 由引擎提供，包含：
          - history: 历史锚定记录
          - recent_accuracy: 近期准确率
          - knowledge_summary: 相关知识卡摘要
          - current_state: 当前系统状态

        返回 None 表示本次无法给出建议（人类直接输入）
        """
        return None

    def get_suggestion_and_record(self, context: dict) -> AdvisorSuggestion | None:
        """
        v4.98: get_suggestion() + 自动写入决策记录 (state/advisor_opinions.json)
        """
        suggestion = self.get_suggestion(context)
        if suggestion:
            self._save_opinion(suggestion, context)
        return suggestion

    def _save_opinion(self, suggestion: AdvisorSuggestion, context: dict):
        """Step 12: 将opinion结果写入决策记录"""
        try:
            opinions_file = Path("state/advisor_opinions.json")
            opinions_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                history = json.loads(opinions_file.read_text("utf-8")) if opinions_file.exists() else []
            except Exception as e:
                logger.warning("[ADVISOR] load opinions history failed: %s", e)
                history = []
            record = {
                "direction": suggestion.direction.value,
                "confidence": suggestion.confidence,
                "reasoning": suggestion.reasoning,
                "conditions": suggestion.conditions,
                "generated_at": suggestion.generated_at,
                "context_keys": list(context.keys()) if context else [],
            }
            history.append(record)
            # 保留最近100条
            if len(history) > 100:
                history = history[-100:]
            opinions_file.write_text(json.dumps(history, indent=2, ensure_ascii=False), "utf-8")
        except Exception as e:
            logger.warning("[ADVISOR] save opinion failed: %s", e)

    def validate_record(self, record: dict) -> str:
        """
        对历史执行记录做回溯评估（用于 RetrospectiveAnalyzer）
        返回：'valid' / 'invalid' / 'neutral'
        """
        return "neutral"


class AnchorStore:
    """
    锚定记录存储，管理每日方向锚定的写入、读取和准确率追踪。
    """

    def __init__(self, gcc_dir: Path | str = ".gcc"):
        self.gcc_dir = Path(gcc_dir)
        self.gcc_dir.mkdir(exist_ok=True)
        self.anchor_log  = self.gcc_dir / "anchor_log.jsonl"
        self.anchor_today = self.gcc_dir / "anchor_today.json"

    def write_anchor(self, record: AnchorRecord) -> AnchorRecord:
        """写入今日锚定"""
        data = {
            "date":          record.date,
            "direction":     record.direction.value,
            "confidence":    record.confidence,
            "source":        record.source.value,
            "conditions":    record.conditions,
            "reasoning":     record.reasoning,
            "external":      record.external_suggestion,
            "correction":    record.human_correction,
            "applied_at":    record.applied_at,
            "expires_at":    record.expires_at,
            "outcome":       record.outcome,
            "accuracy":      record.accuracy,
        }
        # 追加到日志
        with open(self.anchor_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        # 写入今日文件
        self.anchor_today.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def get_today(self) -> AnchorRecord | None:
        """读取今日锚定"""
        if not self.anchor_today.exists():
            return None
        try:
            data = json.loads(self.anchor_today.read_text(encoding="utf-8"))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if data.get("date") != today:
                return None  # 今日还没设置
            return self._from_dict(data)
        except Exception as e:
            logger.warning("[ADVISOR] load today anchor failed: %s", e)
            return None

    def get_history(self, n: int = 30) -> list[AnchorRecord]:
        """读取历史锚定记录"""
        if not self.anchor_log.exists():
            return []
        lines = self.anchor_log.read_text(encoding="utf-8").strip().split("\n")
        records = []
        for line in lines[-n:]:
            try:
                records.append(self._from_dict(json.loads(line)))
            except Exception as e:
                logger.warning("[ADVISOR] parse anchor history line failed: %s", e)
        return list(reversed(records))

    def update_outcome(self, date: str, outcome: str, accuracy: float):
        """事后更新某天的实际结果和准确率"""
        if not self.anchor_log.exists():
            return
        lines = self.anchor_log.read_text(encoding="utf-8").strip().split("\n")
        updated = []
        for line in lines:
            try:
                data = json.loads(line)
                if data.get("date") == date:
                    data["outcome"]  = outcome
                    data["accuracy"] = accuracy
                updated.append(json.dumps(data, ensure_ascii=False))
            except Exception as e:
                logger.warning("[ADVISOR] update anchor record failed: %s", e)
                updated.append(line)
        self.anchor_log.write_text("\n".join(updated) + "\n", encoding="utf-8")

    def accuracy_stats(self, n: int = 30) -> dict:
        """计算近期准确率统计"""
        records = self.get_history(n)
        evaluated = [r for r in records if r.accuracy >= 0]
        if not evaluated:
            return {"evaluated": 0, "accuracy": -1, "by_source": {}}

        total_acc = sum(r.accuracy for r in evaluated) / len(evaluated)
        by_source: dict = {}
        for r in evaluated:
            s = r.source.value
            by_source.setdefault(s, []).append(r.accuracy)

        return {
            "evaluated": len(evaluated),
            "accuracy": round(total_acc, 3),
            "by_source": {k: round(sum(v)/len(v), 3) for k, v in by_source.items()},
        }

    def _from_dict(self, data: dict) -> AnchorRecord:
        return AnchorRecord(
            date=data.get("date", ""),
            direction=Direction(data.get("direction", "NEUTRAL")),
            confidence=data.get("confidence", 0.5),
            source=AdvisorSource(data.get("source", "human_only")),
            conditions=data.get("conditions", []),
            reasoning=data.get("reasoning", ""),
            external_suggestion=data.get("external", {}),
            human_correction=data.get("correction", {}),
            applied_at=data.get("applied_at", ""),
            expires_at=data.get("expires_at", ""),
            outcome=data.get("outcome", ""),
            accuracy=data.get("accuracy", -1),
        )
