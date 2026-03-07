"""
L0 Setup — Pre-Session Configuration Layer (Layer 1)

Handles session initialization and goal configuration before the loop starts.
Validates session config via L0 Gate before every loop run.
"""
from ..session_config import SessionConfig
from ..setup_wizard import run_setup_wizard, run_edit_menu
from ..l0_governance import (
    evaluate_l0_governance,
    format_governance_summary,
    load_governance_state,
    save_governance_state,
    scaffold_required_artifacts,
    set_prerequisite_status,
)

__all__ = [
    "SessionConfig",
    "run_setup_wizard",
    "run_edit_menu",
    "evaluate_l0_governance",
    "format_governance_summary",
    "load_governance_state",
    "save_governance_state",
    "scaffold_required_artifacts",
    "set_prerequisite_status",
]
