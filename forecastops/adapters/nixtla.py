from __future__ import annotations

import re
import warnings
from typing import Any

import pandas as pd

from forecastops.adapters.base import ForecastAdapter
from forecastops.core.normalize import normalize_dataframe
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast
from forecastops.core.schema import ForecastSchema

RESERVED_COLUMNS = {"unique_id", "ds", "cutoff", "cutoff_time", "actual", "y"}

# statsforecast / neuralforecast emit interval columns as ``<model>-lo-<level>`` and
# ``<model>-hi-<level>`` where ``<level>`` is the integer prediction-interval width.
_INTERVAL_COLUMN = re.compile(r"^(?P<model>.+)-(?P<side>lo|hi)-(?P<level>\d+)$")


def _is_interval_column(column: str) -> bool:
    return _INTERVAL_COLUMN.match(column) is not None


def _level_to_quantiles(level: int) -> tuple[float, float] | None:
    """Map a symmetric interval ``level`` to its (lower, upper) percentile pair.

    A level ``L`` interval spans quantiles ``[(100 - L) / 2, (100 + L) / 2]``. Only
    levels that yield integer percentiles in ``1..99`` are returned (e.g. level 95 maps
    to 2.5/97.5 which is not an integer percentile, so it is skipped); ``None`` otherwise.
    """
    if (100 - level) % 2 != 0:
        return None
    lower = (100 - level) // 2
    upper = (100 + level) // 2
    if not (1 <= lower <= 99 and 1 <= upper <= 99):
        return None
    return float(lower), float(upper)


class NixtlaAdapter(ForecastAdapter):
    name = "nixtla"

    def detect(self, obj: Any) -> DetectionResult:
        if not isinstance(obj, pd.DataFrame):
            return DetectionResult(False, 0.0, "object is not a pandas DataFrame")
        columns = set(obj.columns)
        model_cols = [column for column in obj.columns if column not in RESERVED_COLUMNS]
        matched = {"unique_id", "ds"}.issubset(columns) and bool(model_cols)
        return DetectionResult(
            matched,
            0.9 if matched else 0.0,
            "Nixtla-style dataframe with unique_id, ds, model, and optional "
            "<model>-lo/hi-<level> prediction-interval columns"
            if matched
            else "missing unique_id/ds/model columns",
            [] if matched else ["unique_id", "ds", "model_col"],
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        if not isinstance(obj, pd.DataFrame):
            raise TypeError("nixtla adapter expects a pandas DataFrame")

        model_col = context.adapter_options.get("model_col")
        if model_col is None:
            candidates = [
                column
                for column in obj.columns
                if column not in RESERVED_COLUMNS and not _is_interval_column(str(column))
            ]
            if not candidates:
                raise ValueError("nixtla adapter requires at least one model output column")
            model_col = candidates[0]
        if model_col not in obj:
            raise ValueError(f"model_col {model_col!r} not present in dataframe")

        # Collect interval columns belonging to the selected point model only, keyed by
        # level -> {"lo": column, "hi": column}.
        intervals: dict[int, dict[str, str]] = {}
        for column in obj.columns:
            match = _INTERVAL_COLUMN.match(str(column))
            if match is None or match.group("model") != str(model_col):
                continue
            level = int(match.group("level"))
            intervals.setdefault(level, {})[match.group("side")] = str(column)

        # Map levels to quantile source columns so pinball loss can consume them.
        quantiles: dict[float, str] = {}
        skipped_levels: list[int] = []
        for level, sides in intervals.items():
            mapped = _level_to_quantiles(level)
            if mapped is None:
                skipped_levels.append(level)
                continue
            lower_q, upper_q = mapped
            if "lo" in sides:
                quantiles[lower_q / 100.0] = sides["lo"]
            if "hi" in sides:
                quantiles[upper_q / 100.0] = sides["hi"]
        if skipped_levels:
            levels = ", ".join(str(level) for level in sorted(skipped_levels))
            warnings.warn(
                "Nixtla adapter skipped interval level(s) "
                f"{levels} because their bounds do not map to integer percentile "
                "quantile columns. Coverage and interval width still use available bounds, "
                "but pinball loss will not include the skipped level(s). Use levels with "
                "integer lower/upper percentiles, such as 80 or 90, to emit quantile columns.",
                UserWarning,
                stacklevel=2,
            )

        # Bounds use the widest available interval (highest level with both sides) so
        # coverage / interval_width reflect the broadest band.
        lower_col: str | None = None
        upper_col: str | None = None
        complete_levels = [level for level, sides in intervals.items() if "lo" in sides and "hi" in sides]
        if complete_levels:
            widest = max(complete_levels)
            lower_col = intervals[widest]["lo"]
            upper_col = intervals[widest]["hi"]

        schema = ForecastSchema(
            series_id="unique_id",
            cutoff_time="cutoff_time" if "cutoff_time" in obj else None,
            target_time="ds",
            prediction=model_col,
            actual="actual" if "actual" in obj else "y" if "y" in obj else None,
            lower=lower_col,
            upper=upper_col,
            quantiles=quantiles,
        )
        context.model_name = context.model_name or str(model_col)
        return normalize_dataframe(obj, context=context, adapter_name=self.name, schema=schema)
