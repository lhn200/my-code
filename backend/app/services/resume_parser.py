"""Resume ingestion: validate, store and normalize PDF / DOCX / image input."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from ..config import Settings
from .ocr import OCRError, ocr_pil_image, render_pdf_page

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}

_ALLOWED_MIME: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
}

_IMAGE_FORMATS: dict[str, set[str]] = {
    ".png": {"PNG"},
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".webp": {"WEBP"},
}

_PDF_TEXT_MIN_CHARS = 10


class ResumeParseError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedResume:
    file_id: str
    stored_path: Path
    original_filename: str
    text: str
    source_type: str
    page_count: int
    used_ocr: bool
    char_count: int
    low_confidence: bool

    def to_response(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_url": None,
            "source_type": self.source_type,
            "page_count": self.page_count,
            "used_ocr": self.used_ocr,
            "char_count": self.char_count,
            "low_confidence": self.low_confidence,
            "text": self.text,
        }


def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _suffix(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_upload(
    filename: str, content_type: str | None, size: int, settings: Settings
) -> str:
    """Validate name / mime / size and return the normalized suffix."""
    suffix = _suffix(filename)
    if not suffix:
        raise ResumeParseError(
            "resume_unsupported_type",
            f"unsupported file type; supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    if suffix == ".doc":
        raise ResumeParseError("resume_unsupported_type", "only .docx is supported, not .doc")
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ResumeParseError(
            "resume_unsupported_type",
            f"unsupported file type; supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime != "application/octet-stream" and mime not in _ALLOWED_MIME[suffix]:
        raise ResumeParseError(
            "resume_type_mismatch",
            f"content type {mime} does not match extension {suffix}",
        )

    if size <= 0:
        raise ResumeParseError("resume_empty", "the uploaded file is empty")
    if size > settings.resume_max_file_bytes:
        raise ResumeParseError(
            "resume_too_large",
            f"file exceeds the {settings.resume_max_file_mb:g}MB limit",
        )
    return suffix


def _parse_pdf(data: bytes, settings: Settings) -> tuple[str, int, bool]:
    if not data.startswith(b"%PDF"):
        raise ResumeParseError("resume_type_mismatch", "the file is not a valid PDF")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ResumeParseError("resume_encrypted", "encrypted PDFs are not supported")
        pages = list(reader.pages)
    except ResumeParseError:
        raise
    except Exception as exc:
        raise ResumeParseError("resume_unreadable", "the PDF could not be opened") from exc

    texts: list[str] = []
    used_ocr = False
    ocr_pages = 0
    for index, page in enumerate(pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if len(normalize_text(page_text)) < _PDF_TEXT_MIN_CHARS:
            ocr_pages += 1
            if ocr_pages > settings.ocr_max_pages:
                raise ResumeParseError(
                    "resume_ocr_limit",
                    f"OCR is limited to {settings.ocr_max_pages} pages per resume",
                )
            try:
                image = render_pdf_page(data, index)
                ocr_text = ocr_pil_image(image)
            except OCRError as exc:
                raise ResumeParseError("resume_unreadable", str(exc)) from exc
            except Exception as exc:
                raise ResumeParseError(
                    "resume_unreadable", "the PDF page could not be rendered for OCR"
                ) from exc
            if ocr_text.strip():
                used_ocr = True
                page_text = ocr_text
        texts.append(page_text)
    return "\n\n".join(texts), len(pages), used_ocr


def _parse_docx(data: bytes) -> tuple[str, int, bool]:
    if not data.startswith(b"PK\x03\x04"):
        raise ResumeParseError("resume_type_mismatch", "the file is not a valid DOCX")
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = Document(BytesIO(data))
    except Exception as exc:
        raise ResumeParseError("resume_unreadable", "the DOCX could not be opened") from exc

    parts: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            parts.append(Paragraph(child, document).text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
    return "\n".join(part for part in parts if part.strip()), 1, False


def _parse_image(data: bytes, suffix: str) -> tuple[str, int, bool]:
    try:
        from PIL import Image

        image = Image.open(BytesIO(data))
        image.load()
    except Exception as exc:
        raise ResumeParseError("resume_unreadable", "the image could not be opened") from exc
    if image.format not in _IMAGE_FORMATS[suffix]:
        raise ResumeParseError(
            "resume_type_mismatch",
            f"image content does not match extension {suffix}",
        )
    try:
        text = ocr_pil_image(image)
    except OCRError as exc:
        raise ResumeParseError("resume_unreadable", str(exc)) from exc
    return text, 1, True


def parse_bytes(suffix: str, data: bytes, settings: Settings) -> tuple[str, int, bool, str]:
    source_type = SUPPORTED_EXTENSIONS[suffix]
    if suffix == ".pdf":
        text, pages, used_ocr = _parse_pdf(data, settings)
    elif suffix == ".docx":
        text, pages, used_ocr = _parse_docx(data)
    else:
        text, pages, used_ocr = _parse_image(data, suffix)
    return normalize_text(text), pages, used_ocr, source_type


def ingest_resume(
    filename: str, content_type: str | None, data: bytes, settings: Settings
) -> ParsedResume:
    """Validate, persist the original and return normalized text."""
    suffix = validate_upload(filename, content_type, len(data), settings)
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    stored_path = upload_dir / f"{file_id}{suffix}"
    stored_path.write_bytes(data)

    try:
        text, pages, used_ocr, source_type = parse_bytes(suffix, data, settings)
        if not text:
            raise ResumeParseError(
                "resume_no_text",
                "no usable text was extracted; paste the resume text instead",
            )
    except ResumeParseError:
        stored_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        raise ResumeParseError("resume_unreadable", "the resume could not be parsed") from exc

    return ParsedResume(
        file_id=file_id,
        stored_path=stored_path,
        original_filename=filename,
        text=text,
        source_type=source_type,
        page_count=pages,
        used_ocr=used_ocr,
        char_count=len(text),
        low_confidence=used_ocr and len(text) < settings.ocr_min_chars,
    )


def delete_resume_file(file_id: str, settings: Settings) -> bool:
    """Delete a stored original by file_id; repeated calls are idempotent."""
    if not file_id or Path(file_id).name != file_id:
        return False
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.exists():
        return False
    deleted = False
    for path in upload_dir.glob(f"{file_id}.*"):
        if path.is_file():
            path.unlink(missing_ok=True)
            deleted = True
    return deleted


__all__ = [
    "ParsedResume",
    "ResumeParseError",
    "SUPPORTED_EXTENSIONS",
    "delete_resume_file",
    "ingest_resume",
    "normalize_text",
    "parse_bytes",
    "validate_upload",
]
