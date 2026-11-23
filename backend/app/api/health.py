from fastapi import APIRouter, Request

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    schema = getattr(request.app.state, "schema", None)
    return {
        "status": "ok",
        "schema_version": getattr(schema, "version", 0),
        "fts5_enabled": bool(getattr(schema, "fts5_enabled", False)),
    }
