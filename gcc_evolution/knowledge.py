"""
GCC v4.87 — Knowledge Importer
外部知识导入模块，支持论文、笔记、文档。

设计原则：
  支持任意格式的外部知识输入。
  通过 LLM 提取要点，生成结构化知识卡草稿。
  人类审核确认后写入知识库。
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
class KnowledgeSource:
    """外部知识来源"""
    source_id:   str
    source_type: str           # paper / notes / url / doc
    title:       str
    content:     str           # 原始内容
    imported_at: str = field(default_factory=_now)
    linked_keys: list[str] = field(default_factory=list)  # 关联的 KEY
    metadata:    dict = field(default_factory=dict)


@dataclass
class KnowledgeCardDraft:
    """知识卡草稿，待人类审核"""
    draft_id:    str
    source_id:   str
    title:       str
    key_points:  list[str]     # 核心观点
    conditions:  list[str]     # 适用条件
    related_keys: list[str]    # 与现有知识卡的关联
    suggested_key: str         # 建议关联的 KEY
    content_md:  str           # 完整 markdown 草稿
    status:      str = "draft" # draft / approved / rejected
    created_at:  str = field(default_factory=_now)
    reviewed_at: str = ""
    review_note: str = ""


class KnowledgeImporter:
    """
    外部知识导入器。
    支持：PDF、Markdown、纯文本、URL
    """

    def __init__(self, gcc_dir: Path | str = ".gcc",
                 cards_dir: Path | str = "improvement"):
        self.gcc_dir   = Path(gcc_dir)
        self.cards_dir = Path(cards_dir)
        self.cards_dir.mkdir(exist_ok=True)
        self.draft_dir = self.gcc_dir / "knowledge_drafts"
        self.draft_dir.mkdir(exist_ok=True)
        self.index_file = self.gcc_dir / "knowledge_index.jsonl"

    def import_file(self, file_path: str | Path,
                    llm_client=None) -> KnowledgeSource:
        """导入文件（PDF / MD / TXT）"""
        path = Path(file_path)
        content = self._read_file(path)
        source = KnowledgeSource(
            source_id=f"KS_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            source_type=self._detect_type(path),
            title=path.stem,
            content=content,
        )
        self._save_source(source)
        return source

    def import_text(self, text: str, title: str,
                    source_type: str = "notes") -> KnowledgeSource:
        """直接导入文本内容"""
        source = KnowledgeSource(
            source_id=f"KS_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            source_type=source_type,
            title=title,
            content=text,
        )
        self._save_source(source)
        return source

    def import_source(self, source_path: str | Path,
                      source_type: str = "",
                      linked_key: str = "",
                      llm_client=None) -> str:
        """统一导入接口：文件路径 → 导入 + 生成草稿 + 保存 → 返回 draft_id。

        research_workflow 调用此方法完成论文导入全流程。
        """
        ks = self.import_file(source_path, llm_client=llm_client)
        if source_type:
            ks.source_type = source_type
        draft = self.generate_draft(ks, llm_client=llm_client)
        if linked_key:
            draft.suggested_key = linked_key
        self.save_draft(draft)
        if linked_key:
            self.link_to_key(ks.source_id, linked_key)
        return draft.draft_id

    def generate_draft(self, source: KnowledgeSource,
                       llm_client=None,
                       existing_keys: list[str] = None) -> KnowledgeCardDraft:
        """
        用 LLM 从知识来源生成知识卡草稿。
        llm_client 为 None 时使用规则提取。
        """
        if llm_client:
            return self._llm_extract(source, llm_client, existing_keys or [])
        else:
            return self._rule_extract(source, existing_keys or [])

    def save_draft(self, draft: KnowledgeCardDraft):
        """保存草稿到待审核目录"""
        path = self.draft_dir / f"{draft.draft_id}.json"
        path.write_text(
            json.dumps(self._draft_to_dict(draft), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def list_drafts(self) -> list[KnowledgeCardDraft]:
        """列出所有待审核草稿"""
        drafts = []
        for f in sorted(self.draft_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("status") == "draft":
                    drafts.append(self._dict_to_draft(data))
            except Exception as e:
                logger.warning("[KNOWLEDGE] load draft %s failed: %s", f.name, e)
        return drafts

    def approve_draft(self, draft_id: str,
                      note: str = "") -> Path | None:
        """审核通过，写入知识卡"""
        draft = self._load_draft(draft_id)
        if not draft:
            return None

        # 生成知识卡文件
        filename = f"{draft.suggested_key}_{draft.title.replace(' ', '_')}.md"
        card_path = self.cards_dir / filename
        card_path.write_text(draft.content_md, encoding="utf-8")

        # 更新草稿状态
        draft.status = "approved"
        draft.reviewed_at = _now()
        draft.review_note = note
        self.save_draft(draft)

        # 记录到索引
        self._append_index({
            "draft_id": draft_id,
            "card_path": str(card_path),
            "approved_at": _now(),
            "key": draft.suggested_key,
        })

        return card_path

    def reject_draft(self, draft_id: str, note: str = ""):
        """拒绝草稿"""
        draft = self._load_draft(draft_id)
        if draft:
            draft.status = "rejected"
            draft.reviewed_at = _now()
            draft.review_note = note
            self.save_draft(draft)

    def link_to_key(self, source_id: str, key: str):
        """关联知识来源到具体 KEY"""
        # 更新 index 记录
        self._append_index({
            "source_id": source_id,
            "linked_key": key,
            "linked_at": _now(),
        })

    # ── 内部方法 ──────────────────────────────────────────────

    def _read_file(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(path) as pdf:
                    return "\n".join(p.extract_text() or "" for p in pdf.pages)
            except ImportError:
                return f"[PDF 需要安装 pdfplumber: pip install pdfplumber]\n{path}"
        else:
            return path.read_text(encoding="utf-8", errors="ignore")

    def _detect_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        return {"pdf": "paper", ".md": "notes",
                ".txt": "notes"}.get(suffix, "doc")

    def _rule_extract(self, source: KnowledgeSource,
                      existing_keys: list) -> KnowledgeCardDraft:
        """简单规则提取（无 LLM 时的回退）"""
        lines = source.content.split("\n")
        key_points = [l.strip() for l in lines
                      if l.strip() and not l.startswith("#")][:5]
        draft_id = f"KD_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        content_md = f"# {source.title}\n\n## 来源\n{source.source_type}\n\n## 核心要点\n"
        content_md += "\n".join(f"- {p}" for p in key_points)
        return KnowledgeCardDraft(
            draft_id=draft_id,
            source_id=source.source_id,
            title=source.title,
            key_points=key_points,
            conditions=[],
            related_keys=[],
            suggested_key=existing_keys[0] if existing_keys else "KEY-NEW",
            content_md=content_md,
        )

    def _llm_extract(self, source: KnowledgeSource,
                     llm_client, existing_keys: list) -> KnowledgeCardDraft:
        """GCC-0168: 用 LLM 提取知识点（修正接口: generate(system, user)）"""
        system_prompt = (
            "你是知识卡提取助手。从用户提供的内容中提取知识卡，"
            "输出纯 JSON（不要 markdown 包裹）。"
        )
        user_prompt = f"""从以下内容提取知识卡，输出 JSON：
{{
  "title": "简短标题",
  "key_points": ["核心观点1", "核心观点2"],
  "conditions": ["适用条件1"],
  "related_keys": ["相关KEY"],
  "suggested_key": "最相关的KEY（从{existing_keys}选）",
  "content_md": "完整 markdown 知识卡内容"
}}

内容：
{source.content[:3000]}
"""
        try:
            response = llm_client.generate(system_prompt, user_prompt)
            # 尝试提取嵌入的 JSON
            text = response.strip()
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    text = text[start:end]
            data = json.loads(text)
            draft_id = f"KD_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            return KnowledgeCardDraft(
                draft_id=draft_id,
                source_id=source.source_id,
                title=data.get("title", source.title),
                key_points=data.get("key_points", []),
                conditions=data.get("conditions", []),
                related_keys=data.get("related_keys", []),
                suggested_key=data.get("suggested_key", "KEY-NEW"),
                content_md=data.get("content_md", ""),
            )
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.warning("[KNOWLEDGE] LLM extract parse failed, fallback to rule: %s", e)
            return self._rule_extract(source, existing_keys)
        except Exception as e:
            logger.warning("[KNOWLEDGE] LLM extract failed, fallback to rule: %s", e)
            return self._rule_extract(source, existing_keys)

    def _save_source(self, source: KnowledgeSource):
        self._append_index({
            "source_id": source.source_id,
            "source_type": source.source_type,
            "title": source.title,
            "imported_at": source.imported_at,
        })

    def _append_index(self, data: dict):
        with open(self.index_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def _load_draft(self, draft_id: str) -> KnowledgeCardDraft | None:
        path = self.draft_dir / f"{draft_id}.json"
        if not path.exists():
            return None
        try:
            return self._dict_to_draft(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("[KNOWLEDGE] load draft by id failed: %s", e)
            return None

    def _draft_to_dict(self, d: KnowledgeCardDraft) -> dict:
        return {k: v for k, v in d.__dict__.items()}

    def _dict_to_draft(self, data: dict) -> KnowledgeCardDraft:
        return KnowledgeCardDraft(**{k: v for k, v in data.items()
                                     if k in KnowledgeCardDraft.__dataclass_fields__})
