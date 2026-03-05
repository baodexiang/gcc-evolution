"""
GCC v4.91 — Research Workflow
自动研究迭代流程。

设计原则：
  外部输入（论文/文档/URL）→ 自动走完导入→蒸馏→opinion 全流程。
  引擎不知道研究的是什么领域，用户配置输入源和关联改善点。

完整流程：
  1. 扫描 inbox 目录（或指定文件）
  2. knowledge import → 生成草稿
  3. LLM 自动评估草稿质量（可配置是否跳过人工审核）
  4. 批准后 → skillbank distill
  5. 生成 opinion 摘要
  6. 写入分析报告

使用方式：
  wf = ResearchWorkflow()
  wf.run_inbox()             # 扫描 inbox/ 目录
  wf.run_file("paper.pdf", key="KEY-001")
  wf.run_url("https://...", key="KEY-002")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowResult:
    """单次研究迭代结果"""
    source:      str
    key_id:      str
    status:      str        # success / skipped / failed
    draft_id:    str = ""
    skill_count: int = 0
    opinion:     str = ""
    error:       str = ""
    ran_at:      str = field(default_factory=_now)


class ResearchWorkflow:
    """
    自动研究迭代引擎。

    配置选项：
      auto_approve   True = LLM 自动审核草稿（跳过人工）
                     False = 草稿等待人工 gcc-evo knowledge review
      min_quality    LLM 评分低于此值则丢弃（0.0-1.0）
      inbox_dir      自动扫描的输入目录
    """

    def __init__(self, gcc_dir: str | Path = ".gcc",
                 auto_approve: bool = False,
                 min_quality: float = 0.6,
                 inbox_dir: str = "research_inbox"):
        self.gcc_dir      = Path(gcc_dir)
        self.auto_approve = auto_approve
        self.min_quality  = min_quality
        self.inbox_dir    = Path(inbox_dir)
        self._log_file    = self.gcc_dir / "research_workflow.jsonl"
        self._llm         = None

    # ── 主入口 ────────────────────────────────────────────

    def run_inbox(self, key_id: str = "") -> list[WorkflowResult]:
        """
        扫描 inbox 目录，自动处理所有新文件。
        支持 pdf / md / txt / url 文件（url文件每行一个URL）
        """
        if not self.inbox_dir.exists():
            self.inbox_dir.mkdir(parents=True)
            return []

        results = []
        processed = self._load_processed()

        for f in sorted(self.inbox_dir.iterdir()):
            if str(f) in processed:
                continue
            if f.suffix.lower() in (".pdf", ".md", ".txt"):
                result = self.run_file(str(f), key_id=key_id)
            elif f.suffix.lower() == ".url":
                for url in f.read_text(encoding="utf-8").strip().split("\n"):
                    url = url.strip()
                    if url:
                        result = self.run_url(url, key_id=key_id)
                        results.append(result)
                        self._log(result)
                continue
            else:
                continue

            results.append(result)
            self._log(result)
            if result.status == "success":
                processed.add(str(f))
                self._save_processed(processed)

        return results

    def run_file(self, file_path: str, key_id: str = "") -> WorkflowResult:
        """处理单个文件"""
        path = Path(file_path)
        if not path.exists():
            return WorkflowResult(source=file_path, key_id=key_id,
                                  status="failed", error="文件不存在")
        return self._run_source(str(path), source_type="file", key_id=key_id)

    def run_url(self, url: str, key_id: str = "") -> WorkflowResult:
        """处理 URL"""
        return self._run_source(url, source_type="url", key_id=key_id)

    def run_text(self, text: str, title: str = "",
                 key_id: str = "") -> WorkflowResult:
        """直接处理文本内容（随手记、笔记等）"""
        # 写入临时文件
        tmp = self.gcc_dir / f"tmp_research_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        tmp.write_text(f"# {title}\n\n{text}", encoding="utf-8")
        result = self.run_file(str(tmp), key_id=key_id)
        tmp.unlink(missing_ok=True)
        return result

    # ── 核心流程 ──────────────────────────────────────────

    def _run_source(self, source: str,
                    source_type: str,
                    key_id: str) -> WorkflowResult:
        result = WorkflowResult(source=source, key_id=key_id, status="failed")

        # Step 1: 导入生成草稿
        try:
            from gcc_evolution.knowledge import KnowledgeImporter
            importer  = KnowledgeImporter(self.gcc_dir)
            draft_id  = importer.import_source(source, source_type=source_type,
                                                linked_key=key_id)
            result.draft_id = draft_id
        except Exception as e:
            result.error = f"导入失败: {e}"
            return result

        # Step 2: 评估草稿质量
        if self.auto_approve:
            quality, feedback = self._evaluate_draft(draft_id)
            if quality < self.min_quality:
                result.status = "skipped"
                result.error  = f"质量评分 {quality:.0%} 低于阈值 {self.min_quality:.0%}: {feedback}"
                return result

            # 自动批准
            try:
                from gcc_evolution.knowledge import KnowledgeImporter
                KnowledgeImporter(self.gcc_dir).approve_draft(draft_id)
            except Exception as e:
                result.error = f"批准失败: {e}"
                return result
        else:
            # 人工审核模式：记录草稿ID，返回 pending
            result.status = "pending_review"
            result.error  = f"草稿 {draft_id} 等待人工审核: gcc-evo knowledge review {draft_id}"
            self._log(result)
            return result

        # Step 3: 蒸馏到 SkillBank
        try:
            from gcc_evolution.skill_registry import SkillBank
            sb = SkillBank(self.gcc_dir)
            n  = sb.distill_from_cards()
            result.skill_count = n
        except Exception as e:
            logger.warning("[RESEARCH_WF] distill to SkillBank failed: %s", e)
            pass

        # Step 4: 生成 opinion 摘要
        try:
            opinion = self._generate_opinion(source, key_id)
            result.opinion = opinion
        except Exception as e:
            logger.warning("[RESEARCH_WF] generate opinion failed: %s", e)
            pass

        result.status = "success"
        return result

    # ── LLM 评估 ──────────────────────────────────────────

    def _evaluate_draft(self, draft_id: str) -> tuple[float, str]:
        """
        LLM 评估草稿质量，返回 (score, feedback)。
        score: 0.0-1.0，低于 min_quality 则丢弃。
        """
        llm = self._get_llm()
        if not llm:
            return 0.8, "LLM 未配置，默认通过"

        try:
            from gcc_evolution.knowledge import KnowledgeImporter
            importer = KnowledgeImporter(self.gcc_dir)
            draft    = importer.get_draft(draft_id)
            if not draft:
                return 0.5, "草稿不存在"

            system = """你是知识质量评估器。
评估一份知识草稿是否值得加入知识库。
只返回 JSON：{"score": 0.0-1.0, "feedback": "一句话说明"}
评分标准：
  0.8+ 有明确结论和可操作建议
  0.6-0.8 有价值但较泛泛
  0.6以下 太模糊或与主题无关"""

            user = f"草稿内容：\n{str(draft)[:1000]}"
            raw  = llm.generate(system=system, user=user, max_tokens=100)
            raw  = raw.strip().strip("```json").strip("```").strip()
            data = json.loads(raw)
            return float(data.get("score", 0.5)), data.get("feedback", "")
        except Exception as e:
            logger.warning("[RESEARCH_WF] draft evaluation failed: %s", e)
            return 0.7, "评估失败，默认通过"

    def _generate_opinion(self, source: str, key_id: str) -> str:
        """对新导入的内容生成简短 opinion"""
        llm = self._get_llm()
        if not llm:
            return ""
        try:
            system = "你是研究助手，用一两句话总结新导入的知识对当前项目有什么价值，简洁有力。"
            user   = f"新导入来源：{source}\n关联改善点：{key_id or '未指定'}"
            return llm.generate(system=system, user=user, max_tokens=150).strip()
        except Exception as e:
            logger.warning("[RESEARCH_WF] generate opinion LLM failed: %s", e)
            return ""

    # ── 查询历史 ──────────────────────────────────────────

    def history(self, limit: int = 20) -> list[WorkflowResult]:
        """查看研究迭代历史"""
        if not self._log_file.exists():
            return []
        lines = self._log_file.read_text(encoding="utf-8").strip().split("\n")
        results = []
        for line in reversed(lines[-limit:]):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                results.append(WorkflowResult(**d))
            except Exception as e:
                logger.warning("[RESEARCH_WF] parse history line failed: %s", e)
                pass
        return results

    def status_summary(self) -> dict:
        """汇总统计"""
        hist = self.history(limit=100)
        return {
            "total":          len(hist),
            "success":        sum(1 for r in hist if r.status == "success"),
            "pending_review": sum(1 for r in hist if r.status == "pending_review"),
            "skipped":        sum(1 for r in hist if r.status == "skipped"),
            "failed":         sum(1 for r in hist if r.status == "failed"),
            "skills_added":   sum(r.skill_count for r in hist),
        }

    # ── 工具 ──────────────────────────────────────────────

    def _get_llm(self):
        if self._llm:
            return self._llm
        try:
            from gcc_evolution.config import GCCConfig
            from gcc_evolution.llm_client import LLMClient
            cfg = GCCConfig.load()
            if cfg.llm_api_key:
                self._llm = LLMClient(cfg)
        except Exception as e:
            logger.warning("[RESEARCH_WF] LLM client init failed: %s", e)
            pass
        return self._llm

    def _log(self, result: WorkflowResult):
        line = json.dumps({
            "source":      result.source,
            "key_id":      result.key_id,
            "status":      result.status,
            "draft_id":    result.draft_id,
            "skill_count": result.skill_count,
            "opinion":     result.opinion,
            "error":       result.error,
            "ran_at":      result.ran_at,
        }, ensure_ascii=False)
        with self._log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _load_processed(self) -> set:
        f = self.gcc_dir / "research_processed.json"
        if not f.exists():
            return set()
        try:
            return set(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("[RESEARCH_WF] load processed file failed: %s", e)
            return set()

    def _save_processed(self, processed: set):
        f = self.gcc_dir / "research_processed.json"
        f.write_text(json.dumps(list(processed), ensure_ascii=False), encoding="utf-8")
