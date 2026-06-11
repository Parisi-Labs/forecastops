from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LocalStore:
    root: Path

    @classmethod
    def from_path(cls, path: str | Path | None = None) -> "LocalStore":
        if path is None:
            path = os.environ.get("FOPS_LOCAL_STORE", ".forecastops")
        return cls(Path(path).expanduser().resolve())

    @property
    def db_path(self) -> Path:
        return self.root / "forecastops.duckdb"

    @property
    def forecasts_dir(self) -> Path:
        return self.root / "artifacts" / "forecasts"

    @property
    def actuals_dir(self) -> Path:
        return self.root / "artifacts" / "actuals"

    @property
    def benchmarks_dir(self) -> Path:
        return self.root / "artifacts" / "benchmarks"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def traces_dir(self) -> Path:
        return self.root / "traces"

    def init(self) -> None:
        for directory in [
            self.root,
            self.forecasts_dir,
            self.actuals_dir,
            self.benchmarks_dir,
            self.reports_dir,
            self.traces_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

