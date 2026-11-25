"""Resume upload and text extraction endpoint."""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from ..errors import ApiError, field_error
from ..services.resume_parser import ResumeParseError, ingest_resume

router = APIRouter(tags=["resumes"])


@router.post("/resumes")
async def upload_resume(request: Request, file: UploadFile = File(...)) -> dict:
    settings = request.app.state.settings
    if file.size is not None and file.size > settings.resume_max_file_bytes:
        message = f"file exceeds the {settings.resume_max_file_mb:g}MB limit"
        raise ApiError(
            422, "resume_too_large", message, [field_error("file", "resume_too_large", message)]
        )
    data = await file.read()
    if len(data) > settings.resume_max_file_bytes:
        message = f"file exceeds the {settings.resume_max_file_mb:g}MB limit"
        raise ApiError(
            422, "resume_too_large", message, [field_error("file", "resume_too_large", message)]
        )
    try:
        parsed = ingest_resume(
            file.filename or "",
            file.content_type,
            data,
            settings,
        )
    except ResumeParseError as exc:
        raise ApiError(
            422, exc.code, exc.message, [field_error("file", exc.code, exc.message)]
        ) from exc
    return parsed.to_response()


__all__ = ["router"]
