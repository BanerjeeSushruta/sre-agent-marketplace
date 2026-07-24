#!/usr/bin/env python3
import argparse
from pathlib import Path
import fitz

parser = argparse.ArgumentParser(description="Render PDF pages to PNG images for visual review.")
parser.add_argument("pdf")
parser.add_argument("--out-dir", required=True)
parser.add_argument("--dpi", type=int, default=150)
args = parser.parse_args()

out_dir = Path(args.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
doc = fitz.open(args.pdf)
zoom = args.dpi / 72
mat = fitz.Matrix(zoom, zoom)
for i, page in enumerate(doc, start=1):
    pix = page.get_pixmap(matrix=mat, alpha=False)
    out = out_dir / f"page-{i}.png"
    pix.save(out)
    print(out)
