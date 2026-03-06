"""
GCC v5.300 — L0 Setup Wizard

交互式向导，引导用户完成 SessionConfig 的3个必填 + 3个选填字段。

使用:
    from gcc_evolution.setup_wizard import run_setup_wizard
    cfg = run_setup_wizard(key="KEY-010")
"""
from __future__ import annotations

from typing import Optional

from .session_config import SessionConfig


# ── 终端颜色 (fallback-safe) ──────────────────────────────

def _color(text: str, code: str) -> str:
    """ANSI 颜色包装，Windows 安全。"""
    try:
        import os
        if os.name == "nt":
            # Windows: 只有 ANSICON / WT / VS Code terminal 支持 ANSI
            if not (os.environ.get("WT_SESSION") or
                    os.environ.get("TERM_PROGRAM") or
                    os.environ.get("ANSICON")):
                return text
        return f"\033[{code}m{text}\033[0m"
    except Exception:
        return text


def green(t): return _color(t, "32")
def yellow(t): return _color(t, "33")
def cyan(t): return _color(t, "36")
def bold(t): return _color(t, "1")
def red(t): return _color(t, "31")
def dim(t): return _color(t, "2")


# ── Input helpers ─────────────────────────────────────────

def _prompt(label: str, default: str = "", required: bool = True,
            hint: str = "") -> str:
    """安全 input()，支持 default 和 required 验证。"""
    hint_str = f" [{dim(default)}]" if default else ""
    if hint:
        hint_str += f"  {dim('(' + hint + ')')}"
    while True:
        raw = input(f"  {cyan(label)}{hint_str}: ").strip()
        if not raw and default:
            return default
        if not raw and required:
            print(f"  {red('必填，请输入')}")
            continue
        return raw


def _prompt_list(label: str, default: list[str] | None = None,
                  min_count: int = 1, max_count: int = 5) -> list[str]:
    """逐条收集列表 (enter 空行结束，至少 min_count 条)。"""
    default = default or []
    print(f"\n  {cyan(label)}  {dim(f'(至少{min_count}条，最多{max_count}条，空行结束)')}")
    items = list(default)
    # 显示已有项
    for i, d in enumerate(default):
        print(f"  {dim(str(i+1) + '. ' + d)}  {dim('[已填]')}")

    idx = len(items) + 1
    while idx <= max_count:
        raw = input(f"  {dim(str(idx) + '>')} ").strip()
        if not raw:
            if len(items) >= min_count:
                break
            print(f"  {red(f'至少需要 {min_count} 条')}")
            continue
        items.append(raw)
        idx += 1

    return items[:max_count]


def _confirm(label: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    raw = input(f"  {cyan(label)} [{dim(default_str)}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "是", "1")


# ── Wizard ────────────────────────────────────────────────

def run_setup_wizard(
    key: str = "",
    existing: Optional[SessionConfig] = None,
    edit_field: Optional[int] = None,
) -> Optional[SessionConfig]:
    """
    交互式向导，返回填写完成的 SessionConfig。
    Ctrl+C 取消返回 None。

    Args:
        key: 预填入的 KEY 编号
        existing: 已有配置（用于 --edit 模式）
        edit_field: 仅编辑第 N 个字段 (1-6)
    """
    cfg = existing or SessionConfig()
    if key:
        cfg.key = key

    print()
    print(bold("  ╔══════════════════════════════════════╗"))
    print(bold("  ║   gcc-evo setup — L0 预先设置向导   ║"))
    print(bold("  ╚══════════════════════════════════════╝"))
    print()

    try:
        if edit_field is None:
            # 全部字段模式
            _fill_all(cfg)
        else:
            _fill_one(cfg, edit_field)

        # 预览 & 确认
        print()
        print(cfg.summary())
        print()
        ok, err = cfg.is_valid()
        if not ok:
            print(f"  {red('配置不完整:')} {err}")
            return None

        confirmed = _confirm("确认保存？", default=True)
        if not confirmed:
            print(f"  {yellow('已取消，配置未保存')}")
            return None

        path = cfg.save()
        print(f"  {green('✓ 配置已保存:')} {path}")
        return cfg

    except KeyboardInterrupt:
        print(f"\n  {yellow('已取消')}")
        return None


def _fill_all(cfg: SessionConfig) -> None:
    """填写全部 6 个字段 (3必填 + 3选填)。"""
    print(f"  {bold('── 必填字段 (3/3) ──')}")
    print()

    # 1. KEY
    cfg.key = _prompt(
        "KEY编号",
        default=cfg.key,
        hint="如 KEY-010"
    )

    # 2. 目标
    cfg.goal = _prompt(
        "本次进化目标",
        default=cfg.goal,
        hint="至少10字，描述本次要改善什么"
    )
    while len(cfg.goal) < 10:
        print(f"  {red(f'至少10字 (当前{len(cfg.goal)}字)')}")
        cfg.goal = _prompt("本次进化目标", hint="至少10字")

    # 3. 成功标准
    cfg.success_criteria = _prompt_list(
        "成功标准",
        default=cfg.success_criteria,
        min_count=1,
        max_count=5
    )

    print()
    print(f"  {bold('── 选填字段 (可回车跳过) ──')}")
    print()

    # 4. Human anchor required
    cfg.human_anchor_required = _confirm(
        "每轮结束后暂停等待人工确认？",
        default=cfg.human_anchor_required
    )

    # 5. Max iterations
    raw = _prompt(
        "最大循环次数",
        default=str(cfg.max_iterations) if cfg.max_iterations else "0",
        required=False,
        hint="0=不限"
    )
    try:
        cfg.max_iterations = int(raw)
    except ValueError:
        cfg.max_iterations = 0

    # 6. Notes
    cfg.notes = _prompt(
        "备注",
        default=cfg.notes,
        required=False,
        hint="可选"
    )


def _fill_one(cfg: SessionConfig, field_num: int) -> None:
    """编辑单个字段 (--edit 模式)。"""
    FIELD_MAP = {
        1: ("key",                   "KEY编号"),
        2: ("goal",                  "本次进化目标"),
        3: ("success_criteria",      "成功标准"),
        4: ("human_anchor_required", "人工确认"),
        5: ("max_iterations",        "最大循环次数"),
        6: ("notes",                 "备注"),
    }
    if field_num not in FIELD_MAP:
        print(f"  {red('无效字段编号')} (1-6)")
        return

    fname, label = FIELD_MAP[field_num]
    print(f"  编辑字段: {bold(label)}")
    print()

    if fname == "success_criteria":
        cfg.success_criteria = _prompt_list(label, default=cfg.success_criteria)
    elif fname == "human_anchor_required":
        cfg.human_anchor_required = _confirm(label, default=cfg.human_anchor_required)
    elif fname == "max_iterations":
        raw = _prompt(label, default=str(cfg.max_iterations), required=False, hint="0=不限")
        try:
            cfg.max_iterations = int(raw)
        except ValueError:
            pass
    else:
        current = getattr(cfg, fname, "")
        val = _prompt(label, default=str(current), required=(fname in ("key", "goal")))
        setattr(cfg, fname, val)


# ── Edit Menu ─────────────────────────────────────────────

def run_edit_menu(cfg: SessionConfig) -> Optional[SessionConfig]:
    """
    显示编号菜单，让用户选择要编辑的字段。
    用于 gcc-evo setup <KEY> --edit。
    """
    FIELDS = [
        ("KEY编号",          cfg.key),
        ("本次进化目标",      cfg.goal),
        ("成功标准",          "; ".join(cfg.success_criteria)),
        ("人工确认",          "是" if cfg.human_anchor_required else "否"),
        ("最大循环次数",      str(cfg.max_iterations) if cfg.max_iterations else "不限"),
        ("备注",              cfg.notes or "(空)"),
    ]

    print()
    print(bold("  选择要编辑的字段:"))
    for i, (name, val) in enumerate(FIELDS, 1):
        print(f"  {cyan(str(i))}. {name:<16} {dim(val[:40])}")
    print(f"  {cyan('0')}. 返回（不保存）")
    print()

    try:
        raw = input(f"  {cyan('输入编号')}: ").strip()
        num = int(raw)
        if num == 0:
            return None
        if 1 <= num <= 6:
            return run_setup_wizard(existing=cfg, edit_field=num)
        print(f"  {red('无效编号')}")
        return None
    except (ValueError, KeyboardInterrupt):
        return None
