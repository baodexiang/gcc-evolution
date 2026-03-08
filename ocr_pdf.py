#!/usr/bin/env python3
"""Windows-friendly PDF -> markdown/json/db OCR pipeline.

Flow:
  1. For each PDF page, try direct text extraction via PyMuPDF.
  2. If text is too short, render the page to PNG and run OCR.
  3. Optionally run OPENCODE_JSON_CMD to create page_*.json files.
  4. Optionally load json files into DuckDB via load_db.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType


DEFAULT_DPI = 300
DEFAULT_TIMEOUT = 120
DEFAULT_MIN_TEXT_CHARS = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _display_text(value: object) -> str:
    text = str(value)
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except Exception:
        return text.encode("ascii", errors="backslashreplace").decode("ascii")


def _load_local_module(filename: str, module_name: str) -> ModuleType:
    script_dir = Path(__file__).resolve().parent
    module_path = script_dir / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _append_error(error_log: Path, code: str, detail: str) -> None:
    error_log.parent.mkdir(parents=True, exist_ok=True)
    with error_log.open("a", encoding="utf-8") as fh:
        fh.write(f"{_utc_now()} {code} {detail}\n")


def _extract_page_text(page) -> str:
    text = page.get_text("text") or ""
    return text.strip()


def _render_page_png_with_fitz(page, out_path: Path, dpi: int) -> None:
    pix = page.get_pixmap(dpi=dpi)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path))


def _run_json_hook(md_path: Path, json_path: Path, error_log: Path) -> bool:
    template = os.environ.get("OPENCODE_JSON_CMD", "").strip()
    if not template:
        return False

    cmd = template.replace("{md}", str(md_path)).replace("{json}", str(json_path))
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or str(md_path)
        _append_error(error_log, "JSON_GEN_FAILED", detail)
        return False

    try:
        json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _append_error(error_log, "JSON_INVALID", f"{json_path} ({exc})")
        return False
    return True


def _load_db(work_dir: Path, source_pdf: Path, db_path: Path, error_log: Path) -> bool:
    script_dir = Path(__file__).resolve().parent
    cmd = [
        sys.executable,
        str(script_dir / "load_db.py"),
        str(work_dir),
        str(source_pdf),
        "--db",
        str(db_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or str(db_path)
        _append_error(error_log, "LOAD_DB_FAILED", detail)
        return False
    if proc.stdout.strip():
        print(proc.stdout.strip())
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCR one PDF into page markdown files on Windows")
    parser.add_argument("input_pdf", type=Path, help="Input PDF path")
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("output_md"), help="Output directory")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Page render DPI")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-page OCR timeout in seconds")
    parser.add_argument("--model", default="FireRedTeam/FireRed-OCR", help="FireRed model id")
    parser.add_argument("--firered-repo", type=Path, default=None, help="Local FireRed repo path")
    parser.add_argument("--strict-firered", action="store_true", help="Disable pytesseract fallback")
    parser.add_argument("--min-text-chars", type=int, default=DEFAULT_MIN_TEXT_CHARS, help="Minimum direct text length")
    parser.add_argument("--db", type=Path, default=Path("knowledge.duckdb"), help="DuckDB file")
    parser.add_argument("--skip-db", action="store_true", help="Skip loading page json into DuckDB")
    parser.add_argument("--keep-images", action="store_true", help="Keep rendered page PNG files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input_pdf.exists():
        raise FileNotFoundError(f"input pdf not found: {args.input_pdf}")

    ocr_module = _load_local_module("ocr.py", "gcc_ocr")
    output_dir = args.output_dir.resolve()
    tmp_dir = output_dir / ".tmp_pages"
    error_log = output_dir / "error.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    error_log.write_text("", encoding="utf-8")

    direct_pages = 0
    ocr_pages = 0
    json_pages = 0

    try:
        import fitz
    except Exception as exc:
        raise RuntimeError(f"PyMuPDF (fitz) is required for Windows OCR pipeline: {exc}") from exc

    doc = fitz.open(str(args.input_pdf))
    try:
        for idx, page in enumerate(doc):
            base = f"page_{idx}"
            md_path = output_dir / f"{base}.md"
            json_path = output_dir / f"{base}.json"
            try:
                text = _extract_page_text(page)
                if len(text) >= args.min_text_chars:
                    md_path.write_text(text + "\n", encoding="utf-8")
                    direct_pages += 1
                else:
                    img_path = tmp_dir / f"{base}.png"
                    _render_page_png_with_fitz(page, img_path, dpi=args.dpi)
                    text = ocr_module.run_ocr(
                        image_path=img_path,
                        model_id=args.model,
                        timeout_sec=args.timeout,
                        firered_repo=args.firered_repo,
                        allow_fallback=not args.strict_firered,
                    )
                    md_path.write_text((text if text else "[EMPTY OCR RESULT]") + "\n", encoding="utf-8")
                    ocr_pages += 1
                if _run_json_hook(md_path, json_path, error_log):
                    json_pages += 1
            except Exception as exc:
                _append_error(error_log, "PAGE_FAILED", f"page_{idx} ({exc})")
    finally:
        doc.close()

    if not args.keep_images:
        for img_path in tmp_dir.glob("page_*.png"):
            img_path.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    if not args.skip_db and any(output_dir.glob("page_*.json")):
        _load_db(output_dir, args.input_pdf, args.db, error_log)

    print(f"Done: {_display_text(args.input_pdf)} -> {_display_text(output_dir)}")
    print(f"Pages: direct_text={direct_pages} ocr={ocr_pages} json={json_pages}")
    if error_log.exists() and error_log.stat().st_size > 0:
        print(f"Some pages failed. See: {_display_text(error_log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
