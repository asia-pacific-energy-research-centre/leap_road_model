from __future__ import annotations

import pandas as pd
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


def test_manifest_identity_and_required_base_rows_are_validated() -> None:
    metadata = {"economy": "16_RUS", "package_version": "v_test", "base_year": 2021}
    rows = pd.DataFrame({"Year": [2022]})
    with pytest.raises(ValueError, match="does not contain required base-year rows"):
        validate_package_base_year(metadata, 2021, economy="16_RUS", package_version="v_test", package_rows=rows)
    with pytest.raises(ValueError, match="economy does not match"):
        validate_package_base_year(metadata, 2021, economy="20_USA")
    with pytest.raises(ValueError, match="version does not match"):
        validate_package_base_year(metadata, 2021, package_version="v_other")


def test_legacy_wide_package_rows_are_checked_for_the_required_year() -> None:
    assert validate_package_base_year({}, 2022, package_rows=pd.DataFrame({"2022": [1.0]})) == "legacy_inferred"
    with pytest.raises(ValueError, match="does not contain required base-year rows"):
        validate_package_base_year({}, 2021, package_rows=pd.DataFrame({"2022": [1.0]}))


def test_approved_russia_legacy_future_seed_is_auditable() -> None:
    assert validate_package_base_year(
        {}, 2021, package_rows=pd.DataFrame({"2021": [1.0]}),
        legacy_package_rebase={"source_base_year": 2022, "target_base_year": 2021},
    ) == "future_year_seed"


def test_base_year_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the supported range"):
        resolve_base_year("16_RUS", 1800)
