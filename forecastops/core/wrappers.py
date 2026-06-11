from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from forecastops.core.capture import capture
from forecastops.core.run import ForecastRun


def forecast(**capture_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a forecast function and capture its return value."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            output = func(*args, **kwargs)
            resolved = _resolve_callable_kwargs(capture_kwargs, args=args, kwargs=kwargs, instance=None)
            run = capture(output, **resolved)
            run.raw_output = output
            return run

        return wrapper

    return decorator


def wrap(model: Any, *, return_run: bool = False, **capture_kwargs: Any) -> Any:
    """Wrap a model instance while preserving fit/predict-style workflows."""

    class ForecastOpsModelWrapper:
        def __init__(self, wrapped: Any):
            self._wrapped = wrapped
            self.fops_last_run: ForecastRun | None = None

        def fit(self, *args: Any, **kwargs: Any) -> Any:
            result = self._wrapped.fit(*args, **kwargs)
            return self if result is self._wrapped else result

        def predict(self, *args: Any, **kwargs: Any) -> Any:
            output = self._wrapped.predict(*args, **kwargs)
            resolved = _resolve_callable_kwargs(capture_kwargs, args=args, kwargs=kwargs, instance=self._wrapped)
            self.fops_last_run = capture(output, **resolved)
            return self.fops_last_run if return_run else output

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    return ForecastOpsModelWrapper(model)


def instrument(model: Any, **capture_kwargs: Any) -> Any:
    return wrap(model, **capture_kwargs)


def _resolve_callable_kwargs(
    capture_kwargs: dict[str, Any],
    *,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    instance: Any | None,
) -> dict[str, Any]:
    context = {"args": args, "kwargs": kwargs, **kwargs}
    resolved: dict[str, Any] = {}
    for key, value in capture_kwargs.items():
        if callable(value):
            try:
                if instance is not None:
                    resolved[key] = value(instance)
                else:
                    resolved[key] = value(context)
            except TypeError:
                resolved[key] = value()
        else:
            resolved[key] = value
    return resolved
