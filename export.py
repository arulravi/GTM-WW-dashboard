"""
Export helpers: produce leader-ready files from the assembled walk.

  * to_excel  -> formatted .xlsx (walk + HC + per-head + variances)
  * to_pdf    -> one/two page PDF summary for email
  * to_csv    -> raw walk as CSV

All functions return bytes so the Streamlit layer can offer them as downloads
without touching the filesystem.
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd


def to_csv(walk: pd.DataFrame) -> bytes:
    return walk.round(1).to_csv().encode("utf-8")


def to_excel(
    walk: pd.DataFrame,
    hc_row: pd.Series,
    per_head: pd.DataFrame,
    variances: pd.DataFrame,
    title: str,
    commentary: dict | None = None,
    ro: dict | None = None,
) -> bytes:
    commentary = commentary or {}
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xl:
        book = xl.book
        sheet = book.add_worksheet("Opex + HC Walk")
        xl.sheets["Opex + HC Walk"] = sheet

        fmt_title = book.add_format(
            {"bold": True, "font_size": 14, "font_color": "#1F3864"}
        )
        fmt_sub = book.add_format({"italic": True, "font_color": "#666666"})
        fmt_hdr = book.add_format(
            {"bold": True, "bg_color": "#1F3864", "font_color": "white",
             "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True}
        )
        fmt_rowlbl = book.add_format({"bold": True, "border": 1})
        fmt_num = book.add_format({"num_format": "#,##0.0", "border": 1})
        fmt_total = book.add_format(
            {"bold": True, "num_format": "#,##0.0", "border": 1, "bg_color": "#D9E1F2"}
        )
        fmt_total_lbl = book.add_format(
            {"bold": True, "border": 1, "bg_color": "#D9E1F2"}
        )
        fmt_hc = book.add_format({"num_format": "#,##0", "border": 1})

        sheet.write(0, 0, title, fmt_title)
        sheet.write(1, 0, f"Amount in $M  |  Generated {date.today():%d %b %Y}", fmt_sub)

        fmt_cmt = book.add_format({"border": 1, "text_wrap": True, "valign": "top"})

        start = 3
        cols = list(walk.columns)
        comment_col = len(cols) + 1
        sheet.write(start, 0, "Cost Element", fmt_hdr)
        for j, c in enumerate(cols):
            sheet.write(start, j + 1, str(c), fmt_hdr)
        sheet.write(start, comment_col, "Commentary", fmt_hdr)
        sheet.set_column(0, 0, 24)
        sheet.set_column(1, len(cols), 13)
        sheet.set_column(comment_col, comment_col, 55)

        r = start + 1
        for idx, row in walk.iterrows():
            is_total = str(idx) == "Total"
            sheet.write(r, 0, str(idx), fmt_total_lbl if is_total else fmt_rowlbl)
            for j, c in enumerate(cols):
                sheet.write_number(
                    r, j + 1, float(row[c]), fmt_total if is_total else fmt_num
                )
            sheet.write(r, comment_col, commentary.get(str(idx), ""), fmt_cmt)
            r += 1

        # Headcount block
        r += 1
        sheet.write(r, 0, "Headcount", fmt_total_lbl)
        for j, c in enumerate(cols):
            sheet.write(r, j + 1, float(hc_row[c]) if c in hc_row.index else "", fmt_hc)
        r += 2

        # Per-head metrics
        if not per_head.empty:
            sheet.write(r, 0, "Per Head Metrics ($'000s)", fmt_total_lbl)
            r += 1
            ph_cols = list(per_head.columns)
            sheet.write(r, 0, "", fmt_hdr)
            for j, c in enumerate(ph_cols):
                sheet.write(r, j + 1, str(c), fmt_hdr)
            r += 1
            for idx, row in per_head.iterrows():
                sheet.write(r, 0, str(idx), fmt_rowlbl)
                for j, c in enumerate(ph_cols):
                    sheet.write_number(r, j + 1, float(row[c]), fmt_num)
                r += 1

        # Risks & Opportunities block
        if ro:
            r += 1
            sheet.write(r, 0, "Risks & Opportunities", fmt_total_lbl)
            r += 1
            if ro.get("summary"):
                sheet.merge_range(r, 0, r, comment_col, "Summary: " + ro["summary"], fmt_cmt)
                r += 2
            wrap = book.add_format({"text_wrap": True, "valign": "top"})
            for label, items in (("Risks", ro.get("risks_text") or ro.get("risks", [])),
                                 ("Opportunities", ro.get("opps_text") or ro.get("opportunities", []))):
                sheet.write(r, 0, label, fmt_rowlbl)
                text = items if isinstance(items, str) else "\n".join(_strip_md(i) for i in items)
                sheet.merge_range(r, 1, r, comment_col, text, wrap)
                r += 1

        # Variances on its own sheet
        if not variances.empty:
            variances.round(2).to_excel(xl, sheet_name="Variances")

    buf.seek(0)
    return buf.getvalue()


def _strip_md(s: str) -> str:
    """Remove the markdown emphasis used in the on-screen bullets."""
    import re
    return re.sub(r"\*\*|⚠️ |✅ ", "", s).strip()


def to_pdf(walk: pd.DataFrame, hc_row: pd.Series, title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1 * cm, rightMargin=1 * cm, topMargin=1 * cm, bottomMargin=1 * cm,
    )
    styles = getSampleStyleSheet()
    elems = [
        Paragraph(title, styles["Title"]),
        Paragraph("Amount in $M", styles["Italic"]),
        Spacer(1, 0.4 * cm),
    ]

    cols = list(walk.columns)
    header = ["Cost Element"] + [str(c) for c in cols]
    data = [header]
    for idx, row in walk.iterrows():
        data.append([str(idx)] + [f"{row[c]:,.1f}" for c in cols])
    hc_line = ["Headcount"] + [
        (f"{hc_row[c]:,.0f}" if c in hc_row.index else "") for c in cols
    ]
    data.append(hc_line)

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#D9E1F2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    elems.append(table)
    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()
