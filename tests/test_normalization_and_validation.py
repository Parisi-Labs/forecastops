from __future__ import annotations

import numpy as np
import pandas as pd

from forecastops.adapters.registry import resolve_adapter
from forecastops.core.normalize import normalize_dataframe
from forecastops.core.run import CaptureContext
from forecastops.core.schema import ForecastSchema
from forecastops.core.validate import validate_forecast


def test_generic_schema_normalization_computes_horizon() -> None:
    df = pd.DataFrame(
        {
            "sku": ["a", "a"],
            "target": pd.date_range("2026-01-02", periods=2, freq="D"),
            "pred": [10.0, 12.0],
            "p10": [8.0, 9.0],
            "p90": [12.0, 15.0],
            "region": ["east", "east"],
        }
    )
    context = CaptureContext(
        project="test",
        run_id="run-1",
        cutoff=pd.Timestamp("2026-01-01"),
        model_name="baseline",
        schema=ForecastSchema(
            series_id="sku",
            target_time="target",
            prediction="pred",
            quantiles={0.1: "p10", 0.9: "p90"},
            extra_columns=["region"],
        ),
    )

    normalized = normalize_dataframe(df, context=context, schema=context.schema).frame

    assert list(normalized["horizon"]) == [1, 2]
    assert list(normalized["series_id"].astype(str)) == ["a", "a"]
    assert "yhat_p10" in normalized
    assert "region" in normalized


def test_prophet_and_nixtla_adapter_detection() -> None:
    prophet = pd.DataFrame({"ds": pd.date_range("2026-01-01", periods=2), "yhat": [1, 2]})
    nixtla = pd.DataFrame(
        {
            "unique_id": ["a", "a"],
            "ds": pd.date_range("2026-01-01", periods=2),
            "AutoARIMA": [1, 2],
        }
    )

    context = CaptureContext(project="test", run_id="run", cutoff=pd.Timestamp("2025-12-31"))

    assert resolve_adapter(prophet, None, context).name == "prophet"
    assert resolve_adapter(nixtla, None, context).name == "nixtla"


def test_validation_detects_duplicate_and_quantile_errors() -> None:
    frame = pd.DataFrame(
        {
            "run_id": ["r", "r"],
            "series_id": ["s", "s"],
            "cutoff_time": [pd.Timestamp("2026-01-01")] * 2,
            "target_time": [pd.Timestamp("2026-01-02")] * 2,
            "horizon": [1, 1],
            "yhat": [10.0, 11.0],
            "model_name": ["m", "m"],
            "yhat_p10": [12.0, 7.0],
            "yhat_p90": [11.0, 9.0],
        }
    )

    events = validate_forecast(frame)
    codes = {event.code for event in events}

    assert "duplicate_keys" in codes
    assert "quantiles_not_monotonic" in codes


def test_array_adapter_requires_semantics() -> None:
    context = CaptureContext(
        project="array",
        run_id="array-run",
        cutoff=pd.Timestamp("2026-01-01"),
        target_time=pd.date_range("2026-01-02", periods=3, freq="D"),
        series_id="meter",
        model_name="lightgbm",
    )
    adapter = resolve_adapter(np.array([1.0, 2.0, 3.0]), "array", context)
    normalized = adapter.normalize(np.array([1.0, 2.0, 3.0]), context=context).frame

    assert adapter.name == "array"
    assert normalized["yhat"].tolist() == [1.0, 2.0, 3.0]
    assert normalized["target_time"].isna().sum() == 0
    assert normalized["series_id"].astype(str).unique().tolist() == ["meter"]
