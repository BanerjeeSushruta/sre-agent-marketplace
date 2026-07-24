#!/usr/bin/env python3
"""Validate PNG background usage for generated PDF first and last pages.

Checks:
- First/last background PNGs exist and are valid images.
- Generated first/last pages use the same aspect ratio as the respective PNGs.
- Generated first/last pages visually preserve the background images, allowing overlay text.
- Generated first/last pages include extractable overlay/report content.
"""
import argparse
import json
from pathlib import Path
import fitz
from PIL import Image, ImageChops


def render_page(doc: fitz.Document, page_index: int, dpi: int = 100) -> Image.Image:
    zoom = dpi / 72
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def load_bg(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    return img


def visual_preservation_score(background_img: Image.Image, generated_img: Image.Image) -> float:
    if background_img.size != generated_img.size:
        background_img = background_img.resize(generated_img.size)
    diff = ImageChops.difference(background_img, generated_img).convert("L")
    hist = diff.histogram()
    total = generated_img.size[0] * generated_img.size[1]
    unchanged = sum(hist[:16])
    return unchanged / total if total else 0.0


def aspect_ratio_from_image(img: Image.Image) -> float:
    return round(img.size[0] / img.size[1], 4)


def aspect_ratio_from_page(page: fitz.Page) -> float:
    rect = page.rect
    return round(rect.width / rect.height, 4)


def main():
    parser = argparse.ArgumentParser(description="Validate first/last page PNG background usage.")
    parser.add_argument("generated_pdf")
    parser.add_argument("--first-background", required=True)
    parser.add_argument("--last-background", required=True)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--min-preservation-score", type=float, default=0.82)
    args = parser.parse_args()

    generated_pdf = Path(args.generated_pdf)
    first_bg_path = Path(args.first_background)
    last_bg_path = Path(args.last_background)
    errors = []
    warnings = []
    details = {}

    try:
        if not generated_pdf.exists() or generated_pdf.stat().st_size == 0:
            raise RuntimeError("Generated PDF is missing or empty.")
        for bg in [first_bg_path, last_bg_path]:
            if not bg.exists() or bg.stat().st_size == 0:
                raise RuntimeError(f"Background image missing or empty: {bg}")
        doc = fitz.open(generated_pdf)
        if doc.page_count < 2:
            raise RuntimeError("Generated PDF must contain at least two pages.")
        checks = [
            ("first", first_bg_path, 0),
            ("last", last_bg_path, doc.page_count - 1),
        ]
        for label, bg_path, page_index in checks:
            bg_img = load_bg(bg_path)
            gen_page = doc[page_index]
            gen_img = render_page(doc, page_index)
            bg_ratio = aspect_ratio_from_image(bg_img)
            page_ratio = aspect_ratio_from_page(gen_page)
            ratio_match = abs(bg_ratio - page_ratio) <= 0.01
            if not ratio_match:
                errors.append(f"{label.title()} page aspect ratio mismatch. Background={bg_ratio}, generated={page_ratio}.")
            score = visual_preservation_score(bg_img, gen_img)
            if score < args.min_preservation_score:
                errors.append(f"{label.title()} background preservation score too low: {score:.3f}.")
            text = gen_page.get_text("text").strip()
            if len(text) < 10:
                errors.append(f"{label.title()} page does not contain enough extractable overlay content.")
            details[label] = {
                "background_image": str(bg_path),
                "generated_page_index": page_index + 1,
                "background_size_px": bg_img.size,
                "generated_page_size_pt": [round(gen_page.rect.width, 2), round(gen_page.rect.height, 2)],
                "background_aspect_ratio": bg_ratio,
                "generated_page_aspect_ratio": page_ratio,
                "aspect_ratio_match": ratio_match,
                "background_preservation_score": round(score, 4),
                "overlay_text_character_count": len(text),
                "overlay_text_present": len(text) >= 10,
            }
    except Exception as exc:
        errors.append(str(exc))

    result = {
        "status": "success" if not errors else "failed",
        "generated_pdf": str(generated_pdf),
        "background_usage_valid": not errors,
        "background_content_preserved": not errors,
        "first_and_last_pages_have_content": not errors,
        "details": details,
        "warnings": warnings,
        "errors": errors,
    }
    if args.summary:
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
