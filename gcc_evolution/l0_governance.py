"""
GCC v5.325 - L0 governance gate for framework prerequisites and outputs.

S2: Three prerequisites must be explicitly satisfied before loop execution:
  1. data_quality
  2. deterministic_rules
  3. mathematical_filters

S4: Required L0 artifacts must exist so the framework has a reproducible trail:
  - input_source_inventory.md
  - quality_report.md
  - quality_data.json
  - input_math_models.py
  - state_vector_spec.json
  - decision_truth_table.db
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


_STATE_FILE = Path(".GCC") / "state" / "l0_governance.json"
_ARTIFACT_ROOT = Path(".GCC") / "artifacts" / "l0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PrerequisiteGate:
    """Status for one prerequisite gate."""

    key: str
    label: str
    description: str
    satisfied: bool = False
    evidence: str = ""
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "satisfied": self.satisfied,
            "evidence": self.evidence,
            "updated_at": self.updated_at,
        }


@dataclass
class ArtifactSpec:
    """Required L0 artifact."""

    key: str
    path: str
    description: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "path": self.path,
            "description": self.description,
        }


def default_prerequisites() -> list[PrerequisiteGate]:
    return [
        PrerequisiteGate(
            key="data_quality",
            label="Prerequisite 1 - Data Quality",
            description="Input sources are complete enough and quality has been reviewed.",
        ),
        PrerequisiteGate(
            key="deterministic_rules",
            label="Prerequisite 2 - Deterministic Rules",
            description="Rules can be repeated: same input should produce the same output.",
        ),
        PrerequisiteGate(
            key="mathematical_filters",
            label="Prerequisite 3 - Mathematical Filters",
            description="Filters are expressed as clear mathematical conditions.",
        ),
    ]


def default_artifacts() -> list[ArtifactSpec]:
    return [
        ArtifactSpec(
            key="phase1_inventory",
            path=str(_ARTIFACT_ROOT / "phase1" / "input_source_inventory.md"),
            description="Phase 1 full input source inventory.",
        ),
        ArtifactSpec(
            key="phase2_quality_report",
            path=str(_ARTIFACT_ROOT / "phase2" / "quality_report.md"),
            description="Phase 2 quality validation report.",
        ),
        ArtifactSpec(
            key="phase2_quality_data",
            path=str(_ARTIFACT_ROOT / "phase2" / "quality_data.json"),
            description="Phase 2 structured quality data.",
        ),
        ArtifactSpec(
            key="phase3_math_models",
            path=str(_ARTIFACT_ROOT / "phase3" / "input_math_models.py"),
            description="Phase 3 deterministic math models.",
        ),
        ArtifactSpec(
            key="phase3_state_vector",
            path=str(_ARTIFACT_ROOT / "phase3" / "state_vector_spec.json"),
            description="Phase 3 state vector specification.",
        ),
        ArtifactSpec(
            key="phase4_truth_table",
            path=str(_ARTIFACT_ROOT / "phase4" / "decision_truth_table.db"),
            description="Phase 4 decision truth table.",
        ),
    ]


def _default_state() -> dict:
    return {
        "version": "1.0",
        "updated_at": _now(),
        "prerequisites": [p.to_dict() for p in default_prerequisites()],
        "artifacts": [a.to_dict() for a in default_artifacts()],
    }


def load_governance_state(path: Path | None = None) -> dict:
    state_path = path or _STATE_FILE
    if not state_path.exists():
        return _default_state()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()
    defaults = _default_state()
    if "prerequisites" not in data:
        data["prerequisites"] = defaults["prerequisites"]
    if "artifacts" not in data:
        data["artifacts"] = defaults["artifacts"]
    if "updated_at" not in data:
        data["updated_at"] = _now()
    if "version" not in data:
        data["version"] = "1.0"
    return data


def save_governance_state(data: dict, path: Path | None = None) -> Path:
    state_path = path or _STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    state_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return state_path


def set_prerequisite_status(key: str, satisfied: bool, evidence: str = "") -> bool:
    data = load_governance_state()
    matched = False
    for item in data["prerequisites"]:
        if item.get("key") == key:
            item["satisfied"] = bool(satisfied)
            item["evidence"] = evidence.strip()
            item["updated_at"] = _now()
            matched = True
            break
    if matched:
        save_governance_state(data)
    return matched


def iter_artifact_paths(data: dict | None = None) -> Iterable[tuple[str, Path, str]]:
    state = data or load_governance_state()
    for artifact in state["artifacts"]:
        yield artifact["key"], Path(artifact["path"]), artifact["description"]


def scaffold_required_artifacts(overwrite: bool = False) -> list[Path]:
    created: list[Path] = []
    templates = {
        "phase1_inventory": "# input_source_inventory\n\n- TODO: list all input source modules.\n",
        "phase2_quality_report": "# quality_report\n\n- TODO: summarize predictive power and stability.\n",
        "phase2_quality_data": "{\n  \"status\": \"draft\",\n  \"sources\": []\n}\n",
        "phase3_math_models": '"""Deterministic math models for validated inputs."""\n\n# TODO: implement standardized input math models.\n',
        "phase3_state_vector": "{\n  \"version\": \"draft\",\n  \"state_vector\": []\n}\n",
        "phase4_truth_table": "",
    }

    data = load_governance_state()
    for key, path, _ in iter_artifact_paths(data):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            continue
        if key == "phase4_truth_table":
            path.touch()
        else:
            path.write_text(templates[key], encoding="utf-8")
        created.append(path)
    return created


def evaluate_l0_governance() -> dict:
    data = load_governance_state()
    prereq_results = []
    prereq_ok = True
    for item in data["prerequisites"]:
        ok = bool(item.get("satisfied"))
        prereq_ok = prereq_ok and ok
        prereq_results.append(
            {
                "key": item["key"],
                "label": item["label"],
                "ok": ok,
                "evidence": item.get("evidence", ""),
                "updated_at": item.get("updated_at", ""),
            }
        )

    artifact_results = []
    artifacts_ok = True
    for key, path, description in iter_artifact_paths(data):
        exists = path.exists()
        if not exists:
            artifacts_ok = False
        artifact_results.append(
            {
                "key": key,
                "path": str(path),
                "description": description,
                "exists": exists,
            }
        )

    return {
        "ok": prereq_ok and artifacts_ok,
        "prerequisites_ok": prereq_ok,
        "artifacts_ok": artifacts_ok,
        "prerequisites": prereq_results,
        "artifacts": artifact_results,
        "state_path": str(_STATE_FILE),
    }


def format_governance_summary(report: dict) -> str:
    lines = [
        "  L0 Governance Summary",
        "  ---------------------",
        f"  Prerequisites: {'PASS' if report['prerequisites_ok'] else 'BLOCKED'}",
    ]
    for item in report["prerequisites"]:
        status = "PASS" if item["ok"] else "PENDING"
        evidence = f" | evidence: {item['evidence']}" if item["evidence"] else ""
        lines.append(f"    - [{status}] {item['key']}{evidence}")
    lines.append(f"  Required Artifacts: {'PASS' if report['artifacts_ok'] else 'BLOCKED'}")
    for item in report["artifacts"]:
        status = "OK" if item["exists"] else "MISSING"
        lines.append(f"    - [{status}] {item['path']}")
    return "\n".join(lines)
