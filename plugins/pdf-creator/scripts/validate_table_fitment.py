#!/usr/bin/env python3
"""Validate that table data can be fit without word breaks or cell overflow.

The validator mirrors the generation rule: no word breaking is allowed, so every
column must be wide enough for the longest unbreakable token. If the full table
cannot fit on one page, column chunking must be possible. If a single token
cannot fit within the content width even at minimum font size, validation fails.
"""
import argparse
import json
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics

FONT_PAIRS = [(8.4, 8.8), (7.8, 8.2), (7.2, 7.6), (6.6, 7.0), (6.0, 6.4), (5.6, 6.0)]
PADDING = 22

def safe_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def max_word_width(text, font_name, font_size):
    words = re.findall(r"\S+", safe_text(text)) or [""]
    return max(pdfmetrics.stringWidth(word, font_name, font_size) for word in words)

def normalize(columns, rows):
    headers = [safe_text(c) or f"Column {i+1}" for i, c in enumerate(columns or [])]
    expected = len(headers)
    normalized = []
    warnings = []
    for ri, row in enumerate(rows or [], 1):
        source = list(row) if isinstance(row, list) else [row]
        if len(source) < expected:
            warnings.append(f"row {ri} padded from {len(source)} to {expected} cells")
            source += [""] * (expected - len(source))
        elif len(source) > expected:
            warnings.append(f"row {ri} extra cells merged into final column")
            source = source[:expected-1] + [" | ".join(safe_text(x) for x in source[expected-1:])]
        normalized.append([safe_text(x) for x in source])
    return headers, normalized, warnings

def required_width(header, values, cell_font, header_font):
    header_width = max_word_width(header, "Helvetica-Bold", header_font)
    value_width = max((max_word_width(v, "Helvetica", cell_font) for v in values), default=0)
    return max(header_width, value_width) + PADDING

def main():
    parser = argparse.ArgumentParser(description="Validate no-word-break table fitment.")
    parser.add_argument("input_json")
    parser.add_argument("--summary", default=None)
    args = parser.parse_args()

    data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    layout = data.get("layout", {})
    page_size = A4 if layout.get("page_size", "A4") == "A4" else LETTER
    if layout.get("orientation") == "landscape":
        page_size = landscape(page_size)
    content_width = page_size[0] - 1.5 * inch

    errors = []
    warnings = []
    results = []
    for section in data.get("sections", []):
        if section.get("type") != "table":
            continue
        title = section.get("title", section.get("id", "table"))
        headers, rows, norm_warnings = normalize(section.get("columns", []), section.get("rows", []))
        warnings.extend([f"{title}: {w}" for w in norm_warnings])
        if not headers:
            errors.append(f"{title}: no headers available")
            continue
        chosen = None
        for cell_font, header_font in FONT_PAIRS:
            required = []
            for ci, header in enumerate(headers):
                required.append(required_width(header, [row[ci] for row in rows], cell_font, header_font))
            too_wide = [headers[i] for i, width in enumerate(required) if width > content_width]
            if too_wide:
                continue
            chosen = {
                "cell_font": cell_font,
                "header_font": header_font,
                "requires_column_chunking": sum(required) > content_width,
                "required_width_total_points": round(sum(required), 2),
                "content_width_points": round(content_width, 2)
            }
            break
        if not chosen:
            errors.append(f"{title}: at least one unbreakable token cannot fit without word break")
        else:
            results.append({"section": title, **chosen})

    result = {
        "status": "success" if not errors else "failed",
        "no_word_break_fitment_valid": not errors,
        "table_results": results,
        "warnings": warnings,
        "errors": errors
    }
    if args.summary:
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if not errors else 1)

if __name__ == "__main__":
    main()
