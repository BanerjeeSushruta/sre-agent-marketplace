#!/usr/bin/env python3
"""Generate an Azure SRE PDF using a template cover and closing page.

Features:
- First page from template PDF with generated cover text overlay
- Last page from template PDF with generated closing text overlay
- Free-flowing middle pages
- Professionally formatted clickable table of contents
- Tables with controlled widths, padding, repeat headers, and word-boundary wrapping
- Basic secret scanning
- Validation manifest output
"""
import argparse
import json
import re
import sys
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from PIL import Image

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    ListFlowable,
    ListItem,
    KeepTogether,
)

SECRET_PATTERNS = [
    r"client_secret\s*[:=]",
    r"password\s*[:=]",
    r"connectionString\s*[:=]",
    r"SharedAccessKey",
    r"Authorization:\s*Bearer",
    r"BEGIN PRIVATE KEY",
    r"AccountKey=",
]

SHORT_COLUMN_HINTS = {
    "id", "finding id", "action id", "severity", "status", "priority", "owner", "date",
    "category", "service", "environment", "approval status", "change ticket"
}

class AzureSREDocTemplate(BaseDocTemplate):
    def __init__(self, filename, title, classification, *args, **kwargs):
        super().__init__(filename, *args, **kwargs)
        self.title = title
        self.classification = classification

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and getattr(flowable, "outline_level", None) is not None:
            text = flowable.getPlainText()
            key = getattr(flowable, "bookmark_key")
            level = getattr(flowable, "outline_level")
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=False)


def fail(message):
    raise RuntimeError(message)


def scan_for_secrets(payload):
    serialized = json.dumps(payload, ensure_ascii=False)
    findings = []
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, serialized, re.IGNORECASE):
            findings.append(pattern)
    return findings


def safe_text(value):
    """Normalize whitespace while preserving word-boundary wrapping.

    ReportLab Paragraph normally wraps at word boundaries. We explicitly set
    splitLongWords=0 in all styles so words are not broken between lines.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_table_structure(columns, rows, section_title="table"):
    """Return headers and rows with guaranteed structural consistency.

    Rules:
    - Header count is authoritative.
    - Missing row cells are padded with empty strings.
    - Extra row cells are merged into the last column with a visible separator.
    - Empty header names are replaced with deterministic Column N labels.
    """
    headers = [safe_text(c) or f"Column {i+1}" for i, c in enumerate(columns or [])]
    if not headers:
        max_cells = max((len(r) for r in rows or []), default=1)
        headers = [f"Column {i+1}" for i in range(max_cells)]
    normalized = []
    structural_warnings = []
    expected = len(headers)
    for ri, row in enumerate(rows or [], start=1):
        source = list(row) if isinstance(row, list) else [row]
        if len(source) < expected:
            structural_warnings.append(f"{section_title}: row {ri} had {len(source)} cells; padded to {expected}.")
            source = source + [""] * (expected - len(source))
        elif len(source) > expected:
            structural_warnings.append(f"{section_title}: row {ri} had {len(source)} cells; merged extra cells into final column.")
            source = source[:expected-1] + [" | ".join(safe_text(x) for x in source[expected-1:])]
        normalized.append([safe_text(x) for x in source])
    return headers, normalized, structural_warnings


def longest_word_length(headers, rows):
    longest = 0
    for value in list(headers) + [cell for row in rows for cell in row]:
        for word in re.findall(r"\S+", safe_text(value)):
            longest = max(longest, len(word))
    return longest


def max_word_width(text, font_name, font_size):
    words = re.findall(r"\S+", safe_text(text)) or [""]
    return max(pdfmetrics.stringWidth(word, font_name, font_size) for word in words)


def required_column_width(header, values, cell_font_size, header_font_size, padding=18):
    header_need = max_word_width(header, "Helvetica-Bold", header_font_size)
    cell_need = max((max_word_width(v, "Helvetica", cell_font_size) for v in values), default=0)
    # Add padding and a small safety buffer so cell text never touches grid lines.
    return max(header_need, cell_need) + padding + 4


def preferred_column_width(header, values, content_width, column_count):
    header_l = len(safe_text(header))
    avg_l = max([header_l] + [len(safe_text(v)) for v in values])
    h = safe_text(header).lower()
    if h in SHORT_COLUMN_HINTS or avg_l <= 12:
        weight = 0.8
    elif avg_l <= 30:
        weight = 1.2
    else:
        weight = 2.2
    return max(0.70 * inch, min(2.60 * inch, content_width * weight / max(column_count, 1)))


def compute_fit_widths(headers, rows, content_width, cell_font_size, header_font_size):
    required = []
    preferred = []
    for ci, header in enumerate(headers):
        values = [row[ci] for row in rows] if rows else []
        req = required_column_width(header, values, cell_font_size, header_font_size)
        required.append(req)
        preferred.append(max(req, preferred_column_width(header, values, content_width, len(headers))))
    total_preferred = sum(preferred)
    if total_preferred <= content_width:
        return preferred
    total_required = sum(required)
    if total_required <= content_width:
        extra = content_width - total_required
        flex = [max(0, p - r) for p, r in zip(preferred, required)]
        flex_total = sum(flex) or 1
        return [r + extra * f / flex_total for r, f in zip(required, flex)]
    return None


def fit_table_chunks(headers, rows, content_width):
    """Create table chunks that guarantee cell text fits boundaries.

    No word-break mode requires each column to be at least as wide as its
    longest token. If all columns cannot fit together, the table is split into
    sequential column chunks. If one token cannot fit even as a single-column
    table at the minimum size, generation fails closed.
    """
    font_pairs = [(8.4, 8.8), (7.8, 8.2), (7.2, 7.6), (6.6, 7.0), (6.0, 6.4), (5.6, 6.0)]
    for cell_font, header_font in font_pairs:
        widths = compute_fit_widths(headers, rows, content_width, cell_font, header_font)
        if widths is not None:
            return [{
                "columns": headers,
                "rows": rows,
                "widths": widths,
                "cell_font": cell_font,
                "header_font": header_font,
                "range": (1, len(headers)),
            }]

    # Split columns into chunks for very wide tables.
    cell_font, header_font = font_pairs[-1]
    chunks = []
    start = 0
    current_cols = []
    current_indices = []
    current_widths = []
    for ci, header in enumerate(headers):
        single_values = [row[ci] for row in rows] if rows else []
        single_required = required_column_width(header, single_values, cell_font, header_font)
        if single_required > content_width:
            raise RuntimeError(
                f"Unbreakable value in column '{header}' cannot fit within page width without breaking the word. "
                "Shorten the value, allow masking, or use an external appendix."
            )
        proposed_cols = current_cols + [header]
        proposed_indices = current_indices + [ci]
        proposed_rows = [[row[i] for i in proposed_indices] for row in rows]
        proposed_widths = compute_fit_widths(proposed_cols, proposed_rows, content_width, cell_font, header_font)
        if proposed_widths is None and current_cols:
            chunk_rows = [[row[i] for i in current_indices] for row in rows]
            widths = compute_fit_widths(current_cols, chunk_rows, content_width, cell_font, header_font)
            chunks.append({
                "columns": current_cols,
                "rows": chunk_rows,
                "widths": widths,
                "cell_font": cell_font,
                "header_font": header_font,
                "range": (current_indices[0] + 1, current_indices[-1] + 1),
            })
            current_cols = [header]
            current_indices = [ci]
        else:
            current_cols = proposed_cols
            current_indices = proposed_indices
    if current_cols:
        chunk_rows = [[row[i] for i in current_indices] for row in rows]
        widths = compute_fit_widths(current_cols, chunk_rows, content_width, cell_font, header_font)
        chunks.append({
            "columns": current_cols,
            "rows": chunk_rows,
            "widths": widths,
            "cell_font": cell_font,
            "header_font": header_font,
            "range": (current_indices[0] + 1, current_indices[-1] + 1),
        })
    return chunks


def table_styles(base_styles, cell_font_size, header_font_size):
    header = ParagraphStyle(
        name=f"TableHeader_{header_font_size}", parent=base_styles["TableHeader"],
        fontSize=header_font_size, leading=header_font_size + 2.0, splitLongWords=0, wordWrap="LTR"
    )
    cell = ParagraphStyle(
        name=f"TableCell_{cell_font_size}", parent=base_styles["TableCell"],
        fontSize=cell_font_size, leading=cell_font_size + 2.4, splitLongWords=0, wordWrap="LTR"
    )
    return header, cell


def stylesheet():
    styles = getSampleStyleSheet()
    base_kwargs = {"splitLongWords": 0, "wordWrap": "LTR"}
    styles.add(ParagraphStyle(
        name="DocTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=22, leading=26, textColor=colors.HexColor("#000042"), spaceAfter=12,
        **base_kwargs
    ))
    styles.add(ParagraphStyle(
        name="H1Azure", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=18, leading=22, textColor=colors.HexColor("#000042"), spaceBefore=18, spaceAfter=8,
        leftIndent=0, keepWithNext=True, **base_kwargs
    ))
    styles.add(ParagraphStyle(
        name="H2Azure", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=colors.HexColor("#003A70"), spaceBefore=14, spaceAfter=6,
        leftIndent=0.15*inch, keepWithNext=True, **base_kwargs
    ))
    styles.add(ParagraphStyle(
        name="H3Azure", parent=styles["Heading3"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, textColor=colors.HexColor("#005A9C"), spaceBefore=10, spaceAfter=4,
        leftIndent=0.30*inch, keepWithNext=True, **base_kwargs
    ))
    styles.add(ParagraphStyle(
        name="BodyAzure", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=10.5, leading=13.2, textColor=colors.HexColor("#1F2937"), spaceAfter=6,
        alignment=TA_LEFT, **base_kwargs
    ))
    styles.add(ParagraphStyle(
        name="TableHeader", parent=styles["BodyText"], fontName="Helvetica-Bold",
        fontSize=8.8, leading=10.8, textColor=colors.HexColor("#000042"), alignment=TA_CENTER,
        splitLongWords=0, wordWrap="LTR"
    ))
    styles.add(ParagraphStyle(
        name="TableCell", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.4, leading=10.8, textColor=colors.HexColor("#1F2937"), alignment=TA_LEFT,
        splitLongWords=0, wordWrap="LTR"
    ))
    styles.add(ParagraphStyle(
        name="Caption", parent=styles["BodyText"], fontName="Helvetica-Oblique",
        fontSize=8.5, leading=10, textColor=colors.HexColor("#6B7280"), spaceBefore=3, spaceAfter=8,
        **base_kwargs
    ))
    styles.add(ParagraphStyle(
        name="CodeBlock", parent=styles["BodyText"], fontName="Courier",
        fontSize=8.5, leading=10.5, backColor=colors.HexColor("#F3F6FA"),
        borderPadding=6, borderColor=colors.HexColor("#D5E3EF"), borderWidth=0.5,
        splitLongWords=0, wordWrap="LTR"
    ))
    return styles


def footer(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(colors.HexColor("#00B5E2"))
    canvas_obj.setLineWidth(0.7)
    canvas_obj.line(doc.leftMargin, 0.55*inch, doc.pagesize[0] - doc.rightMargin, 0.55*inch)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(colors.HexColor("#6B7280"))
    canvas_obj.drawString(doc.leftMargin, 0.35*inch, doc.classification)
    canvas_obj.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.35*inch, f"Page {doc.page}")
    canvas_obj.restoreState()


def heading(text, level, styles, key):
    style_name = {1: "H1Azure", 2: "H2Azure", 3: "H3Azure"}.get(level, "H3Azure")
    para = Paragraph(safe_text(text), styles[style_name])
    para.outline_level = max(0, min(2, level - 1))
    para.bookmark_key = key
    return para


def build_toc_table(data, styles, content_width):
    toc_header = Paragraph("Table of Contents", styles["H1Azure"])
    toc_note = Paragraph("Select a section name to navigate directly to that section.", styles["Caption"])
    toc_rows = [[Paragraph("Section", styles["TableHeader"]), Paragraph("Level", styles["TableHeader"])]]
    for idx, section in enumerate(data.get("sections", []), start=1):
        sid = section.get("id", f"section-{idx}")
        level = int(section.get("level", 1))
        title = safe_text(section.get("title", f"Section {idx}"))
        prefix = "    " * max(0, level - 1)
        link = f'{prefix}<link href="#{sid}"><font color="#003A70">{title}</font></link>'
        toc_rows.append([Paragraph(link, styles["TableCell"]), Paragraph(str(level), styles["TableCell"])])
    toc_table = Table(toc_rows, colWidths=[content_width - 0.8*inch, 0.8*inch], repeatRows=1, hAlign="LEFT")
    toc_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EAF4FB")),
        ("GRID", (0,0), (-1,-1), 0.30, colors.HexColor("#D5E3EF")),
        ("BOX", (0,0), (-1,-1), 0.75, colors.HexColor("#00B5E2")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FBFE")]),
    ]))
    return [toc_header, toc_note, Spacer(1, 0.10*inch), toc_table, PageBreak()]


def column_widths(columns, rows, content_width):
    if not columns:
        return []
    weights = []
    for ci, col in enumerate(columns):
        header = safe_text(col).lower()
        max_len = len(header)
        for row in rows:
            if ci < len(row):
                max_len = max(max_len, len(safe_text(row[ci])))
        if header in SHORT_COLUMN_HINTS or max_len <= 12:
            weight = 0.75
        elif max_len <= 28:
            weight = 1.15
        else:
            weight = 2.1
        weights.append(weight)
    total = sum(weights) or 1
    widths = [content_width * w / total for w in weights]
    min_w = 0.55 * inch
    max_w = 2.25 * inch
    widths = [max(min_w, min(max_w, w)) for w in widths]
    scale = content_width / sum(widths)
    return [w * scale for w in widths]


def build_flowables(data, content_width):
    styles = stylesheet()
    story = []
    story.extend(build_toc_table(data, styles, content_width))

    for idx, section in enumerate(data.get("sections", []), start=1):
        sid = section.get("id", f"section-{idx}")
        level = int(section.get("level", 1))
        title = section.get("title", f"Section {idx}")
        stype = section.get("type", "narrative")
        section_items = [heading(title, level, styles, sid)]

        if stype == "narrative":
            content = section.get("content", "")
            if isinstance(content, list):
                content = "\n\n".join(str(x) for x in content)
            for para in str(content).split("\n\n"):
                if para.strip():
                    section_items.append(Paragraph(safe_text(para), styles["BodyAzure"]))
        elif stype in ("bullets", "numbered"):
            items = section.get("content", [])
            flow_items = [ListItem(Paragraph(safe_text(item), styles["BodyAzure"]), leftIndent=0.25*inch) for item in items]
            section_items.append(ListFlowable(flow_items, bulletType="1" if stype == "numbered" else "bullet", leftIndent=0.25*inch))
            section_items.append(Spacer(1, 0.08*inch))
        elif stype == "table":
            raw_cols = section.get("columns", [])
            raw_rows = section.get("rows", [])
            cols, rows, structural_warnings = normalize_table_structure(raw_cols, raw_rows, title)

            if structural_warnings:
                section_items.append(Paragraph("Table structure normalized: " + "; ".join(structural_warnings), styles["Caption"]))

            chunks = fit_table_chunks(cols, rows, content_width)
            for chunk_index, chunk in enumerate(chunks, start=1):
                header_style, cell_style = table_styles(styles, chunk["cell_font"], chunk["header_font"])
                chunk_cols = chunk["columns"]
                chunk_rows = chunk["rows"]

                if len(chunks) > 1:
                    col_start, col_end = chunk["range"]
                    section_items.append(Paragraph(
                        f"Table continued - columns {col_start} to {col_end} of {len(cols)}.",
                        styles["Caption"]
                    ))

                table_data = [[Paragraph(safe_text(c), header_style) for c in chunk_cols]]
                for row in chunk_rows:
                    table_data.append([Paragraph(safe_text(value), cell_style) for value in row])

                widths = chunk["widths"]
                if not widths or len(widths) != len(chunk_cols):
                    fail(f"Table width calculation failed for section '{title}'. Header count and width count differ.")
                if sum(widths) > content_width + 0.01:
                    fail(f"Table width overflow detected for section '{title}'.")

                table = Table(
                    table_data,
                    colWidths=widths,
                    repeatRows=1,
                    hAlign="LEFT",
                    splitByRow=1,
                    splitInRow=1,
                    normalizedData=1,
                )
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EAF4FB")),
                    ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#000042")),
                    ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#D5E3EF")),
                    ("BOX", (0,0), (-1,-1), 0.75, colors.HexColor("#B7D8EE")),
                    ("LINEBELOW", (0,0), (-1,0), 0.75, colors.HexColor("#00B5E2")),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("ALIGN", (0,0), (-1,0), "CENTER"),
                    ("LEFTPADDING", (0,0), (-1,-1), 8),
                    ("RIGHTPADDING", (0,0), (-1,-1), 8),
                    ("TOPPADDING", (0,0), (-1,-1), 7),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 7),
                    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FCFE")]),
                ]))
                section_items.append(table)
                section_items.append(Spacer(1, 0.10*inch))

            if section.get("caption"):
                section_items.append(Paragraph(safe_text(section["caption"]), styles["Caption"]))
            section_items.append(Spacer(1, 0.12*inch))
        elif stype == "callout":
            section_items.append(Paragraph(safe_text(section.get("content", "")), ParagraphStyle(
                name=f"Callout{idx}", parent=styles["BodyAzure"], backColor=colors.HexColor("#EAF4FB"),
                borderColor=colors.HexColor("#00B5E2"), borderWidth=1, borderPadding=8,
                leftIndent=0.10*inch, rightIndent=0.10*inch, splitLongWords=0, wordWrap="LTR"
            )))
        elif stype == "code":
            section_items.append(Paragraph(str(section.get("content", "")).replace("\n", "<br/>").replace(" ", "&nbsp;"), styles["CodeBlock"]))
        else:
            section_items.append(Paragraph(safe_text(section.get("content", "")), styles["BodyAzure"]))

        # Keep a short heading with its first paragraph/table when possible.
        if len(section_items) <= 3:
            story.append(KeepTogether(section_items))
        else:
            story.extend(section_items)

    return story


def generate_body(data, body_pdf):
    doc_info = data["document"]
    page_size = A4 if data.get("layout", {}).get("page_size", "A4") == "A4" else LETTER
    if data.get("layout", {}).get("orientation") == "landscape":
        page_size = landscape(page_size)
    doc = AzureSREDocTemplate(
        body_pdf,
        title=doc_info.get("title", "Azure SRE Report"),
        classification=doc_info.get("classification", "CONFIDENTIAL - INTERNAL USE ONLY"),
        pagesize=page_size,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.65*inch,
        bottomMargin=0.75*inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="content", frames=[frame], onPage=footer)])
    doc.build(build_flowables(data, doc.width))


def template_page_size(page):
    box = page.mediabox
    return float(box.width), float(box.height)


def resolve_template_pdf(template_path, work_dir):
    """Resolve a PDF template from either PDF or DOCX input.

    Report templates can be provided as DOCX. At runtime the DOCX is converted
    to PDF using LibreOffice. The first converted page becomes the report cover
    template and the last converted page becomes the report closing template.
    All middle report pages remain generated, free-flowing pages.
    """
    template_path = Path(template_path)
    suffix = template_path.suffix.lower()
    if suffix == ".pdf":
        return template_path
    if suffix != ".docx":
        fail(f"Unsupported template type '{suffix}'. Use .docx or .pdf.")
    out_dir = Path(work_dir) / "template_pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "soffice", "--headless", "--nologo", "--nolockcheck",
        "--convert-to", "pdf", "--outdir", str(out_dir), str(template_path)
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    converted = out_dir / f"{template_path.stem}.pdf"
    if not converted.exists() or converted.stat().st_size == 0:
        fail(f"Template DOCX conversion failed. stdout={proc.stdout} stderr={proc.stderr}")
    return converted


def make_template_overlay(data, page_size, kind):
    doc_info = data.get("document", {})
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=page_size)
    w, h = page_size
    c.saveState()
    if kind == "cover":
        overlay_styles = stylesheet()
        title_style = ParagraphStyle(
            name="CoverTitle", parent=overlay_styles["BodyAzure"], fontName="Helvetica-Bold",
            fontSize=26, leading=30, textColor=colors.white, splitLongWords=0, wordWrap="LTR"
        )
        subtitle_style = ParagraphStyle(
            name="CoverSubtitle", parent=overlay_styles["BodyAzure"], fontName="Helvetica",
            fontSize=14, leading=17, textColor=colors.HexColor("#DCEBFF"), splitLongWords=0, wordWrap="LTR"
        )
        text_w = min(w - 1.45*inch, 6.25*inch)
        title_p = Paragraph(safe_text(doc_info.get("title", "Azure SRE Report")), title_style)
        tw, th = title_p.wrap(text_w, 1.1*inch)
        title_p.drawOn(c, 0.72*inch, h - 2.05*inch - th)
        subtitle_p = Paragraph(safe_text(doc_info.get("subtitle", "Enterprise PDF Report")), subtitle_style)
        sw, sh = subtitle_p.wrap(text_w, 0.70*inch)
        subtitle_p.drawOn(c, 0.72*inch, h - 2.52*inch - th - sh/2)
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#DCEBFF"))
        meta_y = h - 3.22*inch - th
        c.drawString(0.72*inch, meta_y, f"Generated by: {safe_text(doc_info.get('generated_by', 'Azure SRE Agent'))}")
        c.drawString(0.72*inch, meta_y - 0.25*inch, f"Reporting period: {safe_text(doc_info.get('reporting_period', ''))}")
        if doc_info.get("environment"):
            c.drawString(0.72*inch, meta_y - 0.50*inch, f"Environment: {safe_text(doc_info.get('environment'))}")
        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#6AA2DC"))
        c.drawString(0.72*inch, 0.43*inch, f"{safe_text(doc_info.get('classification', 'CONFIDENTIAL - INTERNAL USE ONLY'))} | {safe_text(doc_info.get('reporting_period', ''))}")
    else:
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(w/2, h/2 + 0.30*inch, "Thank You")
        c.setFont("Helvetica", 11)
        c.setFillColor(colors.HexColor("#DCEBFF"))
        c.drawCentredString(w/2, h/2 - 0.02*inch, safe_text(doc_info.get("title", "Azure SRE Report"))[:100])
        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#6AA2DC"))
        c.drawCentredString(w/2, h/2 - 0.34*inch, safe_text(doc_info.get("classification", "CONFIDENTIAL - INTERNAL USE ONLY")))
    c.restoreState()
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def background_page_size(image_path):
    with Image.open(image_path) as img:
        width_px, height_px = img.size
    page_w = 960.0
    page_h = page_w * height_px / width_px
    return page_w, page_h


def make_background_page(data, image_path, kind):
    page_size = background_page_size(image_path)
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=page_size)
    w, h = page_size
    c.drawImage(ImageReader(str(image_path)), 0, 0, width=w, height=h, preserveAspectRatio=False, mask='auto')

    doc_info = data.get("document", {})
    c.saveState()
    if kind == "cover":
        overlay_styles = stylesheet()
        title_style = ParagraphStyle(
            name="CoverBgTitle", parent=overlay_styles["BodyAzure"], fontName="Helvetica-Bold",
            fontSize=28, leading=32, textColor=colors.white, splitLongWords=0, wordWrap="LTR"
        )
        subtitle_style = ParagraphStyle(
            name="CoverBgSubtitle", parent=overlay_styles["BodyAzure"], fontName="Helvetica",
            fontSize=14, leading=17, textColor=colors.HexColor("#DCEBFF"), splitLongWords=0, wordWrap="LTR"
        )
        text_w = min(w - 1.45*inch, 6.35*inch)
        title_p = Paragraph(safe_text(doc_info.get("title", "Azure SRE Report")), title_style)
        _, th = title_p.wrap(text_w, 1.25*inch)
        title_p.drawOn(c, 0.72*inch, h - 2.18*inch - th)
        subtitle_p = Paragraph(safe_text(doc_info.get("subtitle", "Enterprise PDF Report")), subtitle_style)
        _, sh = subtitle_p.wrap(text_w, 0.70*inch)
        subtitle_p.drawOn(c, 0.72*inch, h - 2.62*inch - th - sh/2)
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#DCEBFF"))
        meta_y = h - 3.30*inch - th
        c.drawString(0.72*inch, meta_y, f"Generated by: {safe_text(doc_info.get('generated_by', 'Azure SRE Agent'))}")
        c.drawString(0.72*inch, meta_y - 0.25*inch, f"Reporting period: {safe_text(doc_info.get('reporting_period', ''))}")
        if doc_info.get("environment"):
            c.drawString(0.72*inch, meta_y - 0.50*inch, f"Environment: {safe_text(doc_info.get('environment'))}")
    else:
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(0.72*inch, h - 1.35*inch, "Report Completed")
        c.setFont("Helvetica", 12)
        c.setFillColor(colors.HexColor("#DCEBFF"))
        c.drawString(0.72*inch, h - 1.72*inch, safe_text(doc_info.get("title", "Azure SRE Report"))[:110])
        c.setFont("Helvetica", 9)
        c.drawString(0.72*inch, h - 2.02*inch, safe_text(doc_info.get("classification", "CONFIDENTIAL - INTERNAL USE ONLY")))
    c.restoreState()
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def merge_with_image_backgrounds(first_bg_path, last_bg_path, body_path, out_path, data):
    body_reader = PdfReader(body_path)
    writer = PdfWriter()
    writer.add_page(make_background_page(data, Path(first_bg_path), "cover"))
    for page in body_reader.pages:
        writer.add_page(page)
    writer.add_page(make_background_page(data, Path(last_bg_path), "closing"))

    doc_info = data.get("document", {})
    writer.add_metadata({
        "/Title": doc_info.get("title", "Azure SRE Agent PDF"),
        "/Author": doc_info.get("author", "Azure SRE Platform Team"),
        "/Creator": "Azure SRE Agent PDF Creation Skill",
        "/Producer": "Azure SRE Agent PDF Creation Skill",
        "/Subject": "Azure SRE PDF generated with PNG first/last backgrounds, formatted TOC, formatted tables, free-flowing body, and content overlays"
    })
    with open(out_path, "wb") as f:
        writer.write(f)


def merge_with_template(template_path, body_path, out_path, data):
    template_reader = PdfReader(template_path)
    if len(template_reader.pages) < 2:
        fail("Template PDF must contain at least two pages.")
    body_reader = PdfReader(body_path)
    writer = PdfWriter()

    cover = template_reader.pages[0]
    cover.merge_page(make_template_overlay(data, template_page_size(cover), "cover"))
    writer.add_page(cover)

    for page in body_reader.pages:
        writer.add_page(page)

    closing = template_reader.pages[-1]
    closing.merge_page(make_template_overlay(data, template_page_size(closing), "closing"))
    writer.add_page(closing)

    doc_info = data.get("document", {})
    writer.add_metadata({
        "/Title": doc_info.get("title", "Azure SRE Agent PDF"),
        "/Author": doc_info.get("author", "Azure SRE Platform Team"),
        "/Creator": "Azure SRE Agent PDF Creation Skill",
        "/Producer": "Azure SRE Agent PDF Creation Skill",
        "/Subject": "Azure SRE PDF generated with template cover overlay, formatted TOC, formatted tables, free-flowing body, and closing overlay"
    })
    with open(out_path, "wb") as f:
        writer.write(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json")
    parser.add_argument("--output", required=False)
    args = parser.parse_args()

    input_path = Path(args.input_json)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    secret_findings = scan_for_secrets(data)
    if secret_findings:
        fail(f"Sensitive values detected. Redact before PDF generation. Patterns: {secret_findings}")

    root = input_path.resolve().parents[1] if input_path.parent.name == "examples" else Path.cwd()
    template_path = Path(data["template"]["file_name"])
    if not template_path.is_absolute():
        template_path = root / template_path
    if not template_path.exists():
        fail(f"Template not found: {template_path}")

    out_path = Path(args.output or data["output"]["file_name"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    template_cfg = data.get("template", {})
    use_background_images = bool(template_cfg.get("use_background_images"))
    first_bg = template_cfg.get("first_page_background")
    last_bg = template_cfg.get("last_page_background")
    if first_bg and last_bg:
        use_background_images = True

    with tempfile.TemporaryDirectory() as tmp:
        body_path = Path(tmp) / "body.pdf"
        generate_body(data, str(body_path))
        template_pdf_path = None
        if use_background_images:
            first_bg_path = Path(first_bg or "templates/Page_1.png")
            last_bg_path = Path(last_bg or "templates/Page_2.png")
            if not first_bg_path.is_absolute():
                first_bg_path = root / first_bg_path
            if not last_bg_path.is_absolute():
                last_bg_path = root / last_bg_path
            if not first_bg_path.exists():
                fail(f"First page background image not found: {first_bg_path}")
            if not last_bg_path.exists():
                fail(f"Last page background image not found: {last_bg_path}")
            merge_with_image_backgrounds(first_bg_path, last_bg_path, str(body_path), str(out_path), data)
        else:
            template_pdf_path = resolve_template_pdf(template_path, tmp)
            merge_with_template(str(template_pdf_path), str(body_path), str(out_path), data)

    print(json.dumps({
        "status": "success",
        "pdf_file": str(out_path),
        "template_source_file": str(template_path),
        "template_source_type": Path(template_path).suffix.lower().lstrip('.'),
        "template_used": str(template_pdf_path) if template_pdf_path else None,
        "background_images_used": use_background_images,
        "first_page_background": str(first_bg_path) if use_background_images else None,
        "last_page_background": str(last_bg_path) if use_background_images else None,
        "cover_page_from_template": not use_background_images,
        "cover_page_from_background_image": use_background_images,
        "cover_template_content_overlay": True,
        "closing_page_from_template": not use_background_images,
        "closing_page_from_background_image": use_background_images,
        "closing_template_content_overlay": True,
        "middle_pages_free_flowing": True,
        "toc_generated": True,
        "toc_clickable": True,
        "toc_formatted": True,
        "tables_formatted": True,
        "table_fitment_enforced": True,
        "table_column_chunking_enabled": True,
        "word_breaking_disabled": True
    }, indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        sys.exit(1)
