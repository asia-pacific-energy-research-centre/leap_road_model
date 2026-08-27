"""Authoritative, auditable base-year resolution for road-model runs."""

from __future__ import annotations

from pathlib import Path

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
    return int(economy_data["base_year"])


def resolve_base_year(economy: str, explicit_base_year: int | None = None) -> tuple[int, str]:
    """Resolve a run's base year and record whether it was explicitly overridden."""
    if explicit_base_year is not None:
        return int(explicit_base_year), "explicit_override"
    return configured_base_year(economy), "economy_registry"


def validate_package_base_year(
    package_metadata: dict[str, object] | None,
    expected_base_year: int,
) -> str:
    """Validate package metadata, retaining legacy packages as explicit inference."""
    metadata = package_metadata or {}
    package_base_year = metadata.get("base_year")
    if package_base_year in (None, ""):
        return "legacy_inferred"
    if int(package_base_year) != int(expected_base_year):
        raise ValueError(
            "Module 1 package base year does not match the model run: "
            f"package={package_base_year}, run={expected_base_year}."
        )
    return str(metadata.get("base_year_provenance") or "recorded")
