#!/usr/bin/env python3
"""
Azure FinOps Best Practices Validator - PDF Report Generator
---------------------------------------------------------------
Turns a findings.json (produced by validate_resources.py) into a polished
PDF report with an executive summary, a findings table, and per-finding
remediation guidance grouped by rule ID.

Usage:
    python generate_report.py \
        --findings findings.json \
        --output AzureFinOps_Validation_Report.pdf \
        --title "Contoso Production Subscription" \
        --rules references/finops_rules.json
"""

import argparse
import json
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)

SEVERITY_COLORS = {
    "High": colors.HexColor("#C0392B"),
    "Medium": colors.HexColor("#B9770E"),
    "Low": colors.HexColor("#1E8449"),
}
AZURE_BLUE = colors.HexColor("#0078D4")
DARK_GREY = colors.HexColor("#2B2B2B")
LIGHT_GREY = colors.HexColor("#F2F2F2")


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", fontSize=24, leading=28, textColor=AZURE_BLUE,
        spaceAfter=6, fontName="Helvetica-Bold"
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", fontSize=13, leading=16, textColor=DARK_GREY,
        spaceAfter=20, fontName="Helvetica"
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading", fontSize=15, leading=18, textColor=AZURE_BLUE,
        spaceBefore=18, spaceAfter=8, fontName="Helvetica-Bold"
    ))
    styles.add(ParagraphStyle(
        name="RuleHeading", fontSize=11.5, leading=14, textColor=colors.white,
        fontName="Helvetica-Bold"
    ))
    styles.add(ParagraphStyle(
        name="BodySmall", fontSize=9.5, leading=13, textColor=DARK_GREY
    ))
    styles.add(ParagraphStyle(
        name="BodySmallBold", fontSize=9.5, leading=13, textColor=DARK_GREY,
        fontName="Helvetica-Bold"
    ))
    styles.add(ParagraphStyle(
        name="CoverMeta", fontSize=10, leading=14, textColor=colors.grey,
        alignment=TA_CENTER
    ))
    return styles


def cover_page(story, styles, title, findings_doc):
    story.append(Spacer(1, 1.6 * inch))
    story.append(Paragraph("Azure FinOps Best Practices", styles["ReportTitle"]))
    story.append(Paragraph("Validation &amp; Remediation Report", styles["ReportSubtitle"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(HRFlowable(width="100%", color=AZURE_BLUE, thickness=1.4))
    story.append(Spacer(1, 0.25 * inch))
    story.append(Paragraph(f"Scope: {title}", styles["BodySmallBold"]))
    generated = findings_doc.get("generated_at", datetime.utcnow().isoformat())
    story.append(Paragraph(f"Generated: {generated}", styles["BodySmall"]))
    story.append(Paragraph(f"Rule catalog version: {findings_doc.get('ruleset_version', 'n/a')}", styles["BodySmall"]))
    story.append(Paragraph(
        f"Resources evaluated: {findings_doc.get('resource_count', 'n/a')} | "
        f"Findings: {findings_doc.get('finding_count', 0)}",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(
        "Aligned to the FinOps Foundation FinOps Framework, the Azure Well-Architected "
        "Framework Cost Optimization pillar, and Azure Advisor cost recommendation "
        "categories.",
        styles["CoverMeta"]
    ))
    story.append(PageBreak())


def summary_section(story, styles, findings_doc):
    story.append(Paragraph("Executive Summary", styles["SectionHeading"]))
    sev_counts = findings_doc.get("findings_by_severity", {})
    findings = findings_doc.get("findings", [])
    total_cost_at_risk = sum(
        f.get("monthly_cost_usd") or 0 for f in findings
    )

    summary_rows = [
        ["Metric", "Value"],
        ["Resources evaluated", str(findings_doc.get("resource_count", "n/a"))],
        ["Rules evaluated against inventory", str(len(findings_doc.get("rules_evaluated", [])))],
        ["Rules requiring additional account-scope data", str(len(findings_doc.get("rules_not_evaluated_needs_data", [])))],
        ["Total findings", str(findings_doc.get("finding_count", 0))],
        ["High severity findings", str(sev_counts.get("High", 0))],
        ["Medium severity findings", str(sev_counts.get("Medium", 0))],
        ["Low severity findings", str(sev_counts.get("Low", 0))],
        ["Monthly cost on flagged resources", f"${total_cost_at_risk:,.2f}" if total_cost_at_risk else "n/a"],
    ]
    t = Table(summary_rows, colWidths=[3.2 * inch, 3.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.25 * inch))

    not_evaluated = findings_doc.get("rules_not_evaluated_needs_data", [])
    if not_evaluated:
        story.append(Paragraph(
            f"<b>Note:</b> {len(not_evaluated)} rule(s) were not evaluated because the "
            f"submitted inventory did not include the required account/subscription-scope "
            f"signals (e.g., budgets, Advisor feed, load-balancer telemetry): "
            f"{', '.join(not_evaluated)}. Recommend a follow-up pass once that data is "
            f"available — see references/finops_rules.json for detection logic.",
            styles["BodySmall"]
        ))
    story.append(Spacer(1, 0.2 * inch))


def findings_table_section(story, styles, findings_doc):
    story.append(Paragraph("Findings Overview", styles["SectionHeading"]))
    findings = findings_doc.get("findings", [])
    if not findings:
        story.append(Paragraph("No findings were raised against the submitted inventory.", styles["BodySmall"]))
        return

    header = ["Rule ID", "Severity", "Resource", "Type", "Finding"]
    rows = [header]
    for f in findings:
        rows.append([
            f["rule_id"],
            f["severity"],
            f.get("resource_name", "n/a"),
            (f.get("resource_type") or "").replace("Microsoft.", ""),
            Paragraph(f.get("finding_detail") or f["title"], styles["BodySmall"]),
        ])

    t = Table(rows, colWidths=[0.7 * inch, 0.7 * inch, 1.3 * inch, 1.5 * inch, 2.3 * inch], repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, f in enumerate(findings, start=1):
        color = SEVERITY_COLORS.get(f["severity"], colors.black)
        style_cmds.append(("TEXTCOLOR", (1, i), (1, i), color))
        style_cmds.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GREY))
    t.setStyle(TableStyle(style_cmds))
    story.append(t)
    story.append(PageBreak())


def remediation_section(story, styles, findings_doc):
    story.append(Paragraph("Detailed Remediation Guidance", styles["SectionHeading"]))
    findings = findings_doc.get("findings", [])

    # Group findings by rule_id so repeated resource hits share one remediation block.
    grouped = {}
    for f in findings:
        grouped.setdefault(f["rule_id"], {"meta": f, "resources": []})
        grouped[f["rule_id"]]["resources"].append(f)

    for rule_id in sorted(grouped.keys()):
        group = grouped[rule_id]
        meta = group["meta"]
        resources = group["resources"]
        color = SEVERITY_COLORS.get(meta["severity"], colors.grey)

        header_table = Table(
            [[Paragraph(f"{rule_id} &nbsp;&nbsp;|&nbsp;&nbsp; {meta['title']}", styles["RuleHeading"])]],
            colWidths=[6.9 * inch]
        )
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), color),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))

        body_rows = [
            [Paragraph("<b>Severity</b>", styles["BodySmall"]), Paragraph(meta["severity"], styles["BodySmall"])],
            [Paragraph("<b>Category / Domain</b>", styles["BodySmall"]), Paragraph(f"{meta['category']} / {meta['domain']}", styles["BodySmall"])],
            [Paragraph("<b>Affected resources</b>", styles["BodySmall"]),
             Paragraph("; ".join(r.get("resource_name", "n/a") for r in resources), styles["BodySmall"])],
            [Paragraph("<b>Remediation</b>", styles["BodySmall"]), Paragraph(meta["remediation"], styles["BodySmall"])],
            [Paragraph("<b>Estimated savings</b>", styles["BodySmall"]), Paragraph(meta["estimated_savings"], styles["BodySmall"])],
        ]
        body_table = Table(body_rows, colWidths=[1.5 * inch, 5.4 * inch])
        body_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("BACKGROUND", (0, 0), (0, -1), LIGHT_GREY),
        ]))

        story.append(KeepTogether([header_table, body_table, Spacer(1, 0.18 * inch)]))


def access_coverage_section(story, styles, preflight_doc):
    """Identity & access coverage: which RBAC roles the assessment ran with,
    so readers know exactly what was and wasn't evaluable."""
    if not preflight_doc:
        return
    story.append(Paragraph("Identity &amp; Access Coverage", styles["SectionHeading"]))
    identity = preflight_doc.get("identity") or {}
    story.append(Paragraph(
        f"Assessment identity: <b>{identity.get('name', 'unknown')}</b> "
        f"({identity.get('type', 'unknown')}) on subscription "
        f"<b>{preflight_doc.get('subscription_name') or preflight_doc.get('subscription_id', 'n/a')}</b>. "
        "Checks gated by a MISSING or UNKNOWN role below were skipped or are best-effort "
        "in this report — re-run after granting the role for full coverage.",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.1 * inch))

    rows = [["Role", "Need", "Status", "Gates"]]
    missing_row_indexes = []
    for entry in preflight_doc.get("roles", []):
        st = str(entry.get("status", "UNKNOWN"))
        if st.startswith(("MISSING", "UNKNOWN")):
            missing_row_indexes.append(len(rows))
        rows.append([
            Paragraph(entry.get("role", ""), styles["BodySmallBold"]),
            entry.get("need", ""),
            st,
            Paragraph(entry.get("gates", ""), styles["BodySmall"]),
        ])
    t = Table(rows, colWidths=[1.5 * inch, 0.7 * inch, 1.1 * inch, 3.2 * inch], repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in missing_row_indexes:
        style_cmds.append(("TEXTCOLOR", (2, i), (2, i), SEVERITY_COLORS["Medium"]))
        style_cmds.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style_cmds))
    story.append(t)
    roles_held = preflight_doc.get("roles_held")
    if roles_held:
        story.append(Paragraph(
            f"Roles held at subscription scope: {', '.join(roles_held)}.",
            styles["BodySmall"]
        ))
    story.append(Spacer(1, 0.2 * inch))


def savings_summary_section(story, styles, findings_doc, ruleset):
    """Cost-saving opportunity overview: findings grouped by category with the
    monthly cost on flagged resources and the catalog's estimated savings range."""
    story.append(Paragraph("Cost-Saving Opportunities by Category", styles["SectionHeading"]))
    findings = findings_doc.get("findings", [])
    if not findings:
        story.append(Paragraph("No cost-saving opportunities were identified in the submitted inventory.", styles["BodySmall"]))
        return

    rules_by_id = {r["rule_id"]: r for r in ruleset["rules"]}
    by_category = {}
    for f in findings:
        cat = by_category.setdefault(f["category"], {"count": 0, "cost": 0.0, "rules": set()})
        cat["count"] += 1
        cat["cost"] += f.get("monthly_cost_usd") or 0
        cat["rules"].add(f["rule_id"])

    rows = [["Category", "Findings", "Monthly cost flagged", "Rules", "Typical savings potential"]]
    for cat in sorted(by_category, key=lambda c: -by_category[c]["cost"]):
        info = by_category[cat]
        savings = "; ".join(sorted({
            rules_by_id[rid]["estimated_savings"] for rid in info["rules"] if rid in rules_by_id
        }))
        rows.append([
            Paragraph(cat, styles["BodySmall"]),
            str(info["count"]),
            f"${info['cost']:,.2f}" if info["cost"] else "n/a",
            Paragraph(", ".join(sorted(info["rules"])), styles["BodySmall"]),
            Paragraph(savings, styles["BodySmall"]),
        ])
    t = Table(rows, colWidths=[1.2 * inch, 0.6 * inch, 1.1 * inch, 1.2 * inch, 2.4 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Savings ranges are industry-typical estimates from the rule catalog — validate "
        "against actual negotiated rates before committing.",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.2 * inch))


def reservation_section(story, styles, findings_doc):
    """Azure Reservation / Savings Plan opportunities (Commitment Discounts findings,
    including per-SKU purchase recommendations from the Consumption API)."""
    story.append(Paragraph("Azure Reservation &amp; Savings Plan Opportunities", styles["SectionHeading"]))
    res_findings = [f for f in findings_doc.get("findings", [])
                    if f.get("category") in ("Commitment Discounts",)]
    if not res_findings:
        story.append(Paragraph(
            "No reservation or savings-plan opportunities were detected in this pass. This can "
            "mean coverage is already adequate, or that the Consumption reservation-recommendation "
            "API had no 30+ day steady-state usage to analyze (it needs Reader access and lags "
            "~24h behind new usage). Re-check after a full billing month of steady usage.",
            styles["BodySmall"]
        ))
        story.append(Spacer(1, 0.2 * inch))
        return

    rows = [["SKU / Resource", "Location", "Detail"]]
    for f in res_findings:
        rows.append([
            Paragraph(f.get("resource_name") or "n/a", styles["BodySmall"]),
            f.get("location") or "n/a",
            Paragraph(f.get("finding_detail") or f["title"], styles["BodySmall"]),
        ])
    t = Table(rows, colWidths=[1.5 * inch, 0.9 * inch, 4.1 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Purchase guidance: prefer 3-year terms for stable baseline workloads (up to ~72% off "
        "pay-as-you-go), 1-year for medium confidence; use Azure Savings Plans for Compute where "
        "the workload mix shifts across VM families. Reservations can be exchanged/refunded within "
        "policy limits — start with high-confidence recommendations and expand coverage quarterly.",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.2 * inch))


def log_cost_section(story, styles, findings_doc):
    """Log & monitoring cost analysis: findings on Log Analytics workspaces."""
    story.append(Paragraph("Log &amp; Monitoring Cost Analysis", styles["SectionHeading"]))
    log_findings = [f for f in findings_doc.get("findings", [])
                    if (f.get("resource_type") or "").lower() == "microsoft.operationalinsights/workspaces"]
    if not log_findings:
        story.append(Paragraph(
            "No Log Analytics cost findings were raised. If workspaces exist in scope, confirm "
            "ingestion metrics were collected (Monitoring Reader) — otherwise the idle-workspace, "
            "commitment-tier, and cost-control rules (AZFO-021/022/028) are skipped.",
            styles["BodySmall"]
        ))
        story.append(Spacer(1, 0.2 * inch))
        return

    rows = [["Workspace", "Rule", "Finding"]]
    for f in log_findings:
        rows.append([
            Paragraph(f.get("resource_name") or "n/a", styles["BodySmall"]),
            f["rule_id"],
            Paragraph(f.get("finding_detail") or f["title"], styles["BodySmall"]),
        ])
    t = Table(rows, colWidths=[1.6 * inch, 0.8 * inch, 4.1 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Deep-dive query — run in each flagged workspace to find the biggest ingestion drivers: "
        "<font face='Courier' size='8'>Usage | where TimeGenerated &gt; ago(30d) | summarize "
        "IngestionGB=sum(Quantity)/1000 by DataType | order by IngestionGB desc</font>. "
        "Then move verbose tables to the Basic/Auxiliary plan, add DCR transformations to drop "
        "noisy rows, cap non-production workspaces, and right-size retention per table.",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.2 * inch))


def policy_guardrails_section(story, styles, findings_doc, guardrails_doc):
    """Cost-saving guardrails: Azure Policy suggestions, flagging those related
    to rules that actually fired in this assessment."""
    story.append(PageBreak())
    story.append(Paragraph("Cost-Saving Guardrails — Azure Policy Suggestions", styles["SectionHeading"]))
    story.append(Paragraph(
        "Remediation fixes today's waste; policy guardrails stop it from coming back. The "
        "following Azure Policy assignments prevent recurrence of this assessment's finding "
        "classes. Rows marked <b>✦ recommended now</b> relate to rules that fired in this run. "
        "Assign at management-group or subscription scope; start with Audit and graduate to "
        "Deny/Modify once exemption processes exist.",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.12 * inch))

    fired_rules = {f["rule_id"] for f in findings_doc.get("findings", [])}
    rows = [["Guardrail", "Azure Policy", "Effect", "Related rules", "Priority"]]
    priority_row_indexes = []
    guardrails = sorted(
        guardrails_doc.get("guardrails", []),
        key=lambda g: not (set(g.get("related_rules", [])) & fired_rules),
    )
    for g in guardrails:
        related = set(g.get("related_rules", []))
        fired = bool(related & fired_rules)
        policy_text = g["policy"]
        if g.get("policy_definition_id"):
            policy_text += f" — definition ID {g['policy_definition_id']}"
        elif g.get("custom_policy_hint"):
            policy_text += f". {g['custom_policy_hint']}"
        if g.get("notes"):
            policy_text += f" {g['notes']}"
        if fired:
            priority_row_indexes.append(len(rows))
        rows.append([
            Paragraph(f"<b>{g['guardrail_id']}</b>: {g['title']}", styles["BodySmall"]),
            Paragraph(policy_text, styles["BodySmall"]),
            g.get("effect", "Audit"),
            Paragraph(", ".join(sorted(related)) or "general", styles["BodySmall"]),
            Paragraph("✦ recommended now" if fired else "baseline", styles["BodySmall"]),
        ])
    t = Table(rows, colWidths=[1.5 * inch, 3.0 * inch, 0.75 * inch, 0.85 * inch, 0.85 * inch], repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in priority_row_indexes:
        style_cmds.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#FDEBD0")))
    t.setStyle(TableStyle(style_cmds))
    story.append(t)
    story.append(Paragraph(
        "Assignment example: <font face='Courier' size='8'>az policy assignment create --name "
        "&lt;name&gt; --policy &lt;definition-id&gt; --scope /subscriptions/&lt;sub-id&gt; "
        "--params '{...}'</font>. Verify built-in definition IDs in your cloud before assigning "
        "(<font face='Courier' size='8'>az policy definition show --name &lt;guid&gt;</font>).",
        styles["BodySmall"]
    ))


def appendix_section(story, styles, ruleset):
    story.append(PageBreak())
    story.append(Paragraph("Appendix: Full Rule Catalog", styles["SectionHeading"]))
    story.append(Paragraph(
        "Complete list of rules in this validation pass, including rules not "
        "triggered by any finding. Full detection logic lives in "
        "references/finops_rules.json.",
        styles["BodySmall"]
    ))
    story.append(Spacer(1, 0.1 * inch))

    header = ["Rule ID", "Title", "Category", "Severity"]
    rows = [header]
    for r in ruleset["rules"]:
        rows.append([r["rule_id"], Paragraph(r["title"], styles["BodySmall"]), r["category"], r["severity"]])

    t = Table(rows, colWidths=[0.7 * inch, 3.4 * inch, 1.5 * inch, 0.9 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZURE_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)


def main():
    parser = argparse.ArgumentParser(description="Generate a PDF FinOps remediation report from findings.json")
    parser.add_argument("--findings", required=True, help="Path to findings JSON from validate_resources.py")
    parser.add_argument("--rules", default="references/finops_rules.json", help="Path to rule catalog JSON")
    parser.add_argument("--guardrails", default=None,
                        help="Path to Azure Policy guardrails JSON (default: azure-policy-guardrails.json next to the rules file)")
    parser.add_argument("--preflight", default=None,
                        help="Path to preflight permissions JSON from check_permissions.py --json-output; "
                             "renders the Identity & Access Coverage section")
    parser.add_argument("--output", default="AzureFinOps_Validation_Report.pdf", help="Output PDF path")
    parser.add_argument("--title", default="Azure Subscription", help="Scope name shown on the cover page")
    args = parser.parse_args()

    with open(args.findings) as f:
        findings_doc = json.load(f)
    with open(args.rules) as f:
        ruleset = json.load(f)

    guardrails_path = args.guardrails or os.path.join(os.path.dirname(os.path.abspath(args.rules)),
                                                      "azure-policy-guardrails.json")
    guardrails_doc = {"guardrails": []}
    if os.path.exists(guardrails_path):
        with open(guardrails_path) as f:
            guardrails_doc = json.load(f)
    else:
        print(f"  [warn] guardrails catalog not found at {guardrails_path}; "
              "the Azure Policy guardrails section will be empty.")

    preflight_doc = None
    if args.preflight:
        if os.path.exists(args.preflight):
            with open(args.preflight) as f:
                preflight_doc = json.load(f)
        else:
            print(f"  [warn] preflight file not found at {args.preflight}; "
                  "the Identity & Access Coverage section will be omitted.")

    styles = build_styles()
    doc = SimpleDocTemplate(
        args.output, pagesize=letter,
        topMargin=0.9 * inch, bottomMargin=0.8 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        title="Azure FinOps Validation Report",
    )

    story = []
    cover_page(story, styles, args.title, findings_doc)
    summary_section(story, styles, findings_doc)
    access_coverage_section(story, styles, preflight_doc)
    savings_summary_section(story, styles, findings_doc, ruleset)
    findings_table_section(story, styles, findings_doc)
    reservation_section(story, styles, findings_doc)
    log_cost_section(story, styles, findings_doc)
    remediation_section(story, styles, findings_doc)
    policy_guardrails_section(story, styles, findings_doc, guardrails_doc)
    appendix_section(story, styles, ruleset)

    doc.build(story)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
