# Azure SRE Agent PDF Creation Skill

This artifact pack contains a production-oriented skill definition and implementation scaffold for generating enterprise PDF reports using an approved template.

## Key Features

- Uses `templates/template.pdf` first page as the cover page.
- Uses `templates/template.pdf` last page as the closing page.
- Generates free-flowing middle pages.
- Creates a navigable, clickable table of contents.
- Enforces indentation rules.
- Validates no overlap, clipping, broken pages, or missing output.
- Produces validation summaries and render previews.

## Folder Structure

```text
azure-sre-agent-pdf-creation/
├── SKILL.md
├── README.md
├── templates/
│   └── template.pdf
├── schemas/
│   ├── input.schema.json
│   └── output.schema.json
├── scripts/
│   ├── generate_pdf.py
│   ├── extract_template_pages.py
│   ├── validate_layout.py
│   ├── validate_toc_links.py
│   └── render_pdf.py
├── examples/
│   ├── sre_assessment_input.json
│   ├── finops_report_input.json
│   └── remediation_plan_input.json
└── docs/
    ├── IMPLEMENTATION_GUIDE.md
    └── TEST_PLAN.md
```

## Quick Start

Install dependencies in your agent execution environment:

```bash
pip install reportlab pypdf pymupdf jsonschema
```

Generate a sample PDF:

```bash
python scripts/generate_pdf.py examples/sre_assessment_input.json --output out/azure-sre-report.pdf
```

Render the PDF for visual validation:

```bash
python scripts/render_pdf.py out/azure-sre-report.pdf --out-dir out/rendered
```

Validate layout and TOC links:

```bash
python scripts/validate_layout.py out/azure-sre-report.pdf --summary out/validation_summary.json
python scripts/validate_toc_links.py out/azure-sre-report.pdf
```

## Operational Rule

Do not return a generated PDF to the caller unless the validation summary reports success.

## Latest Enhancements

This version adds the following improvements:

- Formatted tables with calculated column widths, styled headers, padding, borders, and alternating row shading.
- Word-boundary wrapping so words are not intentionally split between lines.
- Cover page content overlay on top of the first page of `templates/template.pdf`.
- Closing page content overlay on top of the last page of `templates/template.pdf`.
- Professionally formatted clickable table of contents with section links and visual styling.

## Generated Template Overlay Fields

The cover page overlay includes title, subtitle, generated-by value, reporting period, optional environment, and classification.

The closing page overlay includes a closing message, document title, and classification.

## Table Structural Consistency Fix

This version includes table structure normalization and validation:

- Header count is treated as the authoritative column count.
- Rows with missing cells are padded before rendering.
- Rows with extra cells are merged into the final column without silent data loss.
- Empty or duplicate column headers are detected by `validate_table_structure.py`.
- Generated tables use one calculated width per header to prevent row/header mismatch.
- Tables are rendered with controlled padding and grid lines to avoid visual overlap between rows and columns.

Validate input table structure:

```bash
python scripts/validate_table_structure.py examples/sre_assessment_input.json --summary out/table_structure_summary.json
```

## Strict Table Data Fitment Fix

This version adds a fitment-first table renderer:

- Measures the longest unbreakable token per column before rendering.
- Calculates safe minimum column width using text width, padding, and safety buffer.
- Reduces table font size only within controlled limits.
- Splits very wide tables into sequential column chunks when the complete table cannot safely fit on one page.
- Fails closed if a single unbreakable value cannot fit without breaking the word.
- Keeps words intact and prevents data from overlapping or overflowing cell boundaries.

Validate table fitment without word break:

```bash
python scripts/validate_table_fitment.py examples/sre_assessment_input.json --summary out/table_fitment_summary.json
```

For wide tables, the generator now creates multiple column chunks rather than forcing data into narrow cells.

## Attached DOCX Template Support

The skill now uses `templates/template.docx` as the default report template.

Runtime behavior:

1. Convert `templates/template.docx` to PDF using LibreOffice headless mode.
2. Use the first converted page as the report cover page.
3. Overlay report title, subtitle, generated-by, reporting period, optional environment, and classification on the cover page.
4. Generate all middle pages as free-flowing report content.
5. Use the last converted page as the report closing page.
6. Overlay a closing message, report title, and classification on the closing page.

Existing safeguards remain intact:

- Clickable formatted TOC
- Strict table structure validation
- Strict table fitment validation
- No word break enforcement
- No overlap or overflow validation
- Render validation

## Template Usage Validation

Run the following validation to confirm the attached template is preserved and used correctly:

```bash
python scripts/validate_template_usage.py out/sample_sre_assessment_docx_template.pdf \
  --template templates/template.docx \
  --summary out/template_usage_summary.json
```

The validator confirms that:

- The attached template source exists and is readable.
- DOCX templates are converted to PDF for page comparison.
- The generated first page preserves the template first page.
- The generated last page preserves the template last page.
- Both first and last pages contain generated report content overlays.
- Template page sizes are preserved.

## PNG Background First and Last Page Support

The default report generation mode now uses:

- `templates/Page_1.png` as the first page background.
- `templates/Page_2.png` as the last page background.
- Free-flowing generated pages for all middle report content.

The generated first page includes title, subtitle, generated-by, reporting period, optional environment, and classification overlaid on the background image.

The generated last page includes closing/report completion content, report title, and classification overlaid on the background image.

Validate PNG background usage:

```bash
python scripts/validate_background_usage.py out/sample_sre_assessment_png_background.pdf \
  --first-background templates/Page_1.png \
  --last-background templates/Page_2.png \
  --summary out/background_usage_summary.json
```
