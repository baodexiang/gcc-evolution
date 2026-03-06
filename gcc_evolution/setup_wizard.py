"""
GCC v5.300 — L0 Setup Wizard

Interactive wizard for completing SessionConfig (3 required + 3 optional fields).

Usage:
    from gcc_evolution.setup_wizard import run_setup_wizard
    cfg = run_setup_wizard(key="KEY-010")
"""
from __future__ import annotations

from typing import Optional

from .session_config import SessionConfig


# ── Terminal colors (fallback-safe) ──────────────────────

def _color(text: str, code: str) -> str:
    """ANSI color wrapper, Windows safe."""
    try:
        import os
        if os.name == "nt":
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
    """Safe input() with default and required validation."""
    hint_str = f" [{dim(default)}]" if default else ""
    if hint:
        hint_str += f"  {dim('(' + hint + ')')}"
    while True:
        raw = input(f"  {cyan(label)}{hint_str}: ").strip()
        if not raw and default:
            return default
        if not raw and required:
            print(f"  {red('Required, please enter a value')}")
            continue
        return raw


def _prompt_list(label: str, default: list[str] | None = None,
                  min_count: int = 1, max_count: int = 5) -> list[str]:
    """Collect items one by one (empty line to finish, min_count required)."""
    default = default or []
    print(f"\n  {cyan(label)}  {dim(f'(at least {min_count}, max {max_count}, empty line to finish)')}")
    items = list(default)
    for i, d in enumerate(default):
        print(f"  {dim(str(i+1) + '. ' + d)}  {dim('[existing]')}")

    idx = len(items) + 1
    while idx <= max_count:
        raw = input(f"  {dim(str(idx) + '>')} ").strip()
        if not raw:
            if len(items) >= min_count:
                break
            print(f"  {red(f'At least {min_count} item(s) required')}")
            continue
        items.append(raw)
        idx += 1

    return items[:max_count]


def _confirm(label: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    raw = input(f"  {cyan(label)} [{dim(default_str)}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1")


# ── Wizard ────────────────────────────────────────────────

def run_setup_wizard(
    key: str = "",
    existing: Optional[SessionConfig] = None,
    edit_field: Optional[int] = None,
) -> Optional[SessionConfig]:
    """
    Interactive wizard, returns completed SessionConfig.
    Ctrl+C cancels and returns None.

    Args:
        key: Pre-filled KEY number
        existing: Existing config (for --edit mode)
        edit_field: Only edit field N (1-6)
    """
    cfg = existing or SessionConfig()
    if key:
        cfg.key = key

    print()
    print(bold("  ╔══════════════════════════════════════╗"))
    print(bold("  ║   gcc-evo setup — L0 Session Setup   ║"))
    print(bold("  ╚══════════════════════════════════════╝"))
    print()

    try:
        if edit_field is None:
            _fill_all(cfg)
        else:
            _fill_one(cfg, edit_field)

        print()
        print(cfg.summary())
        print()
        ok, err = cfg.is_valid()
        if not ok:
            print(f"  {red('Incomplete config:')} {err}")
            return None

        confirmed = _confirm("Save configuration?", default=True)
        if not confirmed:
            print(f"  {yellow('Cancelled, config not saved')}")
            return None

        path = cfg.save()
        print(f"  {green('Config saved:')} {path}")
        return cfg

    except KeyboardInterrupt:
        print(f"\n  {yellow('Cancelled')}")
        return None


def _fill_all(cfg: SessionConfig) -> None:
    """Fill all 6 fields (3 required + 3 optional)."""
    print(f"  {bold('── Required Fields (3/3) ──')}")
    print()

    # 1. KEY
    cfg.key = _prompt(
        "KEY number",
        default=cfg.key,
        hint="e.g. KEY-010"
    )

    # 2. Goal
    cfg.goal = _prompt(
        "Evolution goal",
        default=cfg.goal,
        hint="at least 10 chars, describe what to improve"
    )
    while len(cfg.goal) < 10:
        print(f"  {red(f'At least 10 chars (current: {len(cfg.goal)})')}")
        cfg.goal = _prompt("Evolution goal", hint="at least 10 chars")

    # 3. Success criteria
    cfg.success_criteria = _prompt_list(
        "Success criteria",
        default=cfg.success_criteria,
        min_count=1,
        max_count=5
    )

    print()
    print(f"  {bold('── Optional Fields (press Enter to skip) ──')}")
    print()

    # 4. Human anchor
    cfg.human_anchor_required = _confirm(
        "Pause for human confirmation after each iteration?",
        default=cfg.human_anchor_required
    )

    # 5. Max iterations
    raw = _prompt(
        "Max iterations",
        default=str(cfg.max_iterations) if cfg.max_iterations else "0",
        required=False,
        hint="0=unlimited"
    )
    try:
        cfg.max_iterations = int(raw)
    except ValueError:
        cfg.max_iterations = 0

    # 6. Notes
    cfg.notes = _prompt(
        "Notes",
        default=cfg.notes,
        required=False,
        hint="optional"
    )


def _fill_one(cfg: SessionConfig, field_num: int) -> None:
    """Edit a single field (--edit mode)."""
    FIELD_MAP = {
        1: ("key",                   "KEY number"),
        2: ("goal",                  "Evolution goal"),
        3: ("success_criteria",      "Success criteria"),
        4: ("human_anchor_required", "Human confirmation"),
        5: ("max_iterations",        "Max iterations"),
        6: ("notes",                 "Notes"),
    }
    if field_num not in FIELD_MAP:
        print(f"  {red('Invalid field number')} (1-6)")
        return

    fname, label = FIELD_MAP[field_num]
    print(f"  Editing: {bold(label)}")
    print()

    if fname == "success_criteria":
        cfg.success_criteria = _prompt_list(label, default=cfg.success_criteria)
    elif fname == "human_anchor_required":
        cfg.human_anchor_required = _confirm(label, default=cfg.human_anchor_required)
    elif fname == "max_iterations":
        raw = _prompt(label, default=str(cfg.max_iterations), required=False, hint="0=unlimited")
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
    Show numbered menu for editing fields.
    Used by gcc-evo setup <KEY> --edit.
    """
    FIELDS = [
        ("KEY number",          cfg.key),
        ("Evolution goal",      cfg.goal),
        ("Success criteria",    "; ".join(cfg.success_criteria)),
        ("Human confirmation",  "yes" if cfg.human_anchor_required else "no"),
        ("Max iterations",      str(cfg.max_iterations) if cfg.max_iterations else "unlimited"),
        ("Notes",               cfg.notes or "(empty)"),
    ]

    print()
    print(bold("  Select field to edit:"))
    for i, (name, val) in enumerate(FIELDS, 1):
        print(f"  {cyan(str(i))}. {name:<22} {dim(val[:40])}")
    print(f"  {cyan('0')}. Cancel")
    print()

    try:
        raw = input(f"  {cyan('Enter number')}: ").strip()
        num = int(raw)
        if num == 0:
            return None
        if 1 <= num <= 6:
            return run_setup_wizard(existing=cfg, edit_field=num)
        print(f"  {red('Invalid number')}")
        return None
    except (ValueError, KeyboardInterrupt):
        return None
