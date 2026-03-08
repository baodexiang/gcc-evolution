#!/usr/bin/env python3
"""Stage-2 OCR: page image -> markdown.

Primary backend: FireRed-OCR (FireRedTeam/FireRed-OCR).
Fallback backend: pytesseract (optional, enabled by default).
"""

from __future__ import annotations

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path


DEFAULT_MODEL = "FireRedTeam/FireRed-OCR"
DEFAULT_TIMEOUT = 120


def _run_firered_repo_infer(image_path: Path, model_id: str, repo_dir: Path) -> str:
    infer_py = repo_dir / "conv_for_infer.py"
    if not infer_py.exists():
        raise FileNotFoundError(f"missing FireRed script: {infer_py}")

    cmd = [
        "python",
        str(infer_py),
        "--image",
        str(image_path),
        "--model",
        model_id,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "FireRed repo infer failed")
    return (proc.stdout or "").strip()


def _run_firered_transformers(image_path: Path, model_id: str) -> str:
    """Run FireRed-OCR via Qwen3-VL transformers API (GPU accelerated).

    FireRed-OCR is based on Qwen3-VL-2B architecture.
    Requires: transformers>=5.0, torch with CUDA, accelerate.
    Images are resized to max 1280px width to fit 8GB VRAM.
    """
    import torch
    from PIL import Image
    from transformers import Qwen3VLForConditionalGeneration, AutoProcessor

    # Load model (float16 on GPU)
    device_map = "auto" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        model_id, torch_dtype=dtype, device_map=device_map
    )
    processor = AutoProcessor.from_pretrained(model_id)

    # Load and resize image to fit VRAM (max 1280px width)
    image = Image.open(image_path).convert("RGB")
    MAX_WIDTH = 1280
    if image.width > MAX_WIDTH:
        ratio = MAX_WIDTH / image.width
        new_h = int(image.height * ratio)
        image = image.resize((MAX_WIDTH, new_h), Image.LANCZOS)

    # Build chat message with image
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": "OCR the text in the image."},
            ],
        }
    ]

    # Process and generate
    text_input = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(
        text=[text_input], images=[image], return_tensors="pt", padding=True
    ).to(model.device)

    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=2048)

    # Decode only the new tokens (skip input tokens)
    generated_ids = output_ids[0][inputs["input_ids"].shape[1]:]
    result = processor.decode(generated_ids, skip_special_tokens=True)
    return result.strip()


def _run_tesseract(image_path: Path) -> str:
    from PIL import Image
    import pytesseract

    image = Image.open(image_path)
    return pytesseract.image_to_string(image, lang="chi_sim+eng").strip()


def run_ocr(
    image_path: Path,
    model_id: str,
    timeout_sec: int,
    firered_repo: Path | None,
    allow_fallback: bool,
) -> str:
    errors: list[str] = []

    def _do_ocr() -> str:
        if firered_repo is not None:
            return _run_firered_repo_infer(image_path, model_id=model_id, repo_dir=firered_repo)
        return _run_firered_transformers(image_path, model_id=model_id)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            text = pool.submit(_do_ocr).result(timeout=timeout_sec)
        if text.strip():
            return text.strip()
        errors.append("FireRed returned empty text")
    except FutureTimeout:
        errors.append(f"FireRed timeout after {timeout_sec}s")
    except Exception as exc:
        errors.append(f"FireRed failed: {exc}")

    if allow_fallback:
        try:
            text = _run_tesseract(image_path)
            if text.strip():
                return text.strip()
            errors.append("Tesseract returned empty text")
        except Exception as exc:
            errors.append(f"Tesseract failed: {exc}")

    raise RuntimeError(" | ".join(errors) if errors else "OCR failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCR one image page to markdown")
    parser.add_argument("input_image", type=Path, help="Input page image path, e.g. page_0.png")
    parser.add_argument("output_md", type=Path, help="Output markdown path, e.g. page_0.md")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="FireRed model id")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-page timeout in seconds")
    parser.add_argument(
        "--firered-repo",
        type=Path,
        default=None,
        help="Path to cloned FireRed-OCR repo (uses conv_for_infer.py when provided)",
    )
    parser.add_argument(
        "--strict-firered",
        action="store_true",
        help="Disable pytesseract fallback; fail if FireRed cannot produce output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input_image.exists():
        raise FileNotFoundError(f"input image not found: {args.input_image}")

    text = run_ocr(
        image_path=args.input_image,
        model_id=args.model,
        timeout_sec=args.timeout,
        firered_repo=args.firered_repo,
        allow_fallback=not args.strict_firered,
    )

    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text((text if text else "[EMPTY OCR RESULT]") + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
