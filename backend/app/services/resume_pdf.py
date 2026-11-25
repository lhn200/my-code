"""Render a resume variant (Markdown or plain text) into a downloadable PDF."""

from __future__ import annotations

import io
import re
from datetime import date
from functools import partial
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

_FONT_NAME = "STSong-Light"
_FONT_READY = False
_MARGIN = 18 * mm

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\d{1,3})[.)、]\s+(.*)$")
_RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_CODE_RE = re.compile(r"`([^`]+)`")


def _register_font() -> str:
    global _FONT_READY
    if not _FONT_READY:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(_FONT_NAME))
            pdfmetrics.registerFontFamily(
                _FONT_NAME,
                normal=_FONT_NAME,
                bold=_FONT_NAME,
                italic=_FONT_NAME,
                boldItalic=_FONT_NAME,
            )
        except Exception:  # pragma: no cover - fallback when CID font is unavailable
            pass
        _FONT_READY = True
    return _FONT_NAME if _FONT_NAME in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    escaped = _escape(text)
    escaped = _CODE_RE.sub(r'<font face="Courier">\1</font>', escaped)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    return escaped


def _styles(font: str) -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "ResumeBody",
        fontName=font,
        fontSize=9.5,
        leading=15,
        textColor=colors.HexColor("#1F2328"),
        wordWrap="CJK",
        spaceAfter=2,
    )
    return {
        "body": body,
        "title": ParagraphStyle(
            "ResumeTitle", parent=body, fontSize=17, leading=24, spaceAfter=3
        ),
        "meta": ParagraphStyle(
            "ResumeMeta",
            parent=body,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#6B7280"),
        ),
        "h1": ParagraphStyle(
            "ResumeH1", parent=body, fontSize=14, leading=21, spaceBefore=12, spaceAfter=4
        ),
        "h2": ParagraphStyle(
            "ResumeH2", parent=body, fontSize=12, leading=18, spaceBefore=10, spaceAfter=3
        ),
        "h3": ParagraphStyle(
            "ResumeH3", parent=body, fontSize=10.5, leading=16, spaceBefore=8, spaceAfter=2
        ),
        "bullet": ParagraphStyle(
            "ResumeBullet",
            parent=body,
            leftIndent=14,
            bulletIndent=3,
            bulletFontName=font,
            bulletFontSize=9.5,
            spaceAfter=1,
        ),
        "code": ParagraphStyle(
            "ResumeCode",
            fontName="Courier",
            fontSize=8,
            leading=11.5,
            textColor=colors.HexColor("#374151"),
            backColor=colors.HexColor("#F3F4F6"),
            borderPadding=3,
            spaceBefore=2,
            spaceAfter=4,
        ),
    }


def _body_flowables(text: str, styles: dict[str, ParagraphStyle]) -> list[Any]:
    flowables: list[Any] = []
    paragraph: list[str] = []
    in_code = False

    def flush_body() -> None:
        if not paragraph:
            return
        style = styles["code"] if in_code else styles["body"]
        flowables.append(Paragraph("<br/>".join(paragraph), style))
        paragraph.clear()

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_body()
            in_code = not in_code
            continue
        if in_code:
            paragraph.append(_escape(line if line else " "))
            continue
        if not stripped:
            flush_body()
            continue
        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_body()
            level = min(len(heading.group(1)), 3)
            style = styles["h1"] if level == 1 else styles["h2"] if level == 2 else styles["h3"]
            flowables.append(Paragraph(_inline(heading.group(2).strip()), style))
            continue
        if _RULE_RE.match(stripped):
            flush_body()
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=0.6,
                    color=colors.HexColor("#D8D3C6"),
                    spaceBefore=6,
                    spaceAfter=6,
                )
            )
            continue
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            flush_body()
            flowables.append(
                Paragraph(_inline(bullet.group(1)), styles["bullet"], bulletText="•")
            )
            continue
        ordered = _ORDERED_RE.match(stripped)
        if ordered:
            flush_body()
            flowables.append(
                Paragraph(
                    _inline(ordered.group(2)),
                    styles["bullet"],
                    bulletText=f"{ordered.group(1)}.",
                )
            )
            continue
        paragraph.append(_inline(stripped))

    flush_body()
    return flowables


def _draw_footer(canvas: Any, doc: Any, font: str) -> None:
    canvas.saveState()
    canvas.setFont(font, 8)
    canvas.setFillColor(colors.HexColor("#8A8A8A"))
    canvas.drawRightString(A4[0] - _MARGIN, 11 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def render_resume_pdf(
    *,
    title: str,
    text: str,
    company: str = "",
    version: int = 0,
    score: int | None = None,
    source: str = "baseline",
) -> bytes:
    """Build an A4 PDF for one job's current resume text."""
    font = _register_font()
    styles = _styles(font)
    buffer = io.BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title=title or "Resume",
        author="Career Assistant",
    )

    meta: list[str] = []
    if company.strip():
        meta.append(_escape(company.strip()))
    meta.append(f"定制版本 v{version}" if source == "variant" and version else "基线简历")
    if score is not None:
        meta.append(f"岗位匹配分 {score}")
    meta.append(date.today().isoformat())

    story: list[Any] = [
        Paragraph(_escape(title.strip() or "个人简历"), styles["title"]),
        Paragraph(" · ".join(meta), styles["meta"]),
        Spacer(1, 6),
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor("#D8D3C6"),
            spaceBefore=0,
            spaceAfter=10,
        ),
    ]
    story.extend(_body_flowables(text or "", styles))
    if not text.strip():
        story.append(Paragraph("（暂无简历内容）", styles["meta"]))

    document.build(
        story,
        onFirstPage=partial(_draw_footer, font=font),
        onLaterPages=partial(_draw_footer, font=font),
    )
    return buffer.getvalue()


def resume_pdf_filename(title: str, version: int = 0) -> str:
    stem = _UNSAFE_FILENAME_RE.sub("_", (title or "").strip()).strip(" ._")
    if not stem:
        stem = "resume"
    stem = stem[:48]
    suffix = f"-v{version}" if version else ""
    return f"{stem}-简历{suffix}.pdf"


__all__ = ["render_resume_pdf", "resume_pdf_filename"]
