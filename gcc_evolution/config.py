"""
GCC v4.1 — Configuration
v4.1: + embedding_model, graph_hop_depth, goal_aware_pruning
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    import subprocess
    print("  ⚡ First run: installing pyyaml...", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "pyyaml", "--quiet", "--break-system-packages"],
        capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ pyyaml installed successfully", flush=True)
        import yaml
    else:
        print(f"  ✗ pyyaml install failed: {result.stderr.strip()}")
        print("  Fix: pip install pyyaml")
        sys.exit(1)


@dataclass
class GCCConfig:
    version: str = "5.050"
    project_name: str = ""
    project_type: str = "custom"

    # Evolution
    auto_evaluate: bool = True
    auto_distill: bool = True
    eval_weights: dict[str, float] = field(
        default_factory=lambda: {"outcome": 0.5, "efficiency": 0.3, "novelty": 0.2}
    )

    # Memory
    local_dir: str = ".gcc/local_memory"
    global_db: str = ".gcc/experiences/global.db"
    embedding: str = "local"            # local | semantic | auto
    embedding_model: str = "all-MiniLM-L6-v2"  # v4.1
    retrieval_top_k: int = 5
    graph_hop_depth: int = 1            # v4.1: 0=disable, 1=default
    goal_aware_pruning: bool = True     # v4.1: SWE-Pruner step-level

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = ""
    llm_api_base: str = ""
    llm_temperature: float = 0.2

    # v4.4: Pipeline
    pipeline_max_concurrent: int = 3
    pipeline_max_iterations: int = 3
    pipeline_gate_strict: bool = True

    # v4.5: Handoff
    handoff_auto_detect: bool = True
    handoff_source_agent: str = "claude-code"

    def __post_init__(self):
        if not self.llm_api_key:
            env_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
            }
            self.llm_api_key = os.environ.get(env_map.get(self.llm_provider, ""), "")



    @classmethod
    def load(cls, path=None) -> "GCCConfig":
        """classmethod 入口，兼容 GCCConfig.load() 调用方式。"""
        return load_config(path)

CONFIG_SEARCH_PATHS = [
    ".gcc/evolution.yaml",
    ".gcc/evolution.yml",
    "gcc_evolution.yaml",
]


def load_config(path: str | Path | None = None) -> GCCConfig:
    """Load config from YAML. Falls back to defaults if not found."""
    config_path = None
    if path:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
    else:
        for p in CONFIG_SEARCH_PATHS:
            if Path(p).exists():
                config_path = Path(p)
                break

    if config_path is None:
        return GCCConfig()

    raw = yaml.safe_load(config_path.read_text("utf-8")) or {}
    return _parse(raw)


def _parse(raw: dict) -> GCCConfig:
    proj = raw.get("project", {})
    evo = raw.get("evolution", {})
    mem = raw.get("memory", {})
    llm = raw.get("llm", {})

    return GCCConfig(
        version=raw.get("version", "5.050"),
        project_name=proj.get("name", ""),
        project_type=proj.get("type", "custom"),
        auto_evaluate=evo.get("auto_evaluate", True),
        auto_distill=evo.get("auto_distill", True),
        eval_weights=evo.get("evaluation_weights",
                             {"outcome": 0.5, "efficiency": 0.3, "novelty": 0.2}),
        local_dir=mem.get("local_dir", ".gcc/local_memory"),
        global_db=mem.get("global_db", ".gcc/experiences/global.db"),
        embedding=mem.get("embedding", "local"),
        embedding_model=mem.get("embedding_model", "all-MiniLM-L6-v2"),
        retrieval_top_k=mem.get("retrieval_top_k", 5),
        graph_hop_depth=mem.get("graph_hop_depth", 1),
        goal_aware_pruning=mem.get("goal_aware_pruning", True),
        llm_provider=llm.get("provider", "anthropic"),
        llm_model=llm.get("model", "claude-sonnet-4-20250514"),
        llm_api_key=llm.get("api_key", ""),
        llm_api_base=llm.get("api_base", ""),
        llm_temperature=llm.get("temperature", 0.2),
    )


def init_config(project_name: str, project_type: str = "custom") -> Path:
    """Create default .gcc/evolution.yaml."""
    gcc_dir = Path(".gcc")
    gcc_dir.mkdir(exist_ok=True)
    Path(".gcc/experiences").mkdir(exist_ok=True)
    Path(".gcc/local_memory").mkdir(exist_ok=True)

    config_path = gcc_dir / "evolution.yaml"
    config_path.write_text(f"""# GCC v4.1 Evolution Config
version: "5.050"

project:
  name: "{project_name}"
  type: "{project_type}"

evolution:
  auto_evaluate: true
  auto_distill: true
  evaluation_weights:
    outcome: 0.5
    efficiency: 0.3
    novelty: 0.2

memory:
  local_dir: ".gcc/local_memory"
  global_db: ".gcc/experiences/global.db"
  embedding: "local"             # local | semantic | auto
  embedding_model: "all-MiniLM-L6-v2"  # or paraphrase-multilingual-MiniLM-L12-v2
  retrieval_top_k: 5
  graph_hop_depth: 1             # 0=disable graph expansion
  goal_aware_pruning: true       # SWE-Pruner step-level retrieval

llm:
  provider: "anthropic"
  model: "claude-sonnet-4-20250514"
  # api_key: from ANTHROPIC_API_KEY env var
  temperature: 0.2
""", encoding="utf-8")
    return config_path
