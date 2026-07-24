#!/usr/bin/env python3
"""Validate table section structure in Azure SRE PDF input JSON.

This validates that each table has a deterministic header-to-row mapping and
reports whether any normalization would be required before PDF rendering.
"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="Validate table header and row structural consistency.")
parser.add_argument("input_json")
parser.add_argument("--summary", default=None)
args = parser.parse_args()

data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
errors = []
warnings = []
for section in data.get("sections", []):
    if section.get("type") != "table":
        continue
    title = section.get("title", section.get("id", "table"))
    columns = section.get("columns", [])
    rows = section.get("rows", [])
    if not columns:
        errors.append(f"{title}: table has no column headers.")
        continue
    expected = len(columns)
    seen = set()
    for col in columns:
        col_name = str(col).strip().lower()
        if not col_name:
            errors.append(f"{title}: table includes an empty column header.")
        if col_name in seen:
            errors.append(f"{title}: duplicate column header '{col}'.")
        seen.add(col_name)
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, list):
            errors.append(f"{title}: row {index} is not a list.")
            continue
        if len(row) != expected:
            warnings.append(f"{title}: row {index} has {len(row)} cells but header has {expected}; generator will normalize.")

result = {
    "status": "success" if not errors else "failed",
    "table_structure_consistent": not errors,
    "warnings": warnings,
    "errors": errors
}
if args.summary:
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if not errors else 1)
