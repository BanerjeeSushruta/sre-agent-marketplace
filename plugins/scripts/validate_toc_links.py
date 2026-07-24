#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import fitz

parser = argparse.ArgumentParser(description="Validate that the PDF contains navigable link annotations.")
parser.add_argument("pdf")
args = parser.parse_args()

doc = fitz.open(args.pdf)
link_count = 0
for page in doc:
    link_count += len(page.get_links())
result = {
    "status": "success" if link_count > 0 else "failed",
    "pdf_file": str(Path(args.pdf)),
    "link_annotation_count": link_count,
    "toc_clickable": link_count > 0
}
print(json.dumps(result, indent=2))
raise SystemExit(0 if link_count > 0 else 1)
