from pathlib import Path

from gcc_evolution.L1_memory.memory_tiers import LongTermMemory, SensoryMemory, ShortTermMemory
from gcc_evolution.L1_memory.storage import JSONStorage
from gcc_evolution.L2_retrieval.retriever import HybridRetriever
from gcc_evolution.L3_distillation.distiller import ExperienceDistiller
from gcc_evolution.L4_decision.skeptic import SkepticValidator, ValidatorRule
from gcc_evolution.L5_orchestration.loop_engine_base import CommunitySelfImprovementLoop
from gcc_evolution.L5_orchestration.pipeline import build_research_workflow


class _AlwaysFailRule(ValidatorRule):
    def __init__(self, idx: int):
        self.idx = idx

    def check(self, decision):
        return False, f"forced failure {self.idx}"


def _build_loop(state_dir: Path, task_id: str = "DEMO-ORCH") -> CommunitySelfImprovementLoop:
    long_term = LongTermMemory(storage=JSONStorage(str(state_dir / "ltm.json")))
    return CommunitySelfImprovementLoop(
        task_id=task_id,
        sensory_memory=SensoryMemory(),
        short_term_memory=ShortTermMemory(window_size=16),
        long_term_memory=long_term,
        retriever=HybridRetriever(),
        distiller=ExperienceDistiller(min_confidence=0.5),
        skeptic=SkepticValidator(),
        state_dir=state_dir,
    )


def test_research_workflow_factory_executes_five_stages():
    order = []
    workflow = build_research_workflow(
        {
            "exploration": lambda ctx: order.append("exploration") or {"stage": "exploration"},
            "hypothesis": lambda ctx: order.append("hypothesis") or {"stage": "hypothesis"},
            "implement": lambda ctx: order.append("implement") or {"stage": "implement"},
            "validate": lambda ctx: order.append("validate") or {"stage": "validate"},
            "distill": lambda ctx: order.append("distill") or {"stage": "distill"},
        }
    )
    results = workflow.execute({})
    assert order == ["exploration", "hypothesis", "implement", "validate", "distill"]
    assert set(results.keys()) == {"exploration", "hypothesis", "implement", "validate", "distill"}
    assert workflow.get_summary()["succeeded"] == 5


def test_loop_graph_and_auto_task_generation(tmp_path: Path):
    loop = _build_loop(tmp_path, task_id="DEMO-GRAPH")
    loop.skeptic = SkepticValidator()
    for idx in range(3):
        loop.skeptic.add_rule(_AlwaysFailRule(idx))
    result1 = loop.run_once()
    result2 = loop.run_once()

    graph_path = tmp_path / "audit" / "DEMO-GRAPH_graph.json"
    auto_task_path = tmp_path / "audit" / "DEMO-GRAPH_auto_tasks.jsonl"

    assert graph_path.exists()
    graph = __import__("json").loads(graph_path.read_text(encoding="utf-8"))
    assert len(graph.get("nodes", {})) >= 2
    first_node = graph["nodes"]["DEMO-GRAPH:0001"]
    second_node = graph["nodes"]["DEMO-GRAPH:0002"]
    assert second_node["parent_id"] == "DEMO-GRAPH:0001"
    assert "downstream_avg" in first_node

    assert auto_task_path.exists()
    lines = [line for line in auto_task_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 1
    assert "auto_task" in result1["test_result"] or "auto_task" in result2["test_result"]


def test_loop_research_workflow_runs(tmp_path: Path):
    loop = _build_loop(tmp_path, task_id="DEMO-FARS")
    result1 = loop.run_research_workflow()
    result2 = loop.run_research_workflow()
    summary = result2["workflow_summary"]
    assert summary["total_stages"] == 5
    assert summary["succeeded"] == 5
    assert "validate" in result1["workflow_results"]
    assert result1["iteration_id"] == "WF-0001"
    assert result2["iteration_id"] == "WF-0002"
    graph = __import__("json").loads((tmp_path / "audit" / "DEMO-FARS_graph.json").read_text(encoding="utf-8"))
    assert "DEMO-FARS:0001" in graph["nodes"]
    assert "DEMO-FARS:0002" in graph["nodes"]
