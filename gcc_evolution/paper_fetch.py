"""
GCC v4.96 — Paper Fetch
========================
扩展 ResearchWorkflow，让它能从学术 API 自动拉取论文。

设计原则：
  与现有 ResearchWorkflow 无缝衔接。
  拉取到的论文 → 生成临时 markdown 文件 → 走原有 run_file() 流程。
  对 GCC 其余模块完全透明。

用法（命令行）：
  gcc-evo research fetch "agentic memory"
  gcc-evo research fetch "缠论趋势反转" --domain trading
  gcc-evo research update          # 按 RESEARCH.md 主题自动更新

用法（代码）：
  from gcc_evolution.paper_fetch import PaperFetch
  pf = PaperFetch()
  pf.fetch_and_import("agentic memory", key_id="KEY-001", top_k=5)
"""
from __future__ import annotations

import asyncio
import sys
import os
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paper Engine 路径 ──────────────────────────────────
_HERE = Path(__file__).parent
_ENGINE = _HERE / "paper_engine"
for _p in [str(_ENGINE), str(_ENGINE / "core"),
           str(_ENGINE / "sources"), str(_ENGINE / "domains")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 领域关键词 → domain 映射 ──────────────────────────
_DOMAIN_KEYWORDS = {
    "trading":       ["交易", "因子", "alpha", "回测", "量化", "trading", "factor", "backtest"],
    "chan_theory":   ["缠论", "技术分析", "k线", "candlestick", "wyckoff", "chart pattern"],
    "industrial_ai": ["焊接", "CNC", "机器人", "工厂", "welding", "robot", "factory", "edge ai"],
    "medical":       ["医疗", "临床", "medical", "clinical", "biomedical"],
    "gcc":           ["agent", "memory", "代码", "编程", "code", "agentic", "llm", "记忆"],
}


def _infer_domain(topic: str) -> str:
    t = topic.lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return domain
    return "gcc"


class PaperFetch:
    """
    从学术 API 拉取论文，转换为 GCC knowledge 草稿。

    流程：
        topic → PaperResearcher.search_papers_only()
              → Paper 列表
              → 每篇生成 .md 文件到 research_inbox/
              → ResearchWorkflow.run_inbox() 自动处理
    """

    def __init__(
        self,
        gcc_dir: str | Path = ".gcc",
        inbox_dir: str | Path = "research_inbox",
        auto_approve: bool = False,
        llm_client=None,
    ):
        self.gcc_dir    = Path(gcc_dir)
        self.inbox_dir  = Path(inbox_dir)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.auto_approve = auto_approve
        self.llm_client   = llm_client
        self._log_file    = self.gcc_dir / "paper_fetch.jsonl"
        self.gcc_dir.mkdir(parents=True, exist_ok=True)

    # ── 主入口 ────────────────────────────────────────

    def fetch_and_import(
        self,
        topic: str,
        key_id: str = "",
        domain: str = None,
        top_k: int = 5,
        year_from: int = 2022,
        auto_run_workflow: bool = True,
    ) -> dict:
        """
        同步入口（供命令行 / 非 async 代码使用）。

        Returns:
            {"fetched": N, "results": [WorkflowResult...]}
        """
        return asyncio.run(
            self.afetch_and_import(
                topic=topic,
                key_id=key_id,
                domain=domain or _infer_domain(topic),
                top_k=top_k,
                year_from=year_from,
                auto_run_workflow=auto_run_workflow,
            )
        )

    async def afetch_and_import(
        self,
        topic: str,
        key_id: str = "",
        domain: str = None,
        top_k: int = 5,
        year_from: int = 2022,
        auto_run_workflow: bool = True,
    ) -> dict:
        """异步主流程。"""
        domain = domain or _infer_domain(topic)

        # Step 1: 拉取论文
        papers = await self._fetch_papers(topic, domain, top_k, year_from)
        if not papers:
            return {"fetched": 0, "results": []}

        # Step 2: 写入 inbox（每篇 → .md 文件）
        written = self._papers_to_inbox(papers, topic, key_id)
        print(f"[PaperFetch] 写入 {written} 篇到 {self.inbox_dir}/")

        # Step 3: 走 ResearchWorkflow
        results = []
        if auto_run_workflow:
            results = self._run_workflow(key_id)

        return {"fetched": written, "results": results}

    def update_from_research_md(
        self,
        research_md_path: str | Path = "RESEARCH.md",
        top_k_per_topic: int = 3,
    ) -> dict:
        """
        解析 RESEARCH.md，自动为每篇论文搜索最新相关研究。
        在 RESEARCH.md 每个 ### 条目后追加 '最新进展' 小节。
        """
        path = Path(research_md_path)
        if not path.exists():
            return {"error": "RESEARCH.md not found"}

        content = path.read_text(encoding="utf-8")

        # 提取论文标题作为搜索主题
        import re
        topics = re.findall(r"###\s+.*?—\s+(.+?)$", content, re.MULTILINE)
        topics = [t.strip() for t in topics if t.strip()][:10]  # 最多10个

        total = 0
        for topic in topics:
            result = self.fetch_and_import(
                topic=topic,
                top_k=top_k_per_topic,
                auto_run_workflow=False,  # 批量写入后统一处理
            )
            total += result["fetched"]
            print(f"  [{topic[:40]}] → {result['fetched']} 篇")

        # 统一处理 inbox
        results = self._run_workflow(key_id="")
        return {"topics": len(topics), "fetched": total, "imported": len(results)}

    # ── 内部方法 ──────────────────────────────────────

    async def _fetch_papers(self, topic, domain, top_k, year_from):
        """调用 Paper Engine 拉取论文列表。"""
        try:
            from gcc_evolution.paper_engine import PaperResearcher
            researcher = PaperResearcher(
                domain=domain,
                llm_client=self.llm_client,
            )
            papers = await researcher.search_papers_only(
                topic=topic,
                top_k=top_k,
                year_from=year_from,
            )
            return papers
        except Exception as e:
            print(f"[PaperFetch] 拉取失败: {e}")
            return []

    def _papers_to_inbox(self, papers, topic, key_id) -> int:
        """将 Paper 列表写成 markdown 文件到 inbox。"""
        written = 0
        for paper in papers:
            try:
                md = self._paper_to_md(paper, topic, key_id)
                safe_id = paper.paper_id.replace(":", "_").replace("/", "_")
                fname   = f"paper_{safe_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
                (self.inbox_dir / fname).write_text(md, encoding="utf-8")
                written += 1
            except Exception as e:
                print(f"  [!] 写入失败 {paper.paper_id}: {e}")
        return written

    def _paper_to_md(self, paper, topic, key_id) -> str:
        """Paper 对象 → GCC knowledge 可读的 markdown。"""
        authors = ", ".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors += " et al."

        lines = [
            f"# {paper.title}",
            "",
            f"**来源ID**: {paper.paper_id}  ",
            f"**年份**: {paper.year or 'N/A'}  ",
            f"**作者**: {authors}  ",
            f"**发表平台**: {paper.venue or paper.source}  ",
            f"**引用数**: {paper.citation_count}  ",
            f"**URL**: {paper.url}  ",
        ]
        if paper.pdf_url:
            lines.append(f"**PDF**: {paper.pdf_url}  ")
        if paper.doi:
            lines.append(f"**DOI**: {paper.doi}  ")

        lines += [
            "",
            "## 摘要",
            paper.abstract or "(无摘要)",
            "",
            "## 元信息",
            f"- 搜索主题: {topic}",
            f"- 关联KEY: {key_id or '未指定'}",
            f"- 获取时间: {_now()}",
            f"- 标签: {', '.join(paper.tags[:8])}",
        ]
        return "\n".join(lines)

    def _run_workflow(self, key_id: str):
        """触发 ResearchWorkflow 处理 inbox。"""
        try:
            from gcc_evolution.research_workflow import ResearchWorkflow
            wf = ResearchWorkflow(
                gcc_dir=str(self.gcc_dir),
                auto_approve=self.auto_approve,
                inbox_dir=str(self.inbox_dir),
            )
            results = wf.run_inbox(key_id=key_id)
            self._log_results(results)
            return results
        except Exception as e:
            print(f"[PaperFetch] workflow 失败: {e}")
            return []

    def _log_results(self, results):
        if not results:
            return
        with self._log_file.open("a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps({
                    "source": r.source,
                    "key_id": r.key_id,
                    "status": r.status,
                    "ran_at": r.ran_at,
                }, ensure_ascii=False) + "\n")

    def history(self, limit: int = 20) -> list:
        if not self._log_file.exists():
            return []
        lines = self._log_file.read_text(encoding="utf-8").strip().split("\n")
        out = []
        for line in reversed(lines[-limit:]):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception as e:
                    logger.warning("[PAPER_FETCH] Failed to parse history line: %s", e)
        return out
