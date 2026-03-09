#!/usr/bin/env python3
"""
PDF知识卡提取器 v3
规范：EXTRACTION_REQUIREMENTS_v3.md
流程：OCR page_*.md 或 ABBYY txt → 章节分段 → DeepSeek提取 → JSON+MD知识卡 → GCC知识库
"""

import os
import re
import sys
import json
import time
import uuid
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from openai import OpenAI

# ─── Windows safe print (strip emoji on non-UTF8 terminals) ──────────────────
import builtins as _builtins
_orig_print = _builtins.print

def _safe_print(*args, **kwargs):
    try:
        _orig_print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = []
        for a in args:
            s = str(a)
            safe_args.append(s.encode('ascii', errors='replace').decode('ascii'))
        _orig_print(*safe_args, **kwargs)

_builtins.print = _safe_print

# ─── 配置 ────────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "your_key_here")
MAX_CARDS_PER_CHAPTER = 5
TARGET_TOTAL_CARDS = (30, 80)
EVIDENCE_RATE_TARGET = 0.80
RULE_RATE_TARGET = 0.40
MODULE_RATE_TARGET = 0.70

# ─── 书籍配置 ─────────────────────────────────────────────────────────────────
BOOK_CONFIGS = {
    "price_action": {
        "keywords": ["price action", "al brooks", "bar by bar", "trading price action"],
        "modules": ["TrendDetection", "SignalFilter", "EntryEngine", "ExitEngine",
                    "PatternRecognition", "RiskManager", "MarketStructure"],
        "domain": "价格行为交易(Price Action Trading)",
        "system_prompt": """你是Al Brooks价格行为交易系统的专业分析师。
你的任务是从书籍文本中提取精确、可操作的交易知识卡。

核心原则：
1. 每张卡必须基于文本中的具体证据，禁止推断或捏造
2. atomic_claims必须包含原文页码和引用（从上下文推断页码）
3. rules必须是IF/THEN格式的可执行交易规则
4. system_mapping必须映射到具体的交易系统模块

交易系统模块说明：
- TrendDetection: 趋势识别、方向判断
- SignalFilter: 信号过滤、质量评估
- EntryEngine: 入场条件、触发逻辑
- ExitEngine: 出场条件、止盈止损
- PatternRecognition: K线形态、价格模式
- RiskManager: 风险控制、仓位管理
- MarketStructure: 市场结构、支撑阻力"""
    },
    "wyckoff": {
        "keywords": ["wyckoff", "威科夫", "composite man", "accumulation", "distribution"],
        "modules": ["PhaseDetection", "VolumeAnalysis", "SpringDetection",
                    "EntryEngine", "TrendDetection", "MarketStructure"],
        "domain": "威科夫交易法(Wyckoff Method)",
        "system_prompt": """你是威科夫交易法专家分析师。提取威科夫相关知识卡。
重点：阶段划分、价量关系、弹簧/推力、合成人行为、买卖点。"""
    },
    "general_trading": {
        "keywords": [],
        "modules": ["TrendDetection", "SignalFilter", "EntryEngine", "ExitEngine",
                    "RiskManager", "MarketStructure", "PatternRecognition"],
        "domain": "量化交易系统",
        "system_prompt": """你是专业量化交易系统分析师。从交易书籍文本提取可操作的知识卡。
确保每张卡有具体的交易规则和系统映射。"""
    }
}

# ─── 无效页面关键词 ───────────────────────────────────────────────────────────
SKIP_PATTERNS = [
    r'^(i{1,4}|v|vi{1,3}|ix|x{1,3}|xi{1,3}|xiv|xv)$',  # 罗马数字页码
    r'john wiley',
    r'published by',
    r'copyright',
    r'isbn',
    r'library of congress',
    r'printed in',
    r'all rights reserved',
    r'acknowledgment',
    r'table of contents',
    r'^contents$',
    r'about the author',
    r'about the website',
    r'^index$',
]

# ─── OCR page_*.md 目录输入支持 ───────────────────────────────────────────────────

def load_from_md_dir(md_dir: Path) -> str:
    """Read page_*.md files from OCR output directory, merge into one text.
    Inserts page markers so chapter detection works correctly.
    """
    md_dir = Path(md_dir)
    md_files = sorted(md_dir.glob('page_*.md'),
                       key=lambda p: int(re.search(r'page_(\d+)', p.stem).group(1))
                       if re.search(r'page_(\d+)', p.stem) else 0)
    if not md_files:
        raise FileNotFoundError(f'No page_*.md files in {md_dir}')

    parts = []
    for md_path in md_files:
        text = md_path.read_text(encoding='utf-8', errors='ignore').strip()
        if not text or text == '[EMPTY OCR RESULT]' or text == '[EMPTY_PAGE]':
            continue
        # Insert page number marker for chapter detection context
        page_num = re.search(r'page_(\d+)', md_path.stem)
        page_label = int(page_num.group(1)) + 1 if page_num else 0
        parts.append(f'\n{page_label}\n{text}')

    if not parts:
        raise ValueError(f'All page_*.md files in {md_dir} are empty')

    print(f'   Loaded {len(parts)} pages from {md_dir}')
    return '\n'.join(parts)


# ─── 数据结构 ─────────────────────────────────────────────────────────────────
@dataclass
class Chapter:
    chapter_id: str
    title: str
    pages: list
    text: str
    line_start: int
    line_end: int

@dataclass
class KnowledgeCard:
    id: str
    type: str
    title: str
    quality: str
    confidence: float
    content: dict
    atomic_claims: list
    rules: list
    numeric_thresholds: list
    source: dict
    system_mapping: dict
    related_cards: list = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "quality": self.quality,
            "confidence": self.confidence,
            "content": self.content,
            "atomic_claims": self.atomic_claims,
            "rules": self.rules,
            "numeric_thresholds": self.numeric_thresholds,
            "source": self.source,
            "system_mapping": self.system_mapping,
            "related_cards": self.related_cards
        }

    def quality_check(self) -> tuple[str, list]:
        """质量门控，返回(quality, failures)"""
        failures = []
        summary = self.content.get("summary", "")
        if len(summary) > 50:
            failures.append(f"summary超长({len(summary)}字 > 50字)")
        if not self.atomic_claims or not any(
            c.get("evidence") and c["evidence"] != "待补充" for c in self.atomic_claims
        ):
            failures.append("无有效evidence")
        if not self.system_mapping.get("module"):
            failures.append("system_mapping.module为空")
        if not self.rules or not any(
            r.get("if") and r.get("then") for r in self.rules
        ):
            failures.append("无有效IF/THEN规则")
        if failures:
            return "draft", failures
        return "extracted", []


def detect_book_type(book_name: str, sample: str) -> str:
    combined = (book_name + sample).lower()
    for btype, cfg in BOOK_CONFIGS.items():
        if btype == "general_trading":
            continue
        if any(kw in combined for kw in cfg["keywords"]):
            return btype
    return "general_trading"


def clean_line(line: str) -> Optional[str]:
    """清洗单行，返回None表示丢弃"""
    line = line.strip()
    if not line:
        return None
    # 过滤高密度乱码（^符号超过20%）
    garbage_ratio = sum(1 for c in line if c in '^@\\{}[]`') / max(len(line), 1)
    if garbage_ratio > 0.15:
        return None
    # 过滤无效页面关键词
    line_lower = line.lower()
    for pat in SKIP_PATTERNS:
        if re.match(pat, line_lower):
            return None
    return line


def clean_text(raw: str) -> tuple[str, list]:
    """清洗文本，返回(clean_text, page_markers)"""
    lines = raw.split('\n')
    clean_lines = []
    page_markers = []  # [(clean_line_idx, page_num)]

    for i, line in enumerate(lines):
        cleaned = clean_line(line)
        if cleaned is None:
            continue
        # 检测页码标记（纯数字行）
        if re.match(r'^\d{1,4}$', cleaned):
            try:
                pnum = int(cleaned)
                if 1 <= pnum <= 9999:
                    page_markers.append((len(clean_lines), pnum))
                    continue  # 页码行不加入正文
            except:
                pass
        clean_lines.append(cleaned)

    return '\n'.join(clean_lines), page_markers


def split_into_chapters(text: str, book_name: str) -> list[Chapter]:
    """章节感知分段 - 优先识别真正的章节边界，合并页眉碎片"""

    # 强章节边界：CHAPTER N / PART N / 第N章（出现在行首且独占一行）
    strong_patterns = [
        r'^(CHAPTER\s+\d+\b.*)',
        r'^(PART\s+(?:[IVX]+|\d+)\b.*)',
        r'^(第[一二三四五六七八九十百\d]+章.*)',
        r'^(Introduction\s*$)',
        r'^(Acknowledgments\s*$)',
    ]

    # 弱边界（页眉类，需要合并）- 不作为新章节
    header_patterns = [
        r'^(INTRODUCTION\s*$)',
        r'^(LIST OF TERMS.*)',
        r'^(PRICE ACTION\s*$)',
        r'^(TREND LINES.*)',
        r'^(COMMON TREND.*)',
        r'^(CONTENTS\s*$)',
    ]

    lines = text.split('\n')
    chapters = []
    current_title = "序言"
    current_lines = []
    current_start = 0
    chapter_num = 0
    last_strong_boundary = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            current_lines.append(line)
            continue

        # 检查是否是页眉（跳过，不作为边界）
        is_header = any(re.match(p, stripped, re.IGNORECASE) for p in header_patterns)
        if is_header:
            current_lines.append(line)
            continue

        # 检查强章节边界
        is_strong = False
        matched_title = None
        for pat in strong_patterns:
            m = re.match(pat, stripped, re.IGNORECASE)
            if m:
                # 确认是独立行（前后有换行或内容很短）
                if len(stripped) < 80:
                    is_strong = True
                    matched_title = stripped
                    break

        if is_strong and i - last_strong_boundary > 5:  # 避免连续误判
            text_block = '\n'.join(current_lines)
            if len(text_block.strip()) > 300:
                chapter_num += 1
                chapters.append(Chapter(
                    chapter_id=f"CH{chapter_num:03d}",
                    title=current_title,
                    pages=[],
                    text=text_block,
                    line_start=current_start,
                    line_end=i - 1
                ))
            current_title = matched_title
            current_lines = []
            current_start = i
            last_strong_boundary = i
        else:
            current_lines.append(line)

    # 最后一章
    if current_lines:
        text_block = '\n'.join(current_lines)
        if len(text_block.strip()) > 300:
            chapter_num += 1
            chapters.append(Chapter(
                chapter_id=f"CH{chapter_num:03d}",
                title=current_title,
                pages=[],
                text=text_block,
                line_start=current_start,
                line_end=len(lines) - 1
            ))

    # 如果章节过少（<3），说明边界没识别到，降级为按大小切分
    if len(chapters) < 3:
        print("  ⚠️  章节边界识别不足，降级为大小切分...")
        return _size_based_split(text)

    return chapters


def _size_based_split(text: str, chunk_size: int = 8000) -> list[Chapter]:
    """降级方案：按大小切分"""
    chunks = []
    start = 0
    chunk_num = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # 找段落边界
        if end < len(text):
            newline = text.rfind('\n\n', start, end)
            if newline > start + chunk_size // 2:
                end = newline
        chunk_num += 1
        chunks.append(Chapter(
            chapter_id=f"CH{chunk_num:03d}",
            title=f"段落 {chunk_num}",
            pages=[],
            text=text[start:end],
            line_start=0,
            line_end=0
        ))
        start = end
    return chunks


def build_extraction_prompt(chapter: Chapter, book_name: str, book_type: str) -> str:
    cfg = BOOK_CONFIGS[book_type]
    modules_str = ", ".join(cfg["modules"])

    # 截取章节文本（避免超token）— 12000字符 ≈ 4000 token 中文
    max_text = 12000
    text_sample = chapter.text[:max_text] if len(chapter.text) > max_text else chapter.text

    return f"""从以下交易书籍章节中提取知识卡，严格按JSON格式输出。

书名：{book_name}
章节：{chapter.title} ({chapter.chapter_id})
领域：{cfg['domain']}
可用系统模块：{modules_str}

━━━ 章节文本 ━━━
{text_sample}
━━━━━━━━━━━━━━━

要求：
1. 提取 1-{MAX_CARDS_PER_CHAPTER} 张知识卡，只提取有实质交易内容的概念
2. 如果本章节是目录/版权/致谢/索引等，返回：{{"cards": []}}
3. summary必须 <=50字（中文）
4. atomic_claims的evidence格式：从文本推断页码，引用原文关键句
5. rules必须是可执行的IF/THEN交易规则
6. 类型从以下选择：RULE|CONCEPT|PATTERN|STRATEGY|WARNING|PARAM
7. confidence基于证据质量：0.6-0.9之间

输出格式（纯JSON，无Markdown）：
{{
  "cards": [
    {{
      "type": "CONCEPT",
      "title": "概念英文名 / 中文名",
      "confidence": 0.75,
      "content": {{
        "summary": "<=50字的核心定义",
        "detail": "详细解释",
        "formula": "",
        "conditions": ["条件1", "条件2"]
      }},
      "atomic_claims": [
        {{
          "claim": "具体断言",
          "evidence": "P.xx: 原文关键句",
          "context": "上下文说明",
          "invalidation": "何种情况下此断言无效"
        }}
      ],
      "rules": [
        {{
          "if": "触发条件",
          "then": "交易动作",
          "confirm": "确认信号",
          "invalidate": "失效条件",
          "risk": "风险说明",
          "environment": "适用市场环境"
        }}
      ],
      "numeric_thresholds": [
        {{"param": "参数名", "value": "具体数值", "page": 0, "note": "说明"}}
      ],
      "system_mapping": {{
        "module": "模块名（必填）",
        "function": "具体函数/功能",
        "field": "对应字段名",
        "integration": "集成说明",
        "implemented": false
      }}
    }}
  ]
}}"""


def parse_cards_from_response(response_text: str, chapter: Chapter,
                               book_name: str, book_type: str) -> list[KnowledgeCard]:
    """解析DeepSeek返回的JSON"""
    # 清理Markdown代码块
    text = re.sub(r'```json\s*', '', response_text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    try:
        data = json.loads(text)
        raw_cards = data.get("cards", [])
    except json.JSONDecodeError as e:
        # 尝试提取JSON部分
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                raw_cards = data.get("cards", [])
            except:
                print(f"    ⚠️  JSON解析失败: {e}")
                return []
        else:
            print(f"    ⚠️  无法提取JSON")
            return []

    cards = []
    for raw in raw_cards:
        if not raw.get("title") or not raw.get("content", {}).get("summary"):
            continue

        card_id = f"CARD-{chapter.chapter_id}-{str(uuid.uuid4())[:6].upper()}"

        card = KnowledgeCard(
            id=card_id,
            type=raw.get("type", "CONCEPT"),
            title=raw.get("title", ""),
            quality="draft",
            confidence=float(raw.get("confidence", 0.6)),
            content=raw.get("content", {}),
            atomic_claims=raw.get("atomic_claims", []),
            rules=raw.get("rules", []),
            numeric_thresholds=raw.get("numeric_thresholds", []),
            source={
                "book": book_name,
                "chapter": re.sub(r'\t.*$', '', chapter.title).strip(),
                "pages": chapter.pages if chapter.pages else [chapter.line_start, chapter.line_end]
            },
            system_mapping=raw.get("system_mapping", {"module": "", "implemented": False}),
            related_cards=[]
        )

        # 质量门控
        quality, failures = card.quality_check()
        card.quality = quality
        if failures:
            print(f"    ⚡ {card.title[:30]} → draft ({'; '.join(failures)})")

        cards.append(card)

    return cards


def card_to_markdown(card: KnowledgeCard) -> str:
    """转换为MD格式"""
    lines = [
        f"# {card.title}",
        f"",
        f"**ID:** `{card.id}`  ",
        f"**类型:** {card.type} | **质量:** {card.quality} | **置信度:** {card.confidence:.0%}  ",
        f"**来源:** {card.source.get('book', '')} — {card.source.get('chapter', '')}",
        f"",
        f"## 摘要",
        f"{card.content.get('summary', '')}",
        f"",
        f"## 详述",
        f"{card.content.get('detail', '')}",
        f"",
    ]

    if card.content.get("conditions"):
        lines += ["## 触发条件", ""]
        for c in card.content["conditions"]:
            lines.append(f"- {c}")
        lines.append("")

    if card.atomic_claims:
        lines += ["## 原子断言", ""]
        for i, ac in enumerate(card.atomic_claims, 1):
            lines += [
                f"**{i}. {ac.get('claim', '')}**  ",
                f"> 证据: {ac.get('evidence', '')}  ",
                f"> 失效: {ac.get('invalidation', '')}",
                ""
            ]

    if card.rules:
        lines += ["## 交易规则", ""]
        for i, r in enumerate(card.rules, 1):
            lines += [
                f"**规则 {i}**",
                f"- **IF:** {r.get('if', '')}",
                f"- **THEN:** {r.get('then', '')}",
                f"- **确认:** {r.get('confirm', '')}",
                f"- **失效:** {r.get('invalidate', '')}",
                f"- **风险:** {r.get('risk', '')}",
                f"- **环境:** {r.get('environment', '')}",
                ""
            ]

    if card.numeric_thresholds:
        lines += ["## 数值参数", ""]
        for t in card.numeric_thresholds:
            lines.append(f"- **{t.get('param', '')}:** {t.get('value', '')} (P.{t.get('page', '?')}) — {t.get('note', '')}")
        lines.append("")

    sm = card.system_mapping
    if sm.get("module"):
        lines += [
            "## 系统映射",
            f"- **模块:** {sm.get('module', '')}",
            f"- **功能:** {sm.get('function', '')}",
            f"- **字段:** {sm.get('field', '')}",
            f"- **集成:** {sm.get('integration', '')}",
            f"- **已实现:** {'✅' if sm.get('implemented') else '❌'}",
            ""
        ]

    return '\n'.join(lines)


def generate_acceptance_report(cards: list[KnowledgeCard], book_name: str) -> str:
    """生成验收统计报告"""
    total = len(cards)
    if total == 0:
        return "## 验收报告\n\n❌ 未生成任何卡片"

    has_evidence = sum(1 for c in cards if any(
        a.get("evidence") and a["evidence"] not in ("待补充", "")
        for a in c.atomic_claims
    ))
    has_rules = sum(1 for c in cards if any(
        r.get("if") and r.get("then") for r in c.rules
    ))
    has_module = sum(1 for c in cards if c.system_mapping.get("module"))
    quality_dist = {}
    for c in cards:
        quality_dist[c.quality] = quality_dist.get(c.quality, 0) + 1
    type_dist = {}
    for c in cards:
        type_dist[c.type] = type_dist.get(c.type, 0) + 1

    evidence_rate = has_evidence / total
    rule_rate = has_rules / total
    module_rate = has_module / total

    total_ok = TARGET_TOTAL_CARDS[0] <= total <= TARGET_TOTAL_CARDS[1]
    ev_ok = evidence_rate >= EVIDENCE_RATE_TARGET
    rule_ok = rule_rate >= RULE_RATE_TARGET
    mod_ok = module_rate >= MODULE_RATE_TARGET

    status = "✅ 通过" if (total_ok and ev_ok and rule_ok and mod_ok) else "⚠️ 部分未达标"

    lines = [
        f"# 验收报告 — {book_name}",
        f"",
        f"## 总体状态: {status}",
        f"",
        f"| 指标 | 结果 | 目标 | 状态 |",
        f"|------|------|------|------|",
        f"| 卡片总数 | {total} | {TARGET_TOTAL_CARDS[0]}-{TARGET_TOTAL_CARDS[1]} | {'✅' if total_ok else '❌'} |",
        f"| 有Evidence占比 | {evidence_rate:.0%} | ≥{EVIDENCE_RATE_TARGET:.0%} | {'✅' if ev_ok else '❌'} |",
        f"| 有有效规则占比 | {rule_rate:.0%} | ≥{RULE_RATE_TARGET:.0%} | {'✅' if rule_ok else '❌'} |",
        f"| 模块映射非空占比 | {module_rate:.0%} | ≥{MODULE_RATE_TARGET:.0%} | {'✅' if mod_ok else '❌'} |",
        f"",
        f"## 质量分布",
        f"",
    ]
    for q, cnt in sorted(quality_dist.items()):
        lines.append(f"- **{q}:** {cnt} 张 ({cnt/total:.0%})")

    lines += ["", "## 类型分布", ""]
    for t, cnt in sorted(type_dist.items(), key=lambda x: -x[1]):
        lines.append(f"- **{t}:** {cnt} 张")

    return '\n'.join(lines)


def process_book(txt_path: str, book_name: str = None, output_base: str = None,
                 md_dir: str = None):
    """主处理函数
    txt_path: ABBYY txt 文件路径（传统模式）
    md_dir:   OCR page_*.md 目录路径（新模式，优先于 txt_path）
    """
    input_path = Path(md_dir) if md_dir else Path(txt_path)
    if not book_name:
        book_name = input_path.stem if not md_dir else input_path.name

    # 输出目录结构（v3规范）
    if not output_base:
        output_base = input_path.parent / 'output' if not md_dir else input_path.parent
    output_dir = Path(output_base) / book_name
    cards_dir = output_dir / '最终知识卡'
    charts_dir = output_dir / '引用图片'

    # 清理旧产物（只删子目录，保留 page_*.md 输入文件）
    if cards_dir.exists():
        shutil.rmtree(cards_dir, ignore_errors=True)
    if charts_dir.exists():
        shutil.rmtree(charts_dir, ignore_errors=True)
    cards_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f'📚 {book_name}')
    print(f"{'='*60}")

    # 读取 — 两种输入源
    if md_dir:
        print('📖 从 OCR page_*.md 目录读取...')
        raw = load_from_md_dir(Path(md_dir))
    else:
        print('📖 读取 txt 文件...')
        try:
            raw = Path(txt_path).read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            raw = Path(txt_path).read_text(encoding='gbk', errors='ignore')
    # 清洗
    print("🧹 清洗OCR噪音...")
    text, page_markers = clean_text(raw)
    print(f"   字符数: {len(raw):,} → {len(text):,}")

    # 识别书籍类型
    book_type = detect_book_type(book_name, text[:1000])
    print(f"📂 书籍类型: {book_type}")

    # 章节分段
    print("✂️  章节感知分段...")
    chapters = split_into_chapters(text, book_name)
    print(f"   共 {len(chapters)} 个章节")
    for ch in chapters:
        print(f"   [{ch.chapter_id}] {ch.title[:50]} ({len(ch.text):,}字符)")

    # 过滤无实质内容的章节
    skip_titles = ['acknowledgment', '致谢', 'list of terms', 'index', 'about the']
    valid_chapters = [
        ch for ch in chapters
        if not any(s in ch.title.lower() for s in skip_titles)
        and len(ch.text) > 500
    ]
    print(f"\n🎯 有效章节: {len(valid_chapters)} 个（跳过 {len(chapters)-len(valid_chapters)} 个）")

    # DeepSeek客户端
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    cfg = BOOK_CONFIGS[book_type]

    # 逐章提取
    all_cards = []
    print(f"\n🤖 开始提取知识卡...")

    for ch in valid_chapters:
        print(f"\n  [{ch.chapter_id}] {ch.title[:45]}...")
        prompt = build_extraction_prompt(ch, book_name, book_type)

        cards = None
        for attempt in range(2):  # max 2 attempts
            tok = 8000 if attempt == 0 else 12000
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": cfg["system_prompt"]},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=tok,
                    temperature=0.2
                )
                result = response.choices[0].message.content.strip()
                cards = parse_cards_from_response(result, ch, book_name, book_type)

                if cards:
                    break  # success
                elif attempt == 0 and len(result) > 500:
                    # API returned content but parse failed (likely JSON truncation)
                    print(f"    ↻  重试 (max_tokens {tok}→{12000})...")
                    time.sleep(1)
                    continue
                else:
                    break  # truly empty or second attempt

            except Exception as e:
                print(f"  ❌ API错误: {e}")
                if attempt == 0:
                    print(f"    ↻  重试...")
                    time.sleep(2)
                    continue
                break

        if cards:
            print(f"  ✅ {len(cards)} 张卡片")
            all_cards.extend(cards)
            for card in cards:
                safe_title = re.sub(r'[^\w\s-]', '', card.title)[:40]
                md_path = cards_dir / f"{card.id}.md"
                json_path = cards_dir / f"{card.id}.json"
                md_path.write_text(card_to_markdown(card), encoding='utf-8')
                json_path.write_text(
                    json.dumps(card.to_dict(), ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
        else:
            print(f"  ⏭️  跳过（无实质内容）")

        time.sleep(0.8)  # 避免限流

    # 自动关联 related_cards（同模块或同类型的卡片互相关联）
    print(f"\n🔗 建立卡片关联...")
    module_index = {}  # module -> [card_id]
    type_index = {}    # type -> [card_id]
    for c in all_cards:
        m = c.system_mapping.get("module", "")
        if m:
            module_index.setdefault(m, []).append(c.id)
        type_index.setdefault(c.type, []).append(c.id)

    for c in all_cards:
        related = set()
        m = c.system_mapping.get("module", "")
        if m:
            for rid in module_index.get(m, []):
                if rid != c.id:
                    related.add(rid)
        for rid in type_index.get(c.type, []):
            if rid != c.id and len(related) < 5:
                related.add(rid)
        c.related_cards = list(related)[:5]
        # 更新已写入的JSON文件
        json_path = cards_dir / f"{c.id}.json"
        if json_path.exists():
            json_path.write_text(
                json.dumps(c.to_dict(), ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
    print(f"   完成，平均关联 {sum(len(c.related_cards) for c in all_cards)/max(len(all_cards),1):.1f} 张/卡")

    # 验收报告
    print(f"\n{'='*60}")
    print(f"📊 生成验收报告...")
    report = generate_acceptance_report(all_cards, book_name)
    report_path = output_dir / "验收报告.md"
    report_path.write_text(report, encoding='utf-8')
    print(report)

    # 输出汇总
    print(f"\n{'='*60}")
    print(f"✨ 完成!")
    print(f"   知识卡: {len(all_cards)} 张 → {cards_dir}")
    print(f"   引用图片目录: {charts_dir}")
    print(f"   验收报告: {report_path}")

    return str(output_dir)


if __name__ == "__main__":
    import argparse as _ap
    _parser = _ap.ArgumentParser(
        description='Knowledge card extractor v3 - supports OCR page_*.md dir or ABBYY txt')
    _parser.add_argument('input', help='txt file path or page_*.md directory path')
    _parser.add_argument('--book', default=None, help='book name')
    _parser.add_argument('--output', default=None, help='output directory')
    _args = _parser.parse_args()

    if DEEPSEEK_API_KEY == 'your_key_here':
        _key = os.environ.get('DEEPSEEK_API_KEY', '')
        if _key:
            DEEPSEEK_API_KEY = _key
        else:
            _key = input('DeepSeek API Key: ').strip()
            if _key:
                DEEPSEEK_API_KEY = _key

    _input = Path(_args.input)
    if _input.is_dir():
        # OCR page_*.md 目录模式
        process_book(str(_input), _args.book, _args.output, md_dir=str(_input))
    else:
        # 传统 ABBYY txt 模式
        process_book(str(_input), _args.book, _args.output)
