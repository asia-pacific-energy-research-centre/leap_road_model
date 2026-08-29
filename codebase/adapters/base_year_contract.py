"""Authoritative, auditable base-year resolution for road-model runs."""

from __future__ import annotations

from pathlib import Path
import math
import re

import pandas as pd
import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ECONOMIES_PATH = _REPO_ROOT / "codebase" / "config" / "economies.yaml"


def canonical_economy_code(economy: str) -> str:
    """Return the registry representation of an economy code."""
    value = str(economy).strip().upper().replace("-", "_")
    if "_" not in value and len(value) >= 4:
        value = f"{value[:2]}_{value[2:]}"
    return value


def configured_base_year(economy: str, config_path: str | Path | None = None) -> int:
    """Read the economy-specific base year from the authoritative registry."""
    path = Path(config_path) if config_path is not None else _ECONOMIES_PATH
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    economy_data = (data.get("economies") or {}).get(canonical_economy_code(economy))
    if not isinstance(economy_data, dict) or "base_year" not in economy_data:
        raise ValueError(f"No configured base year for economy {economy!r} in {path}")
    return _validate_base_year(economy_data["base_year"])


def _validate_base_year(value: object) -> int:
    """Reject malformed or implausible base-year values at the boundary."""
    if isinstance(value, bool):
        raise ValueError("Base year must be an integer year, not a boolean.")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"Base year must be an integer, got {value!r}.")
        year = int(value)
    else:
        text = str(value).strip()
        if not re.fullmatch(r"[+-]?\d+(?:\.0+)?", text):
            raise ValueError(f"Base year must be an integer, got {value!r}.")
        year = int(float(text))
    if not 1900 <= year <= 2100:
        raise ValueError(f"Base year {year} is outside the supported range 1900–2100.")
    return year


def resolve_base_year(economy: str, explicit_base_year: int | None = None) -> tuple[int, str]:
    """Resolve a run's base year and record whether it was explicitly overridden."""
    if explicit_base_year is not None:
        return _validate_base_year(explicit_base_year), "explicit_override"
    return configured_base_year(economy), "economy_registry"


def validate_package_base_year(
    package_metadata: dict[str, object] | None,
    expected_base_year: int,
    *,
    economy: str | None = None,
    package_version: str | None = None,
    package_rows: pd.DataFrame | None = None,
    legacy_package_rebase: dict[str, int] | None = None,
) -> str:
    """Validate package identity and required base-year data before modelling."""
    metadata = package_metadata or {}
    expected_base_year = _validate_base_year(expected_base_year)
    if legacy_package_rebase is not None:
        source_year = _validate_base_year(legacy_package_rebase.get("source_base_year"))
        target_year = _validate_base_year(legacy_package_rebase.get("target_base_year"))
        if metadata or target_year != expected_base_year or source_year <= target_year:
            raise ValueError("Invalid legacy future-year package rebase metadata.")
        provenance = "future_year_seed"
    else:
        provenance = None
    if economy is not None and metadata.get("economy") not in (None, ""):
        if canonical_economy_code(str(metadata["economy"])) != canonical_economy_code(economy):
            raise ValueError("Module 1 package economy does not match the model run.")
    if package_version is not None and metadata.get("package_version") not in (None, ""):
        if str(metadata["package_version"]) != str(package_version):
            raise ValueError("Module 1 package version does not match the selected package version.")
    package_base_year = metadata.get("base_year")
    if provenance is not None:
        pass
    elif package_base_year in (None, ""):
        provenance = "legacy_inferred"
    elif _validate_base_year(package_base_year) != expected_base_year:
        raise ValueError(
            "Module 1 package base year does not match the model run: "
            f"package={package_base_year}, run={expected_base_year}."
        )
    else:
        provenance = str(metadata.get("base_year_provenance") or "recorded")
    if package_rows is not None:
        year_column = next((col for col in package_rows.columns if str(col).strip().lower() == "year"), None)
        if year_column is not None:
            has_base_year = pd.to_numeric(package_rows[year_column], errors="coerce").eq(expected_base_year).any()
        else:
            # Legacy wide Module 1 packages store model years as columns.
            has_base_year = any(str(column).strip() == str(expected_base_year) for column in package_rows.columns)
        if not has_base_year:
            raise ValueError(
                f"Module 1 package does not contain required base-year rows for {expected_base_year}; "
                "it is a legacy-package/registry mismatch and cannot be modelled as native."
            )
    return provenance
