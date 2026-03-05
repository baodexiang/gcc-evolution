"""
GCC v5.295 — L6 Layer Emitter

为每一层提供语义化的 emit 接口，自动附加 layer 标签和 loop_id。

使用:
    emitter = LayerEmitter(bus, loop_id="loop_001")
    emitter.emit_l0("L0 gate passed", {"key": "KEY-010"})
    emitter.emit_l1("记忆加载完成", {"cards_loaded": 12})
    emitter.emit_l2("检索完成", {"hits": 5})
    emitter.emit_l3("蒸馏完成", {"distilled": 3})
    emitter.emit_l4("决策生成", {"action": "IMPLEMENT"})
    emitter.emit_l5("编排执行", {"step": "S3"})
    emitter.emit_l6("Dashboard 推送", {"clients": 2})
"""
from __future__ import annotations

from typing import Optional
from .event_bus import EventBus, GCCEvent


class LayerEmitter:
    """
    层级发射器。每层有独立的 emit_lN 方法。

    Args:
        bus: EventBus 实例 (默认使用全局单例)
        loop_id: 本次 loop 的唯一 ID
    """

    LAYERS = {
        "L0": "预先设置",
        "L1": "记忆层",
        "L2": "检索层",
        "L3": "蒸馏层",
        "L4": "决策层",
        "L5": "编排层",
        "L6": "观测层",
    }

    def __init__(self, bus: Optional[EventBus] = None, loop_id: str = ""):
        self._bus = bus or EventBus.get()
        self.loop_id = loop_id

    def _emit(self, layer: str, message: str,
              data: Optional[dict] = None,
              level: str = "INFO") -> GCCEvent:
        return self._bus.emit(
            layer=layer,
            message=message,
            data=data or {},
            loop_id=self.loop_id,
            level=level,
        )

    # ── Per-layer shortcuts ──────────────────────────────

    def emit_l0(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L0 预先设置层。"""
        return self._emit("L0", message, data, level)

    def emit_l1(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L1 记忆层。"""
        return self._emit("L1", message, data, level)

    def emit_l2(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L2 检索层。"""
        return self._emit("L2", message, data, level)

    def emit_l3(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L3 蒸馏层。"""
        return self._emit("L3", message, data, level)

    def emit_l4(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L4 决策层。"""
        return self._emit("L4", message, data, level)

    def emit_l5(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L5 编排层。"""
        return self._emit("L5", message, data, level)

    def emit_l6(self, message: str, data: Optional[dict] = None,
                level: str = "INFO") -> GCCEvent:
        """L6 观测层。"""
        return self._emit("L6", message, data, level)

    # ── Status shortcuts ──────────────────────────────────

    def layer_start(self, layer: str, detail: str = "") -> GCCEvent:
        msg = f"{layer} 开始" + (f": {detail}" if detail else "")
        return self._emit(layer, msg, {"status": "started"})

    def layer_done(self, layer: str, detail: str = "",
                   result: Optional[dict] = None) -> GCCEvent:
        msg = f"{layer} 完成" + (f": {detail}" if detail else "")
        data = {"status": "done"}
        if result:
            data.update(result)
        return self._emit(layer, msg, data)

    def layer_error(self, layer: str, error: str,
                    exc: Optional[Exception] = None) -> GCCEvent:
        data = {"status": "error", "error": error}
        if exc:
            data["exc_type"] = type(exc).__name__
        return self._emit(layer, f"{layer} 错误: {error}", data, level="ERROR")

    def layer_warn(self, layer: str, message: str,
                   data: Optional[dict] = None) -> GCCEvent:
        return self._emit(layer, message, data, level="WARN")

    # ── Human anchor pause ──────────────────────────────

    def human_pause(self, reason: str = "等待人工确认") -> GCCEvent:
        """发出人工确认暂停事件。"""
        return self._emit("L0", f"[PAUSE] {reason}",
                          {"type": "human_pause", "reason": reason},
                          level="WARN")

    def human_resume(self, action: str = "y") -> GCCEvent:
        """发出人工恢复事件。"""
        return self._emit("L0", f"[RESUME] action={action}",
                          {"type": "human_resume", "action": action})
