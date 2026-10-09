#!/usr/bin/env python3
"""
FormFlow Report Generator — Creates branded PDF completion reports
following organization standards (8.5x11 portrait, centered headers,
bold labels, bullet points, infographics).

Usage:
    python scripts/formflow_generate_report.py \
        --session-data session.json \
        --output FormFlow_Report.pdf
"""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.graphics.shapes import Drawing, Circle, Wedge, String, Group
    from reportlab.graphics import renderPDF
except ImportError:
    print("ERROR: reportlab not installed. Run: pip install reportlab")
    sys.exit(1)


BRAND_PRIMARY = colors.HexColor("#1a365d")
BRAND_SECONDARY = colors.HexColor("#2b6cb0")
BRAND_ACCENT = colors.HexColor("#38a169")
BRAND_WARNING = colors.HexColor("#d69e2e")
BRAND_ERROR = colors.HexColor("#e53e3e")
BRAND_LIGHT = colors.HexColor("#f7fafc")
BRAND_TEXT = colors.HexColor("#2d3748")

PAGE_WIDTH, PAGE_HEIGHT = letter


def create_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        leading=28,
        alignment=1,
        textColor=BRAND_PRIMARY,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    ))

    styles.add(ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=12,
        leading=16,
        alignment=1,
        textColor=BRAND_SECONDARY,
        spaceAfter=20,
    ))

    styles.add(ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        alignment=1,
        textColor=BRAND_PRIMARY,
        spaceBefore=16,
        spaceAfter=8,
        fontName="Helvetica-Bold",
    ))

    styles.add(ParagraphStyle(
        "BoldLabel",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        fontName="Helvetica-Bold",
        textColor=BRAND_TEXT,
    ))

    styles.add(ParagraphStyle(
        "BulletItem",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        leftIndent=20,
        bulletIndent=8,
        textColor=BRAND_TEXT,
    ))

    styles.add(ParagraphStyle(
        "FooterStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.gray,
    ))

    return styles


def create_completion_ring(percentage, size=120):
    d = Drawing(size, size)
    cx, cy = size / 2, size / 2
    radius = size / 2 - 10

    d.add(Circle(cx, cy, radius, strokeColor=colors.HexColor("#e2e8f0"),
                 strokeWidth=8, fillColor=None))

    if percentage > 0:
        start_angle = 90
        extent = percentage * 3.6
        color = BRAND_ACCENT if percentage >= 80 else (
            BRAND_WARNING if percentage >= 50 else BRAND_ERROR
        )
        d.add(Wedge(cx, cy, radius, start_angle, start_angle - extent,
                     strokeColor=color, strokeWidth=8, fillColor=None))

    label = String(cx, cy - 4, f"{percentage}%",
                   fontSize=16, fontName="Helvetica-Bold",
                   fillColor=BRAND_PRIMARY, textAnchor="middle")
    d.add(label)

    sub = String(cx, cy - 16, "Complete",
                 fontSize=8, fontName="Helvetica",
                 fillColor=colors.gray, textAnchor="middle")
    d.add(sub)

    return d


def create_category_bar(categories, size_w=400, size_h=100):
    d = Drawing(size_w, size_h)
    if not categories:
        return d

    max_val = max(categories.values()) if categories else 1
    bar_h = 14
    spacing = 4
    y = size_h - 20

    cat_colors = {
        "personal": BRAND_PRIMARY,
        "contact": BRAND_SECONDARY,
        "address": colors.HexColor("#4c51bf"),
        "employment": colors.HexColor("#2b6cb0"),
        "education": colors.HexColor("#2c7a7b"),
        "financial": BRAND_WARNING,
        "medical": colors.HexColor("#9b2c2c"),
        "legal": colors.HexColor("#744210"),
        "business": BRAND_ACCENT,
        "other": colors.gray,
    }

    for cat, count in sorted(categories.items()):
        if y < 10:
            break
        bar_w = (count / max_val) * (size_w - 120) if max_val > 0 else 0
        color = cat_colors.get(cat, colors.gray)

        from reportlab.graphics.shapes import Rect
        d.add(String(0, y, cat.capitalize()[:12],
                     fontSize=8, fontName="Helvetica", fillColor=BRAND_TEXT))
        d.add(Rect(90, y - 2, bar_w, bar_h, fillColor=color,
                   strokeColor=None))
        d.add(String(95 + bar_w, y, str(count),
                     fontSize=8, fontName="Helvetica-Bold", fillColor=BRAND_TEXT))
        y -= (bar_h + spacing)

    return d


def build_report(session_data, output_path):
    styles = create_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    story = []

    story.append(Paragraph("FormFlow Completion Report", styles["ReportTitle"]))

    form_name = session_data.get("form_name", "Document")
    timestamp = session_data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))
    story.append(Paragraph(
        f"{form_name} &mdash; Generated {timestamp}",
        styles["ReportSubtitle"],
    ))

    story.append(Spacer(1, 12))

    story.append(Paragraph("Session Summary", styles["SectionHeader"]))

    total = session_data.get("fields_total", 0)
    filled = session_data.get("fields_filled", 0)
    pct = round((filled / total * 100) if total > 0 else 0)
    avg_conf = session_data.get("confidence_avg", 0)
    issues_count = len(session_data.get("issues", []))

    summary_data = [
        ["<b>Total Fields Detected</b>", str(total)],
        ["<b>Fields Filled</b>", str(filled)],
        ["<b>Completion Rate</b>", f"{pct}%"],
        ["<b>Average Confidence</b>", f"{avg_conf:.0f}%"],
        ["<b>Issues Found</b>", str(issues_count)],
        ["<b>Fill Method</b>", session_data.get("method", "auto")],
    ]

    summary_table = Table(
        [[Paragraph(row[0], styles["BoldLabel"]),
          Paragraph(row[1], styles["Normal"])] for row in summary_data],
        colWidths=[3 * inch, 4 * inch],
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Completion Overview", styles["SectionHeader"]))

    ring = create_completion_ring(pct, 120)
    ring_table = Table([[ring]], colWidths=[7 * inch])
    ring_table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(ring_table)
    story.append(Spacer(1, 12))

    categories = session_data.get("categories", {})
    if categories:
        story.append(Paragraph("Knowledge Base Categories", styles["SectionHeader"]))
        bar = create_category_bar(categories, 450, max(len(categories) * 20, 60))
        bar_table = Table([[bar]], colWidths=[7 * inch])
        bar_table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(bar_table)
        story.append(Spacer(1, 12))

    issues = session_data.get("issues", [])
    if issues:
        story.append(Paragraph("Issues & Warnings", styles["SectionHeader"]))

        severity_icons = {"error": "(!)", "warning": "(!)", "info": "(i)"}
        severity_colors = {
            "error": BRAND_ERROR,
            "warning": BRAND_WARNING,
            "info": BRAND_SECONDARY,
        }

        issue_data = [["<b>Severity</b>", "<b>Field</b>", "<b>Issue</b>"]]
        for issue in issues[:20]:
            sev = issue.get("severity", "info").upper()
            field = issue.get("field", "—")
            msg = issue.get("message", "")
            issue_data.append([sev, field, msg])

        issue_table = Table(
            [[Paragraph(cell, styles["Normal"]) for cell in row] for row in issue_data],
            colWidths=[1.2 * inch, 1.8 * inch, 4 * inch],
        )
        issue_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 1), (-1, -1), BRAND_LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(issue_table)
        story.append(Spacer(1, 12))

    filled_fields = session_data.get("filled_fields", [])
    if filled_fields:
        story.append(Paragraph("Filled Fields Detail", styles["SectionHeader"]))

        field_data = [["<b>Field</b>", "<b>Value</b>", "<b>Confidence</b>", "<b>Source</b>"]]
        for ff in filled_fields[:40]:
            conf = ff.get("confidence", 0)
            conf_str = f"{conf}%"
            field_data.append([
                ff.get("field_name_raw", ff.get("field_name", "")),
                ff.get("field_value", ""),
                conf_str,
                ff.get("source", "kb"),
            ])

        field_table = Table(
            [[Paragraph(cell, styles["Normal"]) for cell in row] for row in field_data],
            colWidths=[1.8 * inch, 2.5 * inch, 1.2 * inch, 1.5 * inch],
        )
        field_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 1), (-1, -1), BRAND_LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(field_table)

    story.append(Spacer(1, 24))
    story.append(Paragraph(
        f"FormFlow Report &bull; Generated {timestamp} &bull; NTXP LLC",
        styles["FooterStyle"],
    ))

    doc.build(story)
    print(f"Report saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="FormFlow Report Generator")
    parser.add_argument("--session-data", required=True, help="Session data JSON")
    parser.add_argument("--output", required=True, help="Output PDF path")
    args = parser.parse_args()

    data_path = Path(args.session_data)
    if not data_path.exists():
        print(f"ERROR: Session data not found: {data_path}")
        sys.exit(1)

    with open(data_path) as f:
        session_data = json.load(f)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    build_report(session_data, str(output_path))


if __name__ == "__main__":
    main()
