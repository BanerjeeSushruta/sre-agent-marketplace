#!/usr/bin/env python3
import argparse
from pathlib import Path
from pypdf import PdfReader, PdfWriter

parser = argparse.ArgumentParser(description="Extract first and last pages from a template PDF.")
parser.add_argument("template_pdf")
parser.add_argument("--out-dir", default="templates/extracted")
args = parser.parse_args()

reader = PdfReader(args.template_pdf)
if len(reader.pages) < 2:
    raise SystemExit("Template must contain at least two pages.")
Path(args.out_dir).mkdir(parents=True, exist_ok=True)
for label, index in [("cover", 0), ("closing", len(reader.pages) - 1)]:
    writer = PdfWriter()
    writer.add_page(reader.pages[index])
    out = Path(args.out_dir) / f"{label}.pdf"
    with out.open("wb") as f:
        writer.write(f)
    print(out)
