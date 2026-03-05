"""
GCC v4.87 — Pre-execution Filter
执行前过滤钩子基类，业务层继承实现。

设计原则：
  任何执行决策发生前，引擎调用注册的过滤器。
  过滤结果（通过/拦截/修改）自动记录到数据库。
  引擎不知道过滤逻辑，只记录结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FilterResult(str, Enum):
    PASS   = "PASS"    # 放行
    BLOCK  = "BLOCK"   # 拦截
    MODIFY = "MODIFY"  # 修改后放行


@dataclass
class FilterRecord:
    """过滤结果记录"""
    record_id:        str
    timestamp:        str = field(default_factory=_now)
    original_decision: dict = field(default_factory=dict)
    anchor_direction: str = ""
    filter_result:    FilterResult = FilterResult.PASS
    modified_decision: dict = field(default_factory=dict)
    reason:           str = ""
    filter_name:      str = ""
    metadata:         dict = field(default_factory=dict)


class PreExecutionFilter:
    """
    执行前过滤器基类。业务层继承并实现 filter()。

    示例：
        class MyFilter(PreExecutionFilter):
            name = "vision_filter"

            def filter(self, decision, anchor, context):
                # 调用图像分析判断当前位置
                if not position_is_valid(decision, context):
                    return FilterResult.BLOCK, {}, "位置不合适"
                return FilterResult.PASS, decision, "通过"
    """

    name: str = "base_filter"

    def filter(self,
               decision: dict,
               anchor: dict,
               context: dict) -> tuple[FilterResult, dict, str]:
        """
        decision: 即将执行的决策
          - action: str        要执行的动作
          - subject: str       对象（品种、任务等）
          - params: dict       参数

        anchor: 当日锚定
          - direction: str     UP / DOWN / NEUTRAL
          - confidence: float
          - conditions: list

        context: 当前状态（业务层自定义）

        返回：(FilterResult, modified_decision, reason)
          PASS   → (PASS, decision, reason)
          BLOCK  → (BLOCK, {}, reason)
          MODIFY → (MODIFY, modified_decision, reason)
        """
        return FilterResult.PASS, decision, "默认放行"

    def record_result(self, record: FilterRecord) -> None:
        """
        过滤结果回调，引擎调用此方法记录结果。
        默认不做任何事，子类可以重写做额外记录。
        """
        pass


class FilterChain:
    """
    过滤器链，按顺序执行多个过滤器。
    任一过滤器返回 BLOCK 则整体拦截。
    """

    def __init__(self, filters: list[PreExecutionFilter] = None):
        self.filters = filters or []

    def add(self, f: PreExecutionFilter):
        self.filters.append(f)

    def run(self, decision: dict, anchor: dict, context: dict) -> FilterRecord:
        import uuid
        record = FilterRecord(
            record_id=str(uuid.uuid4())[:8],
            original_decision=decision,
            anchor_direction=anchor.get("direction", ""),
        )

        current = decision
        for f in self.filters:
            result, modified, reason = f.filter(current, anchor, context)
            record.filter_name = f.name
            record.reason = reason

            if result == FilterResult.BLOCK:
                record.filter_result = FilterResult.BLOCK
                record.modified_decision = {}
                f.record_result(record)
                return record

            if result == FilterResult.MODIFY:
                current = modified
                record.filter_result = FilterResult.MODIFY
                record.modified_decision = modified

            f.record_result(record)

        # 所有过滤器通过
        if record.filter_result != FilterResult.MODIFY:
            record.filter_result = FilterResult.PASS
        record.modified_decision = current
        return record
