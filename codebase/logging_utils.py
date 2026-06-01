"""Minimal structured logging and timing utilities for road model workflow."""

import json
import logging
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import pandas as pd


class StructuredLogger:
    """JSON-structured logger for machine-parseable output."""

    def __init__(self, name: str, log_file: str | Path | None = None):
        self.name = name
        self.log_file = Path(log_file) if log_file else None
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event: dict[str, Any]) -> None:
        """Write event as JSON line."""
        event["time"] = datetime.now().isoformat()
        line = json.dumps(event)
        print(line)
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")

    def info(self, event: str, **kwargs) -> None:
        self._write({"logger": self.name, "level": "info", "event": event, **kwargs})

    def error(self, event: str, **kwargs) -> None:
        self._write({"logger": self.name, "level": "error", "event": event, **kwargs})

    def warning(self, event: str, **kwargs) -> None:
        self._write({"logger": self.name, "level": "warning", "event": event, **kwargs})


def log_dataframe_info(df: pd.DataFrame, label: str) -> dict[str, Any]:
    """Extract shape, columns, and null counts from DataFrame."""
    return {
        f"{label}_rows": len(df),
        f"{label}_columns": list(df.columns),
        f"{label}_dtypes": {col: str(df[col].dtype) for col in df.columns},
        f"{label}_nulls": {col: int(df[col].isna().sum()) for col in df.columns},
    }


def timed_operation(logger: StructuredLogger, module_name: str):
    """Decorator to time function execution and log entry/exit."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger.info("start", module=module_name, function=func.__name__)
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                logger.info("complete", module=module_name, duration_sec=round(duration, 2), status="ok")
                return result
            except Exception as e:
                duration = time.time() - start
                logger.error(
                    "failed",
                    module=module_name,
                    duration_sec=round(duration, 2),
                    error_type=type(e).__name__,
                    error_msg=str(e),
                )
                raise

        return wrapper

    return decorator
