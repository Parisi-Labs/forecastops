from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from forecastops.core.run import ArtifactRecord, utc_now
from forecastops.store.local import LocalStore


def write_dataframe_artifact(
    frame: pd.DataFrame,
    *,
    store: LocalStore,
    run_id: str,
    artifact_type: str,
) -> ArtifactRecord:
    directory = {
        "forecast": store.forecasts_dir,
        "actuals": store.actuals_dir,
        "benchmark": store.benchmarks_dir,
    }[artifact_type]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}.parquet"
    frame.to_parquet(path, index=False)
    stat = path.stat()
    schema = _dataframe_schema(frame)
    digest = sha256_file(path)
    return ArtifactRecord(
        artifact_id=f"{run_id}:{artifact_type}",
        run_id=run_id,
        artifact_type=artifact_type,
        uri=str(path),
        content_type="application/vnd.apache.parquet",
        row_count=len(frame),
        byte_size=stat.st_size,
        schema=schema,
        sha256=digest,
        created_at=utc_now(),
    )


def read_artifact(uri: str | Path) -> pd.DataFrame:
    return pd.read_parquet(Path(uri))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataframe_schema(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": [
            {"name": column, "dtype": str(dtype)}
            for column, dtype in zip(frame.columns, frame.dtypes, strict=False)
        ]
    }

