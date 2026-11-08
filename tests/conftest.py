from __future__ import annotations

import os
import pathlib

import pytest

os.environ.setdefault("DATA_DIR", str(pathlib.Path(__file__).resolve().parent / "test_data"))
os.environ.setdefault("AI_PROVIDER", "none")


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    for sub in ("uploads", "exports", "generated", "extracted"):
        (d / sub).mkdir()
    return d


@pytest.fixture()
def store(data_dir, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    from backend.document_store import DocumentStore

    s = DocumentStore()
    yield s
    try:
        s.close()
    except Exception:
        pass
