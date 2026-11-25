from __future__ import annotations

from tests.test_resume_ingestion import make_png, make_text_pdf


def _upload(client, name: str, data: bytes, content_type: str):
    return client.post(
        "/api/resumes",
        files={"file": (name, data, content_type)},
    )


def test_upload_text_pdf(client) -> None:
    response = _upload(client, "resume.pdf", make_text_pdf(["Python SQL"]), "application/pdf")
    assert response.status_code == 200
    body = response.json()
    assert body["file_id"]
    assert body["source_type"] == "pdf"
    assert body["page_count"] == 1
    assert body["used_ocr"] is False
    assert "Python SQL" in body["text"]
    assert body["char_count"] == len(body["text"])


def test_upload_unsupported_type(client) -> None:
    response = _upload(client, "resume.txt", b"hello", "text/plain")
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "resume_unsupported_type"
    assert body["fields"][0]["field"] == "file"


def test_upload_doc_rejected(client) -> None:
    response = _upload(client, "resume.doc", b"legacy", "application/msword")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resume_unsupported_type"


def test_upload_corrupt_pdf(client) -> None:
    response = _upload(client, "resume.pdf", b"not-a-pdf", "application/pdf")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resume_type_mismatch"


def test_upload_mime_mismatch(client) -> None:
    response = _upload(client, "resume.pdf", make_text_pdf(["x"]), "image/png")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resume_type_mismatch"


def test_upload_oversized(client, settings) -> None:
    oversized = b"x" * (settings.resume_max_file_bytes + 1)
    response = _upload(client, "resume.pdf", oversized, "application/pdf")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resume_too_large"


def test_upload_image(client, monkeypatch) -> None:
    from app.services import resume_parser

    monkeypatch.setattr(
        resume_parser, "ocr_pil_image", lambda image: "Python engineer with API experience"
    )
    response = _upload(client, "resume.png", make_png(), "image/png")
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "image"
    assert body["used_ocr"] is True
