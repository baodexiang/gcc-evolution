"""
GCC v5.300 — L0 预先设置层: SessionConfig

每次 gcc-evo loop 前必须通过 L0 gate 校验。
存储路径: .GCC/state/session_config.json

使用:
    cfg = SessionConfig.load()
    if not cfg.is_valid():
        print("请先运行: gcc-evo setup <KEY>")
        return
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STATE_FILE = Path(".GCC") / "state" / "session_config.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionConfig:
    """
    L0 预先设置层配置。
    必填字段: goal, success_criteria, key
    选填字段: human_anchor_required, max_iterations, notes
    """
    # 必填
    key: str = ""                              # 关联的 KEY 编号 (如 KEY-010)
    goal: str = ""                             # 本次进化目标 (>=10字)
    success_criteria: list[str] = field(default_factory=list)  # 成功标准 (1-5条)

    # 选填
    human_anchor_required: bool = True         # 每轮结束后是否需要人工确认
    max_iterations: int = 0                    # 最大循环次数 (0=不限)
    notes: str = ""                            # 备注

    # 元数据 (自动生成)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    version: str = "1.0"

    # ── 验证 ──────────────────────────────────────────────

    def is_valid(self) -> tuple[bool, str]:
        """校验配置是否完整。返回 (ok, reason)."""
        if not self.key:
            return False, "缺少 key (如 KEY-010)"
        if len(self.goal) < 10:
            return False, f"goal 至少10字 (当前 {len(self.goal)} 字)"
        if not self.success_criteria:
            return False, "至少填写1条 success_criteria"
        if len(self.success_criteria) > 5:
            return False, "success_criteria 最多5条"
        return True, ""

    def summary(self) -> str:
        ok, err = self.is_valid()
        status = "Valid" if ok else f"Invalid: {err}"
        anchor = "human confirm required" if self.human_anchor_required else "auto"
        max_it = f"max {self.max_iterations}" if self.max_iterations else "unlimited"
        lines = [
            f"  L0 Session Config  [{status}]",
            f"  ─────────────────────────────────────",
            f"  KEY:    {self.key}",
            f"  Goal:   {self.goal}",
            f"  Success Criteria:",
        ]
        for i, c in enumerate(self.success_criteria, 1):
            lines.append(f"    {i}. {c}")
        lines += [
            f"  Human Anchor: {anchor}",
            f"  Iterations:   {max_it}",
        ]
        if self.notes:
            lines.append(f"  Notes: {self.notes}")
        lines.append(f"  Updated: {self.updated_at[:19]}")
        return "\n".join(lines)

    # ── 持久化 ────────────────────────────────────────────

    def save(self, path: Optional[Path] = None) -> Path:
        """保存到 JSON 文件。"""
        p = path or _STATE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        p.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return p

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "SessionConfig":
        """从 JSON 文件加载，不存在则返回空配置。"""
        p = path or _STATE_FILE
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            # 只保留已知字段
            known = {f for f in cls.__dataclass_fields__}
            clean = {k: v for k, v in data.items() if k in known}
            return cls(**clean)
        except Exception as e:
            logger.warning("[L0] load session_config failed: %s", e)
            return cls()

    @classmethod
    def exists(cls, path: Optional[Path] = None) -> bool:
        p = path or _STATE_FILE
        return p.exists()

    def to_dict(self) -> dict:
        return asdict(self)

    def reset(self, path: Optional[Path] = None) -> None:
        """删除配置文件 (reset)。"""
        p = path or _STATE_FILE
        if p.exists():
            p.unlink()
