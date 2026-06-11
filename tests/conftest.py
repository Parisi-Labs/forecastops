from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / ".forecastops"
    monkeypatch.setenv("FOPS_LOCAL_STORE", str(store))
    return store


@pytest.fixture(autouse=True)
def clear_otel_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("FOPS_OTEL_"):
            monkeypatch.delenv(key, raising=False)

