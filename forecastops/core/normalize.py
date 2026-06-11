from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from forecastops.core.run import CaptureContext, NormalizedForecast
from forecastops.core.schema import ForecastSchema, quantile_column_name


def normalize_dataframe(
    obj: pd.DataFrame,
    *,
    context: CaptureContext,
    adapter_name: str = "dataframe",
    schema: ForecastSchema | None = None,
) -> NormalizedForecast:
    if not isinstance(obj, pd.DataFrame):
        raise TypeError("normalize_dataframe expects a pandas DataFrame")

    mapping = schema or context.schema
    df = obj.copy()
    out = pd.DataFrame(index=df.index)

    run_id = context.run_id
    if not run_id:
        raise ValueError("CaptureContext.run_id is required for normalization")

    out["run_id"] = run_id
    out["series_id"] = _series_values(df, mapping.series_id if mapping else None, context.series_id)
    out["cutoff_time"] = _time_values(df, mapping.cutoff_time if mapping else None, context.cutoff)
    target_source = mapping.target_time if mapping else _first_present(df, ["target_time", "ds", "timestamp"])
    if target_source is None:
        if context.target_time is None:
            raise ValueError("target_time is required via schema, column inference, or context")
        out["target_time"] = _coerce_context_values(context.target_time, len(df), "target_time")
    else:
        out["target_time"] = df[target_source]

    prediction_source = mapping.prediction if mapping else _first_present(df, ["yhat", "prediction", "forecast"])
    if prediction_source is None:
        raise ValueError("prediction/yhat column is required")
    out["yhat"] = pd.to_numeric(df[prediction_source], errors="coerce")

    model_name_source = mapping.model_name if mapping else None
    if model_name_source and model_name_source in df:
        out["model_name"] = df[model_name_source].astype(str)
    else:
        out["model_name"] = context.model_name or _infer_model_name(prediction_source, adapter_name)

    model_version_source = mapping.model_version if mapping else None
    if model_version_source and model_version_source in df:
        out["model_version"] = df[model_version_source].astype(str)
    elif context.model_version is not None:
        out["model_version"] = context.model_version

    if mapping:
        _copy_if_present(df, out, mapping.actual, "actual", numeric=True)
        _copy_if_present(df, out, mapping.actual_available_at, "actual_available_at")
        _copy_if_present(df, out, mapping.lower, "yhat_lower", numeric=True)
        _copy_if_present(df, out, mapping.upper, "yhat_upper", numeric=True)
        _copy_if_present(df, out, mapping.benchmark_yhat, "benchmark_yhat", numeric=True)
        _copy_if_present(df, out, mapping.benchmark_name, "benchmark_name")
        _copy_if_present(df, out, mapping.benchmark_version, "benchmark_version")
        _copy_if_present(df, out, mapping.forecast_created_at, "forecast_created_at")
        _copy_if_present(df, out, mapping.data_snapshot_id, "data_snapshot_id")
        _copy_if_present(df, out, mapping.source, "source")
        if mapping.interval_level is not None:
            if isinstance(mapping.interval_level, str) and mapping.interval_level in df:
                out["interval_level"] = pd.to_numeric(df[mapping.interval_level], errors="coerce")
            else:
                out["interval_level"] = float(mapping.interval_level)
        for quantile, column in mapping.quantiles.items():
            if column in df:
                out[quantile_column_name(quantile)] = pd.to_numeric(df[column], errors="coerce")
    else:
        for source, target, numeric in [
            ("actual", "actual", True),
            ("y", "actual", True),
            ("yhat_lower", "yhat_lower", True),
            ("yhat_upper", "yhat_upper", True),
            ("interval_level", "interval_level", True),
            ("actual_available_at", "actual_available_at", False),
            ("benchmark_yhat", "benchmark_yhat", True),
            ("benchmark_name", "benchmark_name", False),
            ("benchmark_version", "benchmark_version", False),
            ("forecast_created_at", "forecast_created_at", False),
            ("data_snapshot_id", "data_snapshot_id", False),
            ("source", "source", False),
        ]:
            if source in df and target not in out:
                _copy_if_present(df, out, source, target, numeric=numeric)
        for column in df.columns:
            if column.startswith("yhat_p"):
                out[column] = pd.to_numeric(df[column], errors="coerce")

    for column in _safe_extra_columns(df, mapping):
        if column not in out:
            out[column] = df[column]

    out = _coerce_canonical_types(out)
    out = add_horizon_columns(out)
    return NormalizedForecast(frame=out.reset_index(drop=True), adapter_name=adapter_name)


def normalize_array(obj: Any, *, context: CaptureContext) -> NormalizedForecast:
    values = np.asarray(obj).reshape(-1)
    if context.target_time is None:
        raise ValueError("array adapter requires target_time context")
    df = pd.DataFrame(
        {
            "prediction": values,
            "target_time": _coerce_context_values(context.target_time, len(values), "target_time"),
        }
    )
    schema = ForecastSchema(target_time="target_time", prediction="prediction")
    return normalize_dataframe(df, context=context, adapter_name="array", schema=schema)


def add_horizon_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "cutoff_time" not in out or "target_time" not in out:
        out["horizon"] = pd.NA
        return out

    cutoff = pd.to_datetime(out["cutoff_time"], errors="coerce")
    target = pd.to_datetime(out["target_time"], errors="coerce")
    duration = target - cutoff
    out["horizon_duration"] = duration.astype(str)

    sort_cols = ["series_id", "cutoff_time", "target_time"]
    out = out.sort_values(sort_cols, kind="mergesort")
    out["horizon"] = out.groupby(["series_id", "cutoff_time"], dropna=False).cumcount() + 1
    return out


def _series_values(df: pd.DataFrame, column: str | None, context_series: Any) -> Any:
    if column and column in df:
        return df[column].astype(str)
    if "series_id" in df:
        return df["series_id"].astype(str)
    if context_series is None:
        return "default"
    values = _coerce_context_values(context_series, len(df), "series_id")
    return pd.Series(values, index=df.index).astype(str)


def _time_values(df: pd.DataFrame, column: str | None, context_value: Any) -> Any:
    if column and column in df:
        return df[column]
    if "cutoff_time" in df:
        return df["cutoff_time"]
    if context_value is None:
        raise ValueError("cutoff_time/cutoff is required")
    return _coerce_context_values(context_value, len(df), "cutoff")


def _coerce_context_values(value: Any, length: int, name: str) -> list[Any]:
    if isinstance(value, pd.Series):
        if len(value) != length:
            raise ValueError(f"{name} length {len(value)} does not match forecast length {length}")
        return value.tolist()
    if isinstance(value, pd.Index):
        if len(value) != length:
            raise ValueError(f"{name} length {len(value)} does not match forecast length {length}")
        return value.tolist()
    if isinstance(value, np.ndarray):
        if value.shape[0] != length:
            raise ValueError(f"{name} length {value.shape[0]} does not match forecast length {length}")
        return value.tolist()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != length:
            raise ValueError(f"{name} length {len(value)} does not match forecast length {length}")
        return list(value)
    return [value] * length


def _first_present(df: pd.DataFrame, names: list[str]) -> str | None:
    return next((name for name in names if name in df.columns), None)


def _copy_if_present(
    source: pd.DataFrame,
    target: pd.DataFrame,
    source_column: str | None,
    target_column: str,
    *,
    numeric: bool = False,
) -> None:
    if source_column and source_column in source:
        target[target_column] = (
            pd.to_numeric(source[source_column], errors="coerce")
            if numeric
            else source[source_column]
        )


def _safe_extra_columns(df: pd.DataFrame, schema: ForecastSchema | None) -> list[str]:
    if schema and schema.extra_columns:
        return [column for column in schema.extra_columns if column in df]
    safe_names = {
        "region",
        "zone",
        "category",
        "weekday",
        "month",
        "holiday_flag",
        "event_present",
        "event_type",
        "series_group",
        "customer_segment",
    }
    return [column for column in df.columns if column in safe_names]


def _coerce_canonical_types(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in ["cutoff_time", "target_time", "actual_available_at", "forecast_created_at"]:
        if column in out:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    for column in ["yhat", "actual", "yhat_lower", "yhat_upper", "benchmark_yhat", "interval_level"]:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    for column in ["run_id", "series_id", "model_name", "model_version", "source"]:
        if column in out:
            out[column] = out[column].astype("string")
    return out


def _infer_model_name(prediction_source: str, adapter_name: str) -> str:
    if adapter_name == "nixtla" and prediction_source not in {"yhat", "prediction", "forecast"}:
        return prediction_source
    return adapter_name
