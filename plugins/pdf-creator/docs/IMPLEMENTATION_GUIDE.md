# Implementation Guide

## Objective

Implement an Azure SRE Agent PDF generation capability that uses:

1. Template first page as the cover.
2. Template last page as the closing page.
3. Free-flowing generated middle pages.
4. Proper indentation and no-overlap rules.
5. A navigable table of contents.

## Recommended Agent Flow

1. Validate the input JSON against `schemas/input.schema.json`.
2. Perform security scanning against known secret patterns.
3. Read `templates/template.pdf`.
4. Generate the middle PDF with a table of contents and section bookmarks.
5. Merge the template cover, generated body, and template closing page.
6. Render the merged PDF into PNG preview images.
7. Validate page count, links, clipping, content boundary, and possible overlap.
8. Return the final PDF only if validation passes.

## Layout Standards

- Use A4 portrait for detailed reports.
- Use fixed safe margins but dynamic free-flowing body content.
- Avoid fixed-position content boxes in middle pages.
- Use flowable paragraphs, lists, and tables.
- Repeat table headers on page breaks.
- Keep section headings with the following content where possible.

## TOC Requirements

- The TOC must appear after the cover page.
- TOC entries must be linked to PDF destinations/bookmarks.
- TOC must be regenerated after pagination-altering changes.

## Validation Gate

The agent must not return a PDF unless:

- `validate_layout.py` returns success.
- `validate_toc_links.py` returns success.
- Render previews are created successfully.
