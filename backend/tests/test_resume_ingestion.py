from __future__ import annotations

import json
import shutil
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.checkpoint.sqlite import new_thread_id, open_checkpointer, thread_config
from app.config import Settings
from app.graph.main import build_initial_state, build_main_graph
from app.main import create_app
from app.services import resume_parser
from app.services.resume_parser import (
    ResumeParseError,
    delete_resume_file,
    ingest_resume,
)
from tests.fakes import DEFAULT_HANDLERS, FakeModels, make_context


def make_text_pdf(pages: list[str]) -> bytes:
    objects: list[bytes | None] = [None]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_ids = [3 + 2 * index for index in range(len(pages))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + 2 * len(pages)
    for index, text in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index in range(1, len(objects)):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + objects[index] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects)}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_png() -> bytes:
    image = Image.new("RGB", (240, 90), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_docx() -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph("Lead backend engineer with Python")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Skills"
    table.cell(0, 1).text = "Python, SQL"
    table.cell(1, 0).text = "Projects"
    table.cell(1, 1).text = "Built an API gateway"
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _settings(settings: Settings, **updates) -> Settings:
    return settings.model_copy(update=updates)


def test_text_pdf_preserves_page_order(settings) -> None:
    parsed = ingest_resume(
        "resume.pdf", "application/pdf", make_text_pdf(["Python SQL", "Second page"]), settings
    )
    assert parsed.source_type == "pdf"
    assert parsed.page_count == 2
    assert parsed.used_ocr is False
    assert parsed.low_confidence is False
    assert parsed.text.index("Python SQL") < parsed.text.index("Second page")


def test_docx_reads_paragraphs_and_tables(settings) -> None:
    parsed = ingest_resume(
        "resume.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        make_docx(),
        settings,
    )
    assert parsed.source_type == "docx"
    assert "Lead backend engineer" in parsed.text
    assert "Python, SQL" in parsed.text
    assert "Built an API gateway" in parsed.text


def test_doc_extension_rejected(settings) -> None:
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("resume.doc", "application/msword", b"data", settings)
    assert excinfo.value.code == "resume_unsupported_type"


def test_image_ocr_sets_flags(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        resume_parser, "ocr_pil_image", lambda image: "Python engineer with five years of experience"
    )
    parsed = ingest_resume("resume.png", "image/png", make_png(), settings)
    assert parsed.source_type == "image"
    assert parsed.used_ocr is True
    assert parsed.low_confidence is False
    assert parsed.page_count == 1


def test_short_ocr_text_is_low_confidence(settings, monkeypatch) -> None:
    monkeypatch.setattr(resume_parser, "ocr_pil_image", lambda image: "Python")
    parsed = ingest_resume("resume.png", "image/png", make_png(), settings)
    assert parsed.low_confidence is True


def test_image_without_text_fails_and_cleans_up(settings, monkeypatch) -> None:
    monkeypatch.setattr(resume_parser, "ocr_pil_image", lambda image: "   ")
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("resume.png", "image/png", make_png(), settings)
    assert excinfo.value.code == "resume_no_text"
    assert list(settings.upload_dir.glob("*")) == []


def test_scanned_pdf_uses_ocr(settings, monkeypatch) -> None:
    monkeypatch.setattr(
        resume_parser, "render_pdf_page", lambda data, index: Image.new("RGB", (100, 100))
    )
    monkeypatch.setattr(
        resume_parser, "ocr_pil_image", lambda image: "OCR extracted resume text"
    )
    parsed = ingest_resume("scan.pdf", "application/pdf", make_text_pdf([""]), settings)
    assert parsed.used_ocr is True
    assert "OCR extracted resume text" in parsed.text


def test_mixed_pdf_uses_ocr_only_for_blank_pages(settings, monkeypatch) -> None:
    def render(data, index):
        return Image.new("RGB", (100, 100))

    calls: list[int] = []

    def ocr(image):
        calls.append(1)
        return "OCR page two"

    monkeypatch.setattr(resume_parser, "render_pdf_page", render)
    monkeypatch.setattr(resume_parser, "ocr_pil_image", ocr)
    parsed = ingest_resume(
        "mixed.pdf", "application/pdf", make_text_pdf(["Text layer page", ""]), settings
    )
    assert parsed.used_ocr is True
    assert parsed.text.index("Text layer page") < parsed.text.index("OCR page two")
    assert len(calls) == 1


def test_ocr_page_limit(settings, monkeypatch) -> None:
    limited = _settings(settings, ocr_max_pages=1)
    monkeypatch.setattr(
        resume_parser, "render_pdf_page", lambda data, index: Image.new("RGB", (50, 50))
    )
    monkeypatch.setattr(resume_parser, "ocr_pil_image", lambda image: "text")
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("scan.pdf", "application/pdf", make_text_pdf(["", ""]), limited)
    assert excinfo.value.code == "resume_ocr_limit"
    assert list(limited.upload_dir.glob("*")) == []


def test_encrypted_pdf_rejected(settings) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("secret.pdf", "application/pdf", buffer.getvalue(), settings)
    assert excinfo.value.code == "resume_encrypted"


def test_oversized_file_rejected_before_write(settings) -> None:
    oversized = b"x" * (settings.resume_max_file_bytes + 10)
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("big.pdf", "application/pdf", oversized, settings)
    assert excinfo.value.code == "resume_too_large"
    assert not settings.upload_dir.exists() or list(settings.upload_dir.glob("*")) == []


def test_type_spoofing_rejected_and_cleaned(settings) -> None:
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("fake.pdf", "application/pdf", b"not a pdf", settings)
    assert excinfo.value.code == "resume_type_mismatch"
    assert list(settings.upload_dir.glob("*")) == []


def test_mime_extension_mismatch_rejected(settings) -> None:
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("resume.pdf", "image/png", make_text_pdf(["text"]), settings)
    assert excinfo.value.code == "resume_type_mismatch"


def test_empty_file_rejected(settings) -> None:
    with pytest.raises(ResumeParseError) as excinfo:
        ingest_resume("resume.pdf", "application/pdf", b"", settings)
    assert excinfo.value.code == "resume_empty"


def test_filename_traversal_is_not_used(settings) -> None:
    parsed = ingest_resume(
        "../../evil.pdf", "application/pdf", make_text_pdf(["Python resume"]), settings
    )
    assert parsed.stored_path.parent == settings.upload_dir
    assert parsed.stored_path.name.startswith(parsed.file_id)
    assert ".." not in parsed.stored_path.name


def test_delete_is_idempotent(settings) -> None:
    parsed = ingest_resume(
        "resume.pdf", "application/pdf", make_text_pdf(["Python resume"]), settings
    )
    assert parsed.stored_path.exists()
    assert delete_resume_file(parsed.file_id, settings) is True
    assert delete_resume_file(parsed.file_id, settings) is False


def test_upload_and_paste_are_equivalent(settings, monkeypatch) -> None:
    monkeypatch.setattr(resume_parser, "ocr_pil_image", lambda image: "Python SQL")
    job = {"title": "Backend Engineer", "original_position_text": "Python SQL"}
    cases = [
        ("resume.pdf", "application/pdf", make_text_pdf(["Python SQL"]), "Python SQL"),
        (
            "resume.docx",
            DOCX_MIME,
            make_docx(),
            "Lead backend engineer with Python\nSkills | Python, SQL\n"
            "Projects | Built an API gateway",
        ),
        ("resume.png", "image/png", make_png(), "Python SQL"),
    ]
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        for name, mime, data, literal in cases:
            parsed = ingest_resume(name, mime, data, settings)
            assert parsed.text == literal
            uploaded = client.post(
                "/api/runs",
                json={"goal": "后端", "resume_text": parsed.text, "jobs": [job]},
            ).json()
            pasted = client.post(
                "/api/runs",
                json={"goal": "后端", "resume_text": literal, "jobs": [job]},
            ).json()
            assert uploaded["jobs"][0]["review"] == pasted["jobs"][0]["review"]
            assert uploaded["jobs"][0]["resume_text"] == pasted["jobs"][0]["resume_text"]


def test_deleted_upload_dir_does_not_block_startup_or_runs(settings) -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(settings.upload_dir)

    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        assert client.get("/api/health").status_code == 200
        response = client.post(
            "/api/runs",
            json={
                "goal": "后端",
                "resume_text": "Python SQL",
                "jobs": [{"title": "Backend Engineer", "original_position_text": "Python SQL"}],
            },
        )
        assert response.status_code == 200
    assert not settings.upload_dir.exists() or list(settings.upload_dir.glob("*")) == []


async def test_checkpoint_stores_file_reference_not_binary(settings) -> None:
    parsed = ingest_resume(
        "resume.pdf", "application/pdf", make_text_pdf(["Python resume"]), settings
    )
    async with open_checkpointer(settings.checkpoint_db_path) as saver:
        context, _ = make_context(settings, DEFAULT_HANDLERS)
        graph = build_main_graph(context, checkpointer=saver)
        thread_id = new_thread_id()
        config = thread_config(thread_id)
        await graph.ainvoke(
            build_initial_state(
                "后端",
                parsed.text,
                [{"job_id": "job-1", "title": "Backend", "original_position_text": "Python"}],
                resume_file_id=parsed.file_id,
            ),
            config=config,
        )
        state = (await graph.aget_state(config)).values
    serialized = json.dumps(state, ensure_ascii=False)
    assert state["resume_file_id"] == parsed.file_id
    assert parsed.file_id in serialized
    assert "iVBOR" not in serialized
    assert "JVBERi0" not in serialized
    assert "base64" not in serialized.lower()
