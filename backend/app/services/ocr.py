"""OCR and PDF page rendering helpers."""

from __future__ import annotations

from typing import Any


class OCRError(RuntimeError):
    """Raised when OCR cannot be performed."""


_engine: Any | None = None


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise OCRError("rapidocr-onnxruntime is not installed") from exc
        _engine = RapidOCR()
    return _engine


def ocr_pil_image(image: Any, min_score: float = 0.3) -> str:
    """Run OCR on a PIL image and return newline-joined text."""
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise OCRError("numpy is required for OCR") from exc

    engine = _get_engine()
    array = np.array(image.convert("RGB"))
    result = engine(array)
    lines: list[str] = []
    if isinstance(result, tuple):
        result = result[0]
    for item in result or []:
        if not item or len(item) < 3:
            continue
        text, score = item[1], item[2]
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = 0.0
        if text and confidence >= min_score:
            lines.append(str(text).strip())
    return "\n".join(line for line in lines if line)


def render_pdf_page(data: bytes, index: int, scale: float = 2.0) -> Any:
    """Render one PDF page to a PIL image using pypdfium2."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise OCRError("pypdfium2 is not installed") from exc
    document = pdfium.PdfDocument(data)
    try:
        page = document[index]
        return page.render(scale=scale).to_pil()
    finally:
        document.close()


__all__ = ["OCRError", "ocr_pil_image", "render_pdf_page"]
