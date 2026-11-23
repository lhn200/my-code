from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from tests.fakes import DEFAULT_HANDLERS, FakeModels, make_context


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        checkpoint_db_path=tmp_path / "checkpoints.sqlite3",
        upload_dir=tmp_path / "uploads",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def fake(settings: Settings):
    context, models = make_context(settings, DEFAULT_HANDLERS)
    return context, models


@pytest.fixture
def fake_client(settings: Settings):
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as test_client:
        test_client.models = models
        yield test_client
