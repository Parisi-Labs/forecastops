from __future__ import annotations

from pathlib import Path

from forecastops.cli.main import _read_schema


def test_empty_schema_file_means_infer(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yaml"
    schema.write_text("", encoding="utf-8")

    assert _read_schema(schema) is None

