"""
GCC v4.85 — Human Anchor (方向锚点系统)

核心设计：
  人类用自然语言提问 → GCC解析意图 → 数据验证 → 写入最高优先级锚点
  Anchor不被自动降权，所有后续进化必须与最新Anchor方向对齐

三种触发方式：
  1. 定期触发：每N个session强制校准
  2. 漂移检测：方向偏差超过阈值时主动请求
  3. 人类主动：随时可以用自然语言提问

存储：.gcc/human_anchors.json (append-only log)
      .gcc/anchor_state.json  (latest active anchor)

使用方式：
  store = HumanAnchorStore()
  anchor = store.write_anchor(
      trigger="为什么低位卖？",
      direction="LONG",
      constraints=["LOW位SELL → 强制HOLD"],
      counterfactual_gain=0.043,
  )
  latest = store.get_latest()
  conf = store.get_confidence()    # 0.0 - 1.0
  paused = store.needs_calibration()
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ════════════════════════════════════════════════════════════
# Data Structures
# ════════════════════════════════════════════════════════════

@dataclass
class HumanAnchor:
    """
    方向锚点。最高优先级，永不被自动降权。
    所有自动进化必须与最新Anchor方向对齐。
    """
    anchor_id: str = ""
    created_at: str = field(default_factory=_now)
    created_by: str = "HUMAN"
    priority: str = "MAX"                    # 永远MAX，不可修改

    # 人类输入
    trigger: str = ""                        # 原始自然语言输入
    direction: str = "NEUTRAL"              # LONG / SHORT / NEUTRAL
    main_concern: str = ""                   # 人类描述的核心问题

    # 系统自动解析
    constraints: list[str] = field(default_factory=list)  # 生成的约束规则
    negative_patterns: list[dict] = field(default_factory=list)  # 识别的错误模式

    # 反事实验证
    counterfactual_gain: float = 0.0        # 预期改善（如+0.043=+4.3%）
    counterfactual_drawdown: float = 0.0    # 预期回撤改善

    # 有效期
    expires_after: str = "5_trading_days"   # 或 "10_sessions"
    expires_sessions: int = 10              # session计数过期
    sessions_used: int = 0                  # 已使用session数

    # 效果追踪
    actual_gain: float | None = None        # 实际改善（回测验证后填入）
    tracking_status: str = "PENDING"        # PENDING / TRACKING / EFFECTIVE / FAILED

    # 元数据
    key: str = ""                           # 关联的改善KEY
    project: str = ""

    def is_valid(self) -> bool:
        """检查Anchor是否在有效期内。"""
        if self.sessions_used >= self.expires_sessions:
            return False
        try:
            created = datetime.fromisoformat(self.created_at)
            now = datetime.now(timezone.utc)
            days = (now - created).days
            if "trading_days" in self.expires_after:
                limit = int(self.expires_after.split("_")[0])
                return days < limit
            elif "sessions" in self.expires_after:
                limit = int(self.expires_after.split("_")[0])
                return self.sessions_used < limit
        except Exception as e:
            logger.warning("[ANCHOR] check expiry failed: %s", e)
        return True

    def freshness_score(self) -> float:
        """新鲜度评分 0.0-1.0，随时间衰减。"""
        try:
            created = datetime.fromisoformat(self.created_at)
            now = datetime.now(timezone.utc)
            days = (now - created).days
            return max(0.0, 1.0 - days * 0.05)
        except Exception as e:
            logger.warning("[ANCHOR] freshness calc failed: %s", e)
            return 0.5

    def direction_clarity(self) -> float:
        """方向明确度：有具体约束=1.0，仅方向=0.7，NEUTRAL=0.3。"""
        if self.direction == "NEUTRAL":
            return 0.3
        if self.constraints:
            return 1.0
        return 0.7

    def confidence(self) -> float:
        """综合置信度 = 新鲜度 × 方向明确度。"""
        return self.freshness_score() * self.direction_clarity()

    def to_dict(self) -> dict:
        return {
            "anchor_id": self.anchor_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "priority": self.priority,
            "trigger": self.trigger,
            "direction": self.direction,
            "main_concern": self.main_concern,
            "constraints": self.constraints,
            "negative_patterns": self.negative_patterns,
            "counterfactual_gain": self.counterfactual_gain,
            "counterfactual_drawdown": self.counterfactual_drawdown,
            "expires_after": self.expires_after,
            "expires_sessions": self.expires_sessions,
            "sessions_used": self.sessions_used,
            "actual_gain": self.actual_gain,
            "tracking_status": self.tracking_status,
            "key": self.key,
            "project": self.project,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HumanAnchor":
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})

    def summary(self) -> str:
        conf = self.confidence()
        status = "✅ 有效" if self.is_valid() else "⚠️ 已过期"
        lines = [
            f"[{self.anchor_id}] {status}  置信度={conf:.0%}",
            f"  触发：{self.trigger}",
            f"  方向：{self.direction}  关注：{self.main_concern}",
        ]
        if self.constraints:
            for c in self.constraints[:3]:
                lines.append(f"  约束：{c}")
        if self.counterfactual_gain:
            lines.append(f"  预期改善：+{self.counterfactual_gain:.1%}")
        return "\n".join(lines)


@dataclass
class AnchorPauseSignal:
    """
    方向不明时的主动暂停信号。
    GCC检测到需要校准时输出此信号，而非强行执行。
    """
    reason: str = ""
    severity: str = "WARNING"               # WARNING / CRITICAL
    last_anchor_summary: str = ""
    days_since_anchor: int = 0
    drift_score: float = 0.0               # 0.0-1.0，越高越需要校准
    calibration_questions: list[str] = field(default_factory=list)
    estimated_time: str = "2分钟"

    def format(self) -> str:
        icon = "⚠️" if self.severity == "WARNING" else "🛑"
        lines = [
            f"{icon} GCC 主动暂停 — 需要方向校准",
            f"",
            f"原因：{self.reason}",
        ]
        if self.last_anchor_summary:
            lines.append(f"最近Anchor：{self.last_anchor_summary}")
        if self.drift_score > 0:
            lines.append(f"方向漂移评分：{self.drift_score:.0%}")
        lines.append("")
        lines.append(f"请回答以下问题（预计{self.estimated_time}）：")
        for i, q in enumerate(self.calibration_questions, 1):
            lines.append(f"  {i}. {q}")
        lines.append("")
        lines.append("使用命令：gcc-evo anchor calibrate")
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# NLQ Parser — 自然语言 → 系统级查询
# ════════════════════════════════════════════════════════════

class NLQParser:
    """
    自然语言意图解析器。
    提示词注入系统上下文，剩下靠模型水平判断。
    """

    def __init__(self, llm_client=None, gcc_dir: str | None = None):
        self.llm     = llm_client
        self.gcc_dir = gcc_dir

    # 系统命令表，注入提示词用
    COMMANDS = [
        ("task status [改善号]",    "查看任务进展，例：'001怎么样了'"),
        ("task start [改善号]",     "开始或继续任务，例：'继续001'"),
        ("task done [改善号]",      "完成当前步骤，例：'001第一步做完了'"),
        ("task pause [改善号]",     "暂停任务，例：'001先停一下'"),
        ("task create [标题]",      "创建新任务，例：'新建一个分析任务'"),
        ("anchor calibrate",        "今日方向校正，例：'今天偏空' '做个方向判断'"),
        ("anchor status",           "查看今日锚定，例：'今天方向是什么'"),
        ("analyze run",             "运行回溯分析，例：'分析一下最近的数据'"),
        ("suggest list",            "查看待审核建议，例：'有什么建议'"),
        ("suggest review",          "逐条审核建议，例：'看下建议'"),
        ("db trades --summary",     "查看成交汇总，例：'最近交易怎么样'"),
        ("db improvements",         "查看改善清单，例：'改善项有哪些'"),
        ("knowledge import [文件]", "导入外部知识，例：'导入这篇论文'"),
        ("schedule check",          "检查到期任务，例：'有什么要做的'"),
        ("ho pickup",               "读取上次交接，例：'上次做到哪了'"),
        ("ho create",               "创建交接文件，例：'结束今天的工作'"),
    ]

    SYSTEM_PROMPT = """你是 GCC（Git Context Controller）进化引擎的指令解析器。
GCC 是一个 Agentic AI 系统，帮助人类管理跨会话的任务、知识和策略进化。

━━━ 当前系统状态 ━━━
{state}

━━━ 可用命令 ━━━
任务管理（改善号是唯一标识，如 001 / 1 / KEY-001 都指同一个）：
  task status [改善号]     查看任务进展和步骤
  task start  [改善号]     开始或继续一个任务
  task done   [改善号]     完成当前步骤，推进到下一步
  task pause  [改善号]     暂停任务，下次继续
  task create [标题]       创建新任务

方向与锚定：
  anchor calibrate         今日方向校正（偏多/偏空/中性）
  anchor status            查看今日方向锚定

分析与建议：
  analyze run              运行回溯分析
  suggest list             查看待审核的参数建议
  suggest review           逐条审核建议

数据查询：
  db trades --summary      成交汇总
  db improvements          查看改善清单

知识管理：
  knowledge import [文件]  导入外部论文或文档
  knowledge list           查看待审核知识草稿

会话交接：
  ho pickup                读取上次交接，恢复上下文
  ho create                结束本次工作，创建交接文件

定时任务：
  schedule check           检查有哪些到期任务需要执行

━━━ 返回格式（严格 JSON，不要任何解释文字）━━━
命令明确时：
{{"command": "task done 001", "confidence": 0.95, "reply": "好，标记001当前步骤完成"}}

不确定时：
{{"command": null, "candidates": ["task status 001", "task done 001"], "confidence": 0.4, "reply": "你是想看001的进展，还是标记完成？"}}

完全不理解时：
{{"command": null, "candidates": [], "confidence": 0.1, "reply": "没太明白，能说具体一点吗？"}}

━━━ 解析原则 ━━━
- 改善号识别要宽松：'1号' '001' 'key001' 'KEY-001' 都是同一个
- 结合当前状态判断：如果只有一个活跃任务，"做完了"就是指它
- 方向词识别：'偏空' '看跌' '今天空' → anchor calibrate DOWN
- 动作词识别：'继续' '开始' → task start；'做完' '完成' → task done；'停一下' '暂停' → task pause
- reply 用自然中文，简短，像在对话不像在报告
"""

    def _llm_parse(self, text: str, state: dict) -> dict:
        """用 LLM 解析意图"""
        import json

        commands_str = "\n".join(
            f"  {cmd:<35} # {desc}"
            for cmd, desc in self.COMMANDS
        )

        state_str = self._format_state(state)

        system = self.SYSTEM_PROMPT.format(
            commands=commands_str,
            state=state_str,
        )

        try:
            raw = self.llm.generate(system=system, user=text, max_tokens=400)
            # 清理可能的 markdown
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            result["raw_text"] = text
            result["method"] = "llm"
            return result
        except Exception as e:
            logger.warning("[ANCHOR] LLM parse failed: %s", e)
            # LLM 调用失败，返回友好提示
            return {
                "raw_text": text,
                "command": None,
                "candidates": [],
                "confidence": 0.0,
                "reply": "模型暂时无响应，请直接使用命令行操作",
                "method": "error",
            }

    def _format_state(self, state: dict) -> str:
        """格式化系统状态供提示词注入"""
        lines = []
        if state.get("anchor"):
            a = state["anchor"]
            lines.append(f"今日锚定: {a.get('direction','未设置')} (确信率{a.get('confidence',0):.0%})")
        if state.get("active_tasks"):
            for t in state["active_tasks"][:3]:
                lines.append(f"活跃任务: [{t.get('key','')}] {t.get('title','')} 进度{t.get('progress','')}")
        if state.get("pending_suggests"):
            lines.append(f"待审核建议: {state['pending_suggests']} 条")
        if state.get("last_handoff"):
            lines.append(f"上次交接: {state['last_handoff'][:80]}")
        return "\n".join(lines) if lines else "无（新会话）"

    def _regex_parse(self, text: str) -> dict:
        """正则兜底，覆盖最常用场景"""
        import re
        text_lower = text.lower()

        patterns = [
            # 任务操作
            (r"(继续|开始|start).*(\d{3}|key-\d+)", "task start"),
            (r"(\d{3}|key-\d+).*(做完|完成|done)",  "task done"),
            (r"(暂停|pause|停一下).*(\d{3}|key-\d+)|(\d{3}|key-\d+).*(暂停|停)", "task pause"),
            (r"(\d{3}|key-\d+).*(怎么|进展|状态|status)", "task status"),
            # 方向校正
            (r"今天.*(偏|方向|看|bearish|bullish)|做个.*方向|anchor", "anchor calibrate"),
            # 分析
            (r"分析|analyze|回溯|retrospective", "analyze run"),
            # 建议
            (r"建议|suggest|待审核", "suggest list"),
            # 交接
            (r"上次|继续|pickup|handoff|交接", "ho pickup"),
            (r"结束|收工|create.*handoff|今天做完", "ho create"),
            # 查询
            (r"成交|交易|trade|盈亏", "db trades --summary"),
            (r"改善|improvement|清单", "db improvements"),
        ]

        for pattern, command in patterns:
            if re.search(pattern, text_lower):
                # 尝试提取改善号
                key_match = re.search(r"(\d{3}|key-\d+)", text_lower)
                args = {}
                if key_match:
                    args["key"] = key_match.group(1)
                return {
                    "raw_text": text,
                    "command": command,
                    "args": args,
                    "confidence": 0.7,
                    "reply": f"好的",
                    "method": "regex",
                }

        return {
            "raw_text": text,
            "command": None,
            "candidates": [],
            "confidence": 0.2,
            "reply": "没理解，能说得更具体一点吗？",
            "method": "regex",
        }

    def parse(self, text: str, state: dict | None = None) -> dict:
        """
        主入口：解析自然语言意图。
        有 LLM 时用 LLM，否则用正则兜底。
        """
        ctx = state or {}
        if self.llm:
            return self._llm_parse(text, ctx)
        return self._regex_parse(text)

    def generate_calibration_questions(self, issue_type: str) -> list[str]:
        """根据问题类型生成校准问题（保留兼容）"""
        base = [
            "当前市场大方向是？（牛市 / 熊市 / 震荡）",
            "未来1-2周的操作偏向？（做多 / 做空 / 观望）",
        ]
        specific = {
            "over_trading":      ["每标的每日最多允许几个有效信号？"],
            "direction_reversed":["这种系统性方向偏差持续多久了？"],
        }
        return base + specific.get(issue_type, ["请描述您观察到的具体问题。"])


class HumanAnchorStore:
    """
    Human Anchor 存储和管理。

    文件：
      .gcc/human_anchors.json  — 历史log（所有Anchor记录）
      .gcc/anchor_state.json   — 当前活跃Anchor快照
    """

    ANCHORS_FILE = ".gcc/human_anchors.json"
    STATE_FILE = ".gcc/anchor_state.json"
    DRIFT_FILE = ".gcc/anchor_drift.json"

    # 校准触发阈值
    MIN_CONFIDENCE = 0.70       # 低于此值主动暂停
    DRIFT_CRITICAL = 0.60       # 滚动漂移评分超过此值强制校准
    DRIFT_WARNING = 0.35        # 超过此值提示

    def __init__(self, gcc_dir: str | None = None):
        self._base = Path(gcc_dir or ".gcc")
        self._base.mkdir(parents=True, exist_ok=True)
        self._anchors_path = Path(self.ANCHORS_FILE)
        self._state_path = Path(self.STATE_FILE)
        self._drift_path = Path(self.DRIFT_FILE)
        self._nlq = NLQParser()

    # ── Write ──

    def write_anchor(
        self,
        trigger: str,
        direction: str = "NEUTRAL",
        constraints: list[str] | None = None,
        main_concern: str = "",
        counterfactual_gain: float = 0.0,
        counterfactual_drawdown: float = 0.0,
        expires_after: str = "5_trading_days",
        key: str = "",
        project: str = "",
        negative_patterns: list[dict] | None = None,
    ) -> HumanAnchor:
        """写入新的Human Anchor。旧Anchor保留在历史log中。"""
        anchor = HumanAnchor(
            anchor_id=f"anchor_{_ts()}",
            trigger=trigger,
            direction=direction.upper(),
            constraints=constraints or [],
            main_concern=main_concern or trigger,
            counterfactual_gain=counterfactual_gain,
            counterfactual_drawdown=counterfactual_drawdown,
            expires_after=expires_after,
            expires_sessions=self._parse_session_limit(expires_after),
            key=key,
            project=project,
            negative_patterns=negative_patterns or [],
        )

        # Append to history log
        self._append_log(anchor)

        # Update active state
        self._state_path.write_text(
            json.dumps(anchor.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        return anchor

    def write_from_nlq(self, text: str, direction: str = "NEUTRAL",
                       constraints: list[str] | None = None,
                       counterfactual_gain: float = 0.0,
                       key: str = "", project: str = "") -> HumanAnchor:
        """从自然语言直接创建Anchor。"""
        parsed = self._nlq.parse(text)
        return self.write_anchor(
            trigger=text,
            direction=direction,
            constraints=constraints or [],
            main_concern=parsed.get("issue_type", ""),
            counterfactual_gain=counterfactual_gain,
            key=key,
            project=project,
        )

    # ── Read ──

    def get_latest(self) -> HumanAnchor | None:
        """获取最新的活跃Anchor。"""
        if not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text("utf-8"))
            return HumanAnchor.from_dict(data)
        except Exception as e:
            logger.warning("[ANCHOR] load state failed: %s", e)
            return None

    def get_all(self) -> list[HumanAnchor]:
        """获取所有历史Anchor。"""
        if not self._anchors_path.exists():
            return []
        try:
            data = json.loads(self._anchors_path.read_text("utf-8"))
            return [HumanAnchor.from_dict(d) for d in data]
        except Exception as e:
            logger.warning("[ANCHOR] load all anchors failed: %s", e)
            return []

    def get_confidence(self) -> float:
        """当前Anchor的综合置信度。无Anchor=0.0。"""
        anchor = self.get_latest()
        if anchor is None:
            return 0.0
        if not anchor.is_valid():
            return 0.0
        return anchor.confidence()

    def needs_calibration(self) -> tuple[bool, str]:
        """
        判断是否需要校准。
        返回 (需要校准, 原因)。
        """
        anchor = self.get_latest()

        if anchor is None:
            return True, "没有Human Anchor，需要首次校准"

        if not anchor.is_valid():
            return True, f"Human Anchor已过期（{anchor.expires_after}）"

        conf = anchor.confidence()
        if conf < self.MIN_CONFIDENCE:
            return True, f"Anchor置信度 {conf:.0%} < 阈值 {self.MIN_CONFIDENCE:.0%}"

        drift = self._get_drift_score()
        if drift >= self.DRIFT_CRITICAL:
            return True, f"方向漂移评分 {drift:.0%}（严重），强制校准"

        return False, ""

    def build_pause_signal(self) -> AnchorPauseSignal:
        """构建主动暂停信号，包含校准问题。"""
        needs, reason = self.needs_calibration()
        anchor = self.get_latest()
        drift = self._get_drift_score()

        issue_type = "direction_drift" if drift > self.DRIFT_WARNING else "general"
        questions = self._nlq.generate_calibration_questions(issue_type)

        severity = "CRITICAL" if drift >= self.DRIFT_CRITICAL else "WARNING"
        last_summary = anchor.summary() if anchor else "无"

        # 计算距上次校准的天数
        days = 0
        if anchor:
            try:
                created = datetime.fromisoformat(anchor.created_at)
                days = (datetime.now(timezone.utc) - created).days
            except Exception as e:
                logger.warning("[ANCHOR] parse anchor date failed: %s", e)

        return AnchorPauseSignal(
            reason=reason,
            severity=severity,
            last_anchor_summary=last_summary,
            days_since_anchor=days,
            drift_score=drift,
            calibration_questions=questions,
        )

    # ── Drift Detection ──

    def record_session_direction(self, session_direction: str,
                                  session_id: str = "") -> float:
        """
        记录本次session的实际方向，更新漂移评分。
        返回当前漂移评分。
        """
        anchor = self.get_latest()
        if anchor is None:
            return 0.0

        # 更新session使用计数
        anchor.sessions_used += 1
        self._state_path.write_text(
            json.dumps(anchor.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # 计算对齐
        aligned = self._direction_aligned(anchor.direction, session_direction)
        drift_delta = 0.0 if aligned else 1.0

        # 更新滚动漂移记录
        drift_log = self._load_drift_log()
        drift_log.append({
            "timestamp": _now(),
            "session_id": session_id,
            "anchor_direction": anchor.direction,
            "session_direction": session_direction,
            "aligned": aligned,
            "drift_delta": drift_delta,
        })
        # 只保留最近10条
        drift_log = drift_log[-10:]
        self._drift_path.write_text(
            json.dumps(drift_log, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        drift_score = self._compute_drift(drift_log)

        # 持久化到 alignment.json
        alignment_path = self._state_path.parent / "alignment.json"
        alignment_data = {
            "drift_score": round(drift_score, 2),
            "updated_at": _now(),
            "constraint_violations": {}
        }
        alignment_path.write_text(
            json.dumps(alignment_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        return drift_score

    def update_tracking(self, anchor_id: str, actual_gain: float,
                         status: str = "EFFECTIVE") -> bool:
        """更新Anchor实际效果（回测验证后调用）。"""
        anchor = self.get_latest()
        if anchor and anchor.anchor_id == anchor_id:
            anchor.actual_gain = actual_gain
            anchor.tracking_status = status
            self._state_path.write_text(
                json.dumps(anchor.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            self._append_log(anchor)  # 更新log中的记录
            return True
        return False

    def record_constraint_violation(self, constraint_type: str) -> None:
        """记录约束违反事件，按类型统计。"""
        alignment_path = self._state_path.parent / "alignment.json"
        # 读取现有的 alignment.json，如果不存在则初始化
        alignment_data = {}
        if alignment_path.exists():
            try:
                alignment_data = json.loads(alignment_path.read_text("utf-8"))
            except Exception:
                alignment_data = {
                    "drift_score": 0.0,
                    "updated_at": _now(),
                    "constraint_violations": {}
                }
        # 确保 constraint_violations 字段存在
        if "constraint_violations" not in alignment_data:
            alignment_data["constraint_violations"] = {}
        # 增加违反计数
        if constraint_type not in alignment_data["constraint_violations"]:
            alignment_data["constraint_violations"][constraint_type] = 0
        alignment_data["constraint_violations"][constraint_type] += 1
        alignment_data["updated_at"] = _now()
        # 写回文件
        alignment_path.write_text(
            json.dumps(alignment_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # ── Helpers ──

    def _append_log(self, anchor: HumanAnchor):
        """追加到历史log。"""
        existing = []
        if self._anchors_path.exists():
            try:
                existing = json.loads(self._anchors_path.read_text("utf-8"))
            except Exception as e:
                logger.warning("[ANCHOR] read anchors file failed: %s", e)
                existing = []
        # 更新已存在的记录，否则追加
        updated = False
        for i, e in enumerate(existing):
            if e.get("anchor_id") == anchor.anchor_id:
                existing[i] = anchor.to_dict()
                updated = True
                break
        if not updated:
            existing.append(anchor.to_dict())
        self._anchors_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _load_drift_log(self) -> list[dict]:
        if not self._drift_path.exists():
            return []
        try:
            return json.loads(self._drift_path.read_text("utf-8"))
        except Exception as e:
            logger.warning("[ANCHOR] read drift file failed: %s", e)
            return []

    def _get_drift_score(self) -> float:
        log = self._load_drift_log()
        return self._compute_drift(log)

    @staticmethod
    def _compute_drift(log: list[dict], window: int = 5) -> float:
        """滚动窗口漂移评分。"""
        if not log:
            return 0.0
        recent = log[-window:]
        if not recent:
            return 0.0
        total_drift = sum(r.get("drift_delta", 0.0) for r in recent)
        return total_drift / len(recent)

    @staticmethod
    def _direction_aligned(anchor_dir: str, session_dir: str) -> bool:
        """判断session方向是否与Anchor方向对齐。"""
        anchor_dir = anchor_dir.upper()
        session_dir = session_dir.upper()
        if anchor_dir == "NEUTRAL":
            return True
        if anchor_dir == session_dir:
            return True
        # 容忍：LONG vs NEUTRAL 算部分对齐
        if session_dir == "NEUTRAL":
            return True
        return False

    @staticmethod
    def _parse_session_limit(expires_after: str) -> int:
        """从expires_after字符串提取session上限。"""
        if "sessions" in expires_after:
            try:
                return int(expires_after.split("_")[0])
            except ValueError:
                pass
        return 10  # 默认10个session


# ════════════════════════════════════════════════════════════
# CLI Formatting
# ════════════════════════════════════════════════════════════

def format_anchor_status(store: HumanAnchorStore) -> str:
    """格式化Anchor状态用于CLI显示。"""
    anchor = store.get_latest()
    conf = store.get_confidence()
    needs, reason = store.needs_calibration()
    drift = store._get_drift_score()

    lines = [
        "  Human Anchor 状态",
        f"  {'═' * 50}",
    ]

    if anchor is None:
        lines.append("  ❌ 无Human Anchor")
        lines.append("  运行: gcc-evo anchor calibrate")
    else:
        valid_icon = "✅" if anchor.is_valid() else "⚠️"
        lines.append(f"  {valid_icon} Anchor ID: {anchor.anchor_id}")
        lines.append(f"  触发问题: {anchor.trigger}")
        lines.append(f"  方向: {anchor.direction}  |  置信度: {conf:.0%}")
        if anchor.constraints:
            lines.append(f"  约束数量: {len(anchor.constraints)}")
            for c in anchor.constraints[:3]:
                lines.append(f"    → {c}")
        if anchor.counterfactual_gain:
            lines.append(f"  预期改善: +{anchor.counterfactual_gain:.1%}")
        if anchor.actual_gain is not None:
            lines.append(f"  实际改善: +{anchor.actual_gain:.1%}  [{anchor.tracking_status}]")
        lines.append(f"  已用Sessions: {anchor.sessions_used}/{anchor.expires_sessions}")
        lines.append(f"  漂移评分: {drift:.0%}")

    if needs:
        lines.append("")
        lines.append(f"  ⚠️  需要校准: {reason}")

    return "\n".join(lines)
