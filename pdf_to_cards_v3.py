#!/usr/bin/env python3
"""Convert OCR page markdown files into structured knowledge-card JSON.

Compatible with load_db.py:
  - title
  - summary
  - key_points
  - tables
  - entities
  - tags

Also emits richer professional card fields used by GCC skill cards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "part",
    "page", "chapter", "section", "using", "when", "then", "than", "into",
    "price", "volume", "market", "method", "system", "trade", "trading",
    "rules", "rule", "analysis", "trend", "entry", "exit",
}

ZH_TAG_HINTS = [
    "仓位", "风险", "交易", "趋势", "突破", "回调", "结构", "成交量", "价格行为",
    "威科夫", "止损", "止盈", "动量", "供需", "震荡", "吸筹", "出货", "情绪",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert page_*.md OCR output into structured card json")
    parser.add_argument("work_dir", type=Path, help="Directory containing page_*.md")
    parser.add_argument("--book", default="", help="Book/course/source name")
    parser.add_argument("--chapter", default="", help="Chapter or topic label")
    parser.add_argument("--module", default="KnowledgeExtractor", help="System mapping module")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing page_*.json")
    parser.add_argument("--refine", action="store_true", help="Refine existing/generated json with stricter noise cleanup")
    parser.add_argument("--llm-refine", action="store_true", help="Use configured GCC LLM to refine the card")
    parser.add_argument("--llm-repeat", type=int, default=1, help="LLM repeat count")
    return parser.parse_args()


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"\s+", " ", line)
        if _is_noise_line(line):
            continue
        lines.append(line)
    return lines


def _is_noise_line(line: str) -> bool:
    compact = line.strip()
    if not compact:
        return True
    if re.fullmatch(r"\d+", compact):
        return True
    if compact.lower() in {"contents", "table of contents", "目录"}:
        return True
    if compact.count(".") >= 8:
        return True
    if re.search(r"\.{5,}\s*\d+$", compact):
        return True
    if re.match(r"^part\s*\d+[.:]?", compact, re.IGNORECASE):
        return False
    if len(compact) <= 3:
        return True
    return False


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s+|\s*;\s*", text)
    return [p.strip(" -•\t") for p in parts if p.strip(" -•\t")]


def _is_heading(line: str) -> bool:
    if line.startswith("#"):
        return True
    if re.match(r"^\d+(\.\d+)*\s+\S+", line):
        return True
    return False


def _derive_title(lines: list[str], page_name: str) -> str:
    for line in lines[:8]:
        candidate = line.lstrip("#").strip()
        if len(candidate) >= 6 and not re.fullmatch(r"\d+", candidate):
            if _looks_like_toc_entry(candidate):
                continue
            if _is_heading(line) or len(candidate) <= 120:
                return _normalize_title(candidate)[:120]
    for line in lines[:20]:
        candidate = line.lstrip("#").strip()
        if len(candidate) >= 12 and not _looks_like_toc_entry(candidate):
            return _normalize_title(candidate)[:120]
    return page_name.replace("_", " ")


def _looks_like_toc_entry(text: str) -> bool:
    if text.count(".") >= 5:
        return True
    if re.search(r"\b\d+\s*$", text):
        return True
    if re.match(r"^\d+(\.\d+)+\s+", text):
        return True
    return False


def _normalize_title(text: str) -> str:
    text = re.sub(r"^\d+(\.\d+)*\s*", "", text).strip()
    text = re.sub(r"\s+\d+$", "", text).strip()
    return text


def _derive_summary(sentences: list[str]) -> str:
    clean = [s for s in sentences if not _looks_like_toc_entry(s) and len(s) >= 18]
    if not clean:
        return ""
    joined = " ".join(clean[:2]).strip()
    return joined[:200]


def _derive_key_points(lines: list[str], sentences: list[str]) -> list[str]:
    points: list[str] = []
    for line in lines:
        if line.startswith(("-", "*", "•")):
            points.append(line.lstrip("-*• ").strip())
    if not points:
        for sent in sentences[:6]:
            if len(sent) >= 18 and not _looks_like_toc_entry(sent):
                points.append(sent)
    dedup: list[str] = []
    seen: set[str] = set()
    for point in points:
        key = point[:120]
        if key not in seen:
            dedup.append(point[:220])
            seen.add(key)
    return dedup[:8]


def _extract_numeric_thresholds(text: str) -> list[dict]:
    results = []
    for match in re.finditer(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|倍|天|周|月|年|根|次|个|笔|小时|分钟)?", text):
        value = match.group("value")
        unit = match.group("unit") or ""
        if len(value) == 1 and unit == "":
            continue
        start = max(0, match.start() - 18)
        end = min(len(text), match.end() + 18)
        context = re.sub(r"\s+", " ", text[start:end]).strip()
        results.append(
            {
                "name": "提取阈值",
                "value": float(value) if "." in value else int(value),
                "unit": unit,
                "context": context[:120],
            }
        )
        if len(results) >= 8:
            break
    return results


def _extract_tags(title: str, text: str) -> list[str]:
    tags: list[str] = []
    haystack = f"{title} {text}"
    for hint in ZH_TAG_HINTS:
        if hint in haystack and hint not in tags:
            tags.append(hint)

    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", haystack.lower())
    counts: dict[str, int] = {}
    for word in words:
        if word in STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    for word, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if word not in tags:
            tags.append(word)
        if len(tags) >= 8:
            break
    return tags[:8]


def _extract_entities(title: str, key_points: list[str], tags: list[str]) -> dict:
    return {
        "topics": tags[:6],
        "headings": [title],
        "key_phrases": key_points[:5],
    }


def _build_atomic_claims(key_points: list[str]) -> list[dict]:
    claims = []
    for point in key_points[:5]:
        claims.append(
            {
                "claim": point,
                "evidence": "来源于 OCR 页面文本摘要",
                "context": "待人工复核",
                "invalidation": "待补充",
            }
        )
    return claims


def _build_rules(key_points: list[str]) -> list[dict]:
    rules = []
    for point in key_points[:3]:
        rules.append(
            {
                "if": "满足文中所述前提",
                "then": point,
                "confirm": "待人工复核",
                "invalidate": "待补充",
                "risk": "需要结合原文校验",
                "environment": "通用",
            }
        )
    return rules


def _build_card(md_path: Path, book: str, chapter: str, module: str) -> dict:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    lines = _clean_lines(text)
    sentences = _sentences(" ".join(lines))

    title = _derive_title(lines, md_path.stem)
    summary = _derive_summary(sentences)
    key_points = _derive_key_points(lines, sentences)
    tags = _extract_tags(title, text)
    entities = _extract_entities(title, key_points, tags)
    numeric_thresholds = _extract_numeric_thresholds(text)
    digest = hashlib.sha1(f"{md_path.resolve()}::{title}".encode("utf-8")).hexdigest()[:6].upper()

    detail = " ".join(sentences[:8]).strip()[:2000]
    return {
        "id": f"CARD-OCR-{digest}",
        "type": "RULE",
        "title": title,
        "quality": "ocr_extracted",
        "confidence": 0.35,
        "summary": summary,
        "key_points": key_points,
        "tables": [],
        "entities": entities,
        "tags": tags,
        "content": {
            "summary": summary,
            "detail": detail,
            "formula": "",
            "conditions": key_points[:4],
        },
        "atomic_claims": _build_atomic_claims(key_points),
        "rules": _build_rules(key_points),
        "numeric_thresholds": numeric_thresholds,
        "source": {
            "book": book,
            "chapter": chapter,
            "pages": [],
            "page_file": md_path.name,
        },
        "system_mapping": {
            "module": module,
            "function": "从 OCR 页面文本提取结构化知识卡字段",
            "field": "title, summary, key_points, tags",
            "integration": "可直接被 load_db.py 导入 cards 表",
            "implemented": False,
        },
    }


def _refine_existing_card(card: dict, md_path: Path, book: str, chapter: str, module: str) -> dict:
    rebuilt = _build_card(md_path, book=book, chapter=chapter, module=module)
    merged = dict(card)
    for field in ["title", "summary", "key_points", "tables", "entities", "tags", "content",
                  "atomic_claims", "rules", "numeric_thresholds", "source", "system_mapping"]:
        merged[field] = rebuilt[field]
    merged["quality"] = "ocr_refined"
    merged["confidence"] = max(float(card.get("confidence", 0.0) or 0.0), 0.45)
    if "id" not in merged or not merged["id"]:
        merged["id"] = rebuilt["id"]
    if "type" not in merged or not merged["type"]:
        merged["type"] = "RULE"
    return merged


def _load_llm_client():
    from gcc_evolution.config import GCCConfig
    from gcc_evolution.llm_client import LLMClient

    cfg = GCCConfig.load()
    if not (cfg.llm_api_key or cfg.llm_provider == "local"):
        raise RuntimeError("LLM not configured. Set GCC_API_KEY or use local provider.")
    return LLMClient(cfg)


def _extract_json_object(text: str) -> dict | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _llm_refine_card(card: dict, md_path: Path, llm, repeat: int) -> dict:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    system = (
        "You are a strict knowledge-card refiner. "
        "Only use facts present in the OCR markdown. "
        "Do not invent evidence. "
        "Return JSON only."
    )
    user = f"""
Refine this OCR-derived professional knowledge card.

Constraints:
- Keep it factual and conservative.
- Remove table-of-contents style noise.
- Produce concise, professional fields.
- If evidence is weak, keep placeholders like "待人工复核" or "待补充".

Return JSON with exactly these fields:
{{
  "title": "...",
  "summary": "...",
  "key_points": ["..."],
  "tags": ["..."],
  "content": {{
    "summary": "...",
    "detail": "...",
    "formula": "",
    "conditions": ["..."]
  }},
  "atomic_claims": [{{"claim":"...","evidence":"...","context":"...","invalidation":"..."}}],
  "rules": [{{"if":"...","then":"...","confirm":"...","invalidate":"...","risk":"...","environment":"..."}}],
  "numeric_thresholds": [{{"name":"...","value":0,"unit":"","context":"..."}}],
  "system_mapping": {{
    "module": "{card.get("system_mapping", {}).get("module", "KnowledgeExtractor")}",
    "function": "...",
    "field": "...",
    "integration": "...",
    "implemented": false
  }},
  "entities": {{"topics":["..."],"headings":["..."],"key_phrases":["..."]}}
}}

Current card draft:
{json.dumps(card, ensure_ascii=False)}

OCR markdown:
{text[:12000]}
"""
    refined = llm.generate(system, user, repeat=repeat, consensus=repeat >= 3)
    payload = _extract_json_object(refined)
    if not payload:
        raise RuntimeError("LLM did not return valid JSON")

    merged = dict(card)
    for field in [
        "title", "summary", "key_points", "tags", "content",
        "atomic_claims", "rules", "numeric_thresholds",
        "system_mapping", "entities",
    ]:
        if field in payload:
            merged[field] = payload[field]
    merged["quality"] = "ocr_llm_refined"
    merged["confidence"] = max(float(card.get("confidence", 0.0) or 0.0), 0.65)
    return merged


def main() -> int:
    args = parse_args()
    if not args.work_dir.exists():
        raise FileNotFoundError(f"work dir not found: {args.work_dir}")

    md_files = sorted(args.work_dir.glob("page_*.md"))
    llm = _load_llm_client() if args.llm_refine else None
    converted = 0
    skipped = 0
    for md_path in md_files:
        json_path = md_path.with_suffix(".json")
        if json_path.exists() and not args.overwrite and not args.refine:
            skipped += 1
            continue
        if json_path.exists() and args.refine:
            try:
                existing = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            card = _refine_existing_card(existing, md_path, book=args.book, chapter=args.chapter, module=args.module)
        else:
            card = _build_card(md_path, book=args.book, chapter=args.chapter, module=args.module)
        if args.llm_refine:
            card = _llm_refine_card(card, md_path, llm=llm, repeat=max(1, args.llm_repeat))
        json_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        converted += 1

    print(f"Converted {converted} markdown pages into card json under {args.work_dir}")
    if skipped:
        print(f"Skipped {skipped} existing json files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
