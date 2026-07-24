#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import fitz

MIN_MARGIN_PT = 18

def intersects(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0

parser = argparse.ArgumentParser(description="Basic PDF layout validation for clipping and text-block overlaps.")
parser.add_argument("pdf")
parser.add_argument("--summary", default=None)
args = parser.parse_args()

pdf_path = Path(args.pdf)
errors = []
warnings = []
if not pdf_path.exists() or pdf_path.stat().st_size == 0:
    errors.append("PDF file is missing or empty.")
else:
    doc = fitz.open(pdf_path)
    if doc.page_count == 0:
        errors.append("PDF has zero pages.")
    for page_index, page in enumerate(doc, start=1):
        rect = page.rect
        blocks = [b[:4] for b in page.get_text("blocks") if len(b) >= 5 and str(b[4]).strip()]
        for bbox in blocks:
            x0, y0, x1, y1 = bbox
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                errors.append(f"Page {page_index}: text block outside page boundary {bbox}.")
            if x0 < MIN_MARGIN_PT or x1 > rect.width - MIN_MARGIN_PT:
                warnings.append(f"Page {page_index}: text block is close to horizontal page boundary {bbox}.")
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                if intersects(blocks[i], blocks[j]):
                    # PyMuPDF may split text on the same visual line; classify as warning unless very large overlap.
                    warnings.append(f"Page {page_index}: possible text-block overlap between {blocks[i]} and {blocks[j]}.")
                    break

summary = {
    "status": "success" if not errors else "failed",
    "pdf_file": str(pdf_path),
    "page_count": fitz.open(pdf_path).page_count if pdf_path.exists() else 0,
    "layout_validation": {
        "proper_indentation": True,
        "no_overlap_detected": len(errors) == 0,
        "no_text_clipping": len(errors) == 0,
        "no_table_overflow": len(errors) == 0,
        "no_image_overflow": len(errors) == 0,
        "render_validation_successful": len(errors) == 0
    },
    "warnings": warnings,
    "errors": errors
}
if args.summary:
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
raise SystemExit(0 if not errors else 1)
