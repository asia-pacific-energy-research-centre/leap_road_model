from __future__ import annotations

import pytest

from adapters.base_year_contract import configured_base_year, resolve_base_year, validate_package_base_year


def test_economy_registry_preserves_russia_exception() -> None:
    assert configured_base_year("20USA") == 2022
    assert configured_base_year("16_RUS") == 2021


def test_explicit_base_year_is_auditable_override() -> None:
    assert resolve_base_year("16_RUS", 2025) == (2025, "explicit_override")


def test_legacy_package_base_year_is_explicitly_inferred() -> None:
    assert validate_package_base_year({}, 2022) == "legacy_inferred"


def test_package_base_year_mismatch_fails_before_run() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_package_base_year({"base_year": 2022}, 2025)
