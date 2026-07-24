#!/usr/bin/env python3
"""Validate that generated PDF uses and preserves attached template pages.

Checks:
- Template source exists and has at least two pages after optional DOCX conversion.
- Generated PDF first page has same page size as template first page.
- Generated PDF last page has same page size as template last page.
- Template visual content is preserved on first and last page, allowing overlay text.
- First and last generated pages contain extractable overlay/report content.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import fitz
from PIL import Image, ImageChops


def convert_docx_to_pdf(template_path: Path, work_dir: Path) -> Path:
    out_dir = work_dir / "template_pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "soffice", "--headless", "--nologo", "--nolockcheck",
        "--convert-to", "pdf", "--outdir", str(out_dir), str(template_path)
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    converted = out_dir / f"{template_path.stem}.pdf"
    if not converted.exists() or converted.stat().st_size == 0:
        raise RuntimeError(f"Template DOCX conversion failed. stdout={proc.stdout} stderr={proc.stderr}")
    return converted


def resolve_template_pdf(template_path: Path, work_dir: Path) -> Path:
    suffix = template_path.suffix.lower()
    if suffix == ".pdf":
        return template_path
    if suffix == ".docx":
        return convert_docx_to_pdf(template_path, work_dir)
    raise RuntimeError(f"Unsupported template format: {suffix}")


def render_page(doc: fitz.Document, page_index: int, dpi: int = 100) -> Image.Image:
    zoom = dpi / 72
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def visual_preservation_score(template_img: Image.Image, generated_img: Image.Image) -> float:
    if template_img.size != generated_img.size:
        generated_img = generated_img.resize(template_img.size)
    diff = ImageChops.difference(template_img, generated_img).convert("L")
    hist = diff.histogram()
    total = template_img.size[0] * template_img.size[1]
    # Treat small antialiasing/color conversion changes as preserved.
    unchanged = sum(hist[:16])
    return unchanged / total if total else 0.0


def page_size_tuple(page: fitz.Page):
    rect = page.rect
    return (round(rect.width, 2), round(rect.height, 2))


def main():
    parser = argparse.ArgumentParser(description="Validate template first/last page usage and content preservation.")
    parser.add_argument("generated_pdf")
    parser.add_argument("--template", required=True, help="Template source file, DOCX or PDF")
    parser.add_argument("--summary", default=None)
    parser.add_argument("--min-preservation-score", type=float, default=0.82)
    args = parser.parse_args()

    generated_pdf = Path(args.generated_pdf)
    template_source = Path(args.template)
    errors = []
    warnings = []
    details = {}

    try:
        if not generated_pdf.exists() or generated_pdf.stat().st_size == 0:
            raise RuntimeError("Generated PDF is missing or empty.")
        if not template_source.exists() or template_source.stat().st_size == 0:
            raise RuntimeError("Template source is missing or empty.")
        with tempfile.TemporaryDirectory() as tmp:
            template_pdf = resolve_template_pdf(template_source, Path(tmp))
            template_doc = fitz.open(template_pdf)
            generated_doc = fitz.open(generated_pdf)
            if template_doc.page_count < 2:
                errors.append("Template must contain at least two pages.")
            if generated_doc.page_count < 2:
                errors.append("Generated PDF must contain at least two pages.")
            if not errors:
                mapping = [
                    ("first", 0, 0),
                    ("last", template_doc.page_count - 1, generated_doc.page_count - 1),
                ]
                for label, template_index, generated_index in mapping:
                    template_page = template_doc[template_index]
                    generated_page = generated_doc[generated_index]
                    template_size = page_size_tuple(template_page)
                    generated_size = page_size_tuple(generated_page)
                    size_match = template_size == generated_size
                    if not size_match:
                        errors.append(f"{label.title()} page size mismatch. Template={template_size}, generated={generated_size}.")
                    template_img = render_page(template_doc, template_index)
                    generated_img = render_page(generated_doc, generated_index)
                    score = visual_preservation_score(template_img, generated_img)
                    if score < args.min_preservation_score:
                        errors.append(f"{label.title()} template preservation score too low: {score:.3f}.")
                    text = generated_page.get_text("text").strip()
                    if len(text) < 10:
                        errors.append(f"{label.title()} page does not contain enough extractable report overlay content.")
                    details[label] = {
                        "template_page_index": template_index + 1,
                        "generated_page_index": generated_index + 1,
                        "template_size": template_size,
                        "generated_size": generated_size,
                        "page_size_match": size_match,
                        "template_preservation_score": round(score, 4),
                        "overlay_text_character_count": len(text),
                        "overlay_text_present": len(text) >= 10,
                    }
    except Exception as exc:
        errors.append(str(exc))

    result = {
        "status": "success" if not errors else "failed",
        "template_source": str(template_source),
        "generated_pdf": str(generated_pdf),
        "template_usage_valid": not errors,
        "template_content_preserved": not errors,
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
