# Test Plan

## Test Case 1: Generate SRE Assessment Report

Command:

```bash
python scripts/generate_pdf.py examples/sre_assessment_input.json --output out/sre_assessment.pdf
```

Expected result:

- PDF created successfully.
- First page matches template cover.
- Last page matches template closing page.
- TOC exists directly after the cover page.
- Middle pages contain report content.

## Test Case 2: Render PDF Preview

Command:

```bash
python scripts/render_pdf.py out/sre_assessment.pdf --out-dir out/rendered
```

Expected result:

- PNG files are generated for every PDF page.

## Test Case 3: Validate Layout

Command:

```bash
python scripts/validate_layout.py out/sre_assessment.pdf --summary out/validation_summary.json
```

Expected result:

- Status is success.
- No critical clipping or boundary errors are found.

## Test Case 4: Validate Navigable TOC

Command:

```bash
python scripts/validate_toc_links.py out/sre_assessment.pdf
```

Expected result:

- Link annotation count is greater than zero.

## Test Case 5: Secret Scan Failure

Add a forbidden token such as `client_secret:` to the input JSON.

Expected result:

- PDF generation fails closed before output creation.


## Test Case 6: Validate Table Structure

Command:

```bash
python scripts/validate_table_structure.py examples/sre_assessment_input.json --summary out/table_structure_summary.json
```

Expected result:

- Status is success.
- No empty or duplicate column headers exist.
- Header count and row cell count are structurally consistent or safely normalizable.

## Test Case 7: Table Normalization

Create a table row with one missing cell and another row with one extra cell.

Expected result:

- Missing cells are padded.
- Extra cells are merged into the final column.
- Generated PDF does not visually overlap or overflow between columns or rows.


## Test Case 8: Validate Table Data Fitment Without Word Breaks

Command:

```bash
python scripts/validate_table_fitment.py examples/sre_assessment_input.json --summary out/table_fitment_summary.json
```

Expected result:

- Status is success.
- Every unbreakable token can fit within a calculated cell width.
- Wide tables are identified for column chunking instead of forcing content into narrow columns.
- Generation fails closed if a single unbreakable token cannot fit without word break.


## Test Case 9: Validate Template Usage and Preservation

Command:

```bash
python scripts/validate_template_usage.py out/sample_sre_assessment_docx_template.pdf   --template templates/template.docx   --summary out/template_usage_summary.json
```

Expected result:

- Status is success.
- First page size matches the first page of the converted template.
- Last page size matches the last page of the converted template.
- First and last template visual preservation scores meet the configured threshold.
- First and last generated pages contain extractable overlay text.
- Template content is preserved while generated report content is written on top of the template pages.


## Test Case 10: Validate PNG Background Usage

Command:

```bash
python scripts/validate_background_usage.py out/sample_sre_assessment_png_background.pdf   --first-background templates/Page_1.png   --last-background templates/Page_2.png   --summary out/background_usage_summary.json
```

Expected result:

- Status is success.
- First page uses `templates/Page_1.png` as a full-page background.
- Last page uses `templates/Page_2.png` as a full-page background.
- First and last pages contain generated report content overlays.
- First and last background images are visually preserved.
- Middle pages remain free-flowing generated pages.
