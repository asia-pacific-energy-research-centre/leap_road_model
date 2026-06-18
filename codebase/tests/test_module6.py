"""
Tests for Module 6 — reconciliation and device shares.

Covers:
  1. Device share calculation (BEV single-fuel, ICE multi-fuel, PHEV)
  2. Stock accounting identity after reconciliation
  3. calculate_remaining_esto PHEV subtraction
  4. allocate_esto_fuel_to_branches priority spillover and stock-share allocation
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from modules.module6_reconciliation_and_leap_handoff import (
    apply_scalars,
    apply_scalars_with_cumulative_bounds,
    build_phev_utilisation_diagnostics,
    bootstrap_zero_stock_fuel_branches,
    build_leap_ready_table,
    calculate_device_shares,
    calculate_initial_branch_energy,
    calculate_remaining_esto,
    reconcile_electricity,
    reconcile_stock_mileage_efficiency,
    allocate_esto_fuel_to_branches,
    distribute_phev_liquid_by_esto_mix,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _branch(
    vehicle_type: str,
    drive_type: str,
    fuel: str,
    stock: float,
    mileage: float,
    efficiency: float,
    economy: str = "12_NZ",
    scenario: str = "Reference",
    transport_type: str = "passenger",
    leap_branch_path: str | None = None,
    base_year: int = 2022,
) -> dict:
    if leap_branch_path is None:
        leap_branch_path = f"Demand\\Passenger road\\{vehicle_type}\\{drive_type}\\{fuel}"
    return {
        "economy": economy,
        "scenario": scenario,
        "base_year": base_year,
        "transport_type": transport_type,
        "vehicle_type": vehicle_type,
        "drive_type": drive_type,
        "fuel": fuel,
        "leap_branch_path": leap_branch_path,
        "stock": float(stock),
        "mileage_km_per_year": float(mileage),
        "efficiency_km_per_gj": float(efficiency),
        "stock_source_flag": "researcher",
        "mileage_source_flag": "researcher",
        "efficiency_source_flag": "researcher",
    }


def _make_t4(*branch_dicts) -> pd.DataFrame:
    return pd.DataFrame(list(branch_dicts))


def _make_esto(fuels_pj: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{"fuel": f, "energy_pj": pj} for f, pj in fuels_pj.items()])


# ---------------------------------------------------------------------------
# PHEV utilisation rates
# ---------------------------------------------------------------------------

class TestPHEVUtilisationRates:
    def test_initial_branch_energy_uses_transport_type_specific_phev_rates(self):
        t4 = _make_t4(
            _branch("LPVs", "PHEV", "Electricity", stock=100, mileage=10000, efficiency=250),
            _branch("LPVs", "PHEV", "Motor gasoline", stock=100, mileage=10000, efficiency=100),
            _branch(
                "LCVs",
                "PHEV",
                "Electricity",
                stock=100,
                mileage=20000,
                efficiency=300,
                transport_type="freight",
                leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Electricity",
            ),
            _branch(
                "LCVs",
                "PHEV",
                "Motor gasoline",
                stock=100,
                mileage=20000,
                efficiency=120,
                transport_type="freight",
                leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Motor gasoline",
            ),
        )

        result = calculate_initial_branch_energy(
            t4,
            phev_utilisation_rate={"passenger": 0.8, "freight": 0.3},
        )

        passenger = result[result["transport_type"].eq("passenger")]
        freight = result[result["transport_type"].eq("freight")]
        assert passenger.loc[passenger["fuel"].eq("Electricity"), "mileage_km_per_year"].iloc[0] == pytest.approx(8000)
        assert passenger.loc[passenger["fuel"].eq("Motor gasoline"), "mileage_km_per_year"].iloc[0] == pytest.approx(2000)
        assert freight.loc[freight["fuel"].eq("Electricity"), "mileage_km_per_year"].iloc[0] == pytest.approx(6000)
        assert freight.loc[freight["fuel"].eq("Motor gasoline"), "mileage_km_per_year"].iloc[0] == pytest.approx(14000)

    def test_initial_branch_energy_zero_efficiency_is_zero_not_inf(self):
        t4 = _make_t4(
            _branch("Buses", "BEV", "Electricity", stock=100, mileage=45000, efficiency=0),
        )

        result = calculate_initial_branch_energy(t4)

        assert result["initial_energy_pj"].iloc[0] == 0.0
        assert np.isfinite(result["initial_energy_pj"].iloc[0])


# ---------------------------------------------------------------------------
# apply_scalars
# ---------------------------------------------------------------------------

class TestApplyScalars:
    def test_ecf_one_returns_unmodified_values(self):
        ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars(
            stock=1000.0, mileage=15000.0, efficiency=200.0,
            ecf=1.0,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds=(0.33, 3.0),
        )
        assert pytest.approx(adj_s, rel=1e-6) == 1000.0
        assert pytest.approx(adj_m, rel=1e-6) == 15000.0
        assert pytest.approx(adj_e, rel=1e-6) == 200.0
        assert within is True

    def test_ecf_two_increases_stock_and_mileage_decreases_efficiency(self):
        ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars(
            stock=1000.0, mileage=15000.0, efficiency=200.0,
            ecf=2.0,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds=(0.1, 10.0),
        )
        # stock_scalar = 2^0.5, mileage_scalar = 2^0.25, efficiency_scalar = 2^(-0.25)
        assert adj_s > 1000.0
        assert adj_m > 15000.0
        assert adj_e < 200.0  # efficiency_scalar < 1 means km/GJ drops
        assert within is True

    def test_ecf_beyond_bounds_clips_and_flags(self):
        _, _, _, adj_s, _, _, within = apply_scalars(
            stock=1000.0, mileage=15000.0, efficiency=200.0,
            ecf=1000.0,  # extreme → scalar would be 1000^0.5 = 31.6, beyond hi=3.0
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds=(0.33, 3.0),
        )
        # stock clamped at 3.0 → adj_s = 3000
        assert pytest.approx(adj_s, rel=1e-6) == 3000.0
        assert within is False


class TestReconcileElectricity:
    def test_phev_electricity_above_esto_iterates_stock_to_target(self):
        t4 = _make_t4(
            _branch("LPVs", "BEV", "Electricity", stock=100, mileage=10000, efficiency=250),
            _branch("LPVs", "PHEV", "Electricity", stock=500, mileage=10000, efficiency=250),
            _branch("LPVs", "PHEV", "Motor gasoline", stock=500, mileage=10000, efficiency=100),
        )
        branch_energy = calculate_initial_branch_energy(t4, phev_utilisation_rate=0.6)

        adjusted, phev_liquid = reconcile_electricity(
            branch_energy=branch_energy,
            electricity_esto_pj=0.004,
            phev_utilisation_rate=0.6,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds={
                "stock": (0.0, np.inf),
                "mileage": (0.85, 1.15),
                "efficiency": (0.90, 1.10),
            },
        )

        electric_total = adjusted.loc[adjusted["fuel"] == "Electricity", "initial_energy_pj"].sum()
        assert pytest.approx(electric_total, rel=1e-6) == 0.004
        assert not phev_liquid.empty
        assert phev_liquid["phev_liquid_pj"].sum() < 0.02

    def test_energy_identity_holds_approximately(self):
        """After applying scalars, the energy should approximately equal ECF × original."""
        stock, mileage, eff = 500.0, 12000.0, 150.0
        ecf = 1.4
        weights = {"stock": 0.5, "mileage": 0.25, "efficiency": 0.25}
        _, _, _, adj_s, adj_m, adj_e, _ = apply_scalars(
            stock, mileage, eff, ecf, weights, (0.1, 10.0)
        )
        original_energy = stock * mileage / eff
        adjusted_energy = adj_s * adj_m / adj_e
        # With simultaneous adjustment, energy ratio should equal ECF
        assert pytest.approx(adjusted_energy / original_energy, rel=1e-5) == ecf

    def test_per_scalar_bounds_allow_wider_stock_flexibility(self):
        """Per-scalar bounds should allow stock to move more than mileage/efficiency."""
        ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars(
            stock=1000.0, mileage=15000.0, efficiency=200.0,
            ecf=4.0,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds={
                "stock": (0.0, 10.0),
                "mileage": (0.85, 1.15),
                "efficiency": (0.90, 1.10),
            },
        )
        # raw scalars: stock=2.0, mileage~1.414, efficiency~0.707
        # mileage and efficiency clip to their tighter bounds; stock remains flexible.
        assert pytest.approx(ss, rel=1e-6) == 2.0
        assert pytest.approx(ms, rel=1e-6) == 1.15
        assert pytest.approx(es, rel=1e-6) == 0.90
        assert within is False
        assert adj_s > 1000.0

    def test_cumulative_step_removes_mileage_efficiency_cancellation(self):
        """Residual crossover should not leave mileage and efficiency moving together."""
        ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars_with_cumulative_bounds(
            original_stock=1000.0,
            original_mileage=15000.0,
            original_efficiency=200.0,
            ecf=0.60,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds={
                "stock": (0.0, 10.0),
                "mileage": (0.85, 1.15),
                "efficiency": (0.90, 1.10),
            },
            current_stock_scalar=1.0,
            current_mileage_scalar=1.15,
            current_efficiency_scalar=0.90,
        )

        assert ms / es == pytest.approx((1.15 * (0.60 ** 0.25)) / (0.90 * (0.60 ** -0.25)))
        assert (ms - 1.0) * (es - 1.0) <= 0.0
        assert adj_m == pytest.approx(15000.0 * ms)
        assert adj_e == pytest.approx(200.0 * es)

    def test_ecf_zero_flags_out_of_bounds(self):
        """Zero allocated fuel should be treated as an out-of-bounds reconciliation case."""
        ss, ms, es, adj_s, adj_m, adj_e, within = apply_scalars(
            stock=1000.0,
            mileage=15000.0,
            efficiency=200.0,
            ecf=0.0,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds={
                "stock": (0.0, 10.0),
                "mileage": (0.85, 1.15),
                "efficiency": (0.90, 1.10),
            },
        )
        assert within is False
        assert ss == 0.0
        assert pytest.approx(ms, rel=1e-6) == 0.85
        assert pytest.approx(es, rel=1e-6) == 1.10
        assert adj_s == 0.0


# ---------------------------------------------------------------------------
# calculate_device_shares
# ---------------------------------------------------------------------------

class TestCalculateDeviceShares:
    def _make_t9_row(self, drive, fuel, stock, mileage, efficiency, final_fuel_pj,
                     vehicle_type="LPVs", economy="12_NZ", scenario="Reference") -> dict:
        return {
            "economy": economy,
            "scenario": scenario,
            "transport_type": "passenger",
            "vehicle_type": vehicle_type,
            "drive_type": drive,
            "fuel": fuel,
            "leap_branch_path": f"Demand\\Passenger road\\{vehicle_type}\\{drive}\\{fuel}",
            "allocated_branch_fuel_pj": final_fuel_pj,
            "adjusted_stock": float(stock),
            "adjusted_mileage_km_per_year": float(mileage),
            "adjusted_efficiency_km_per_gj": float(efficiency),
            "final_branch_fuel_pj": float(final_fuel_pj),
            "initial_branch_energy_pj": float(stock * mileage / efficiency / 1_000_000),
            "energy_correction_factor": 1.0,
            "stock_scalar": 1.0, "mileage_scalar": 1.0, "efficiency_scalar": 1.0,
            "stock_weight": 0.5, "mileage_weight": 0.25, "efficiency_weight": 0.25,
            "scalars_within_bounds": True,
        }

    def test_bev_single_fuel_device_share_is_one(self):
        t9 = pd.DataFrame([
            self._make_t9_row("BEV", "Electricity", stock=500, mileage=12000, efficiency=300, final_fuel_pj=0.02)
        ])
        t10 = calculate_device_shares(t9)
        assert len(t10) == 1
        assert pytest.approx(t10["device_share"].iloc[0], abs=1e-9) == 1.0

    def test_fcev_single_fuel_device_share_is_one(self):
        t9 = pd.DataFrame([
            self._make_t9_row("FCEV", "Hydrogen", stock=100, mileage=15000, efficiency=250, final_fuel_pj=0.006)
        ])
        t10 = calculate_device_shares(t9)
        assert pytest.approx(t10["device_share"].iloc[0], abs=1e-9) == 1.0

    def test_ice_two_fuels_device_shares_sum_to_one(self):
        # ICE LPV with gasoline (80%) and biogasoline (20%) by energy
        eff = 100.0  # km/GJ
        mileage = 10000.0
        t9 = pd.DataFrame([
            self._make_t9_row("ICE", "Motor gasoline", stock=1000, mileage=mileage, efficiency=eff,
                              final_fuel_pj=0.08),
            self._make_t9_row("ICE", "Biogasoline", stock=1000, mileage=mileage, efficiency=eff,
                              final_fuel_pj=0.02),
        ])
        t10 = calculate_device_shares(t9)
        total = t10["device_share"].sum()
        assert pytest.approx(total, abs=1e-6) == 1.0

    def test_ice_two_fuels_shares_proportional_to_energy(self):
        eff = 100.0
        mileage = 10000.0
        # gasoline: 0.08 PJ, biogasoline: 0.02 PJ → expected shares 0.8 / 0.2
        t9 = pd.DataFrame([
            self._make_t9_row("ICE", "Motor gasoline", stock=1000, mileage=mileage, efficiency=eff,
                              final_fuel_pj=0.08),
            self._make_t9_row("ICE", "Biogasoline", stock=1000, mileage=mileage, efficiency=eff,
                              final_fuel_pj=0.02),
        ])
        t10 = calculate_device_shares(t9)
        shares = t10.set_index("fuel")["device_share"]
        assert pytest.approx(shares["Motor gasoline"], rel=1e-4) == 0.80
        assert pytest.approx(shares["Biogasoline"], rel=1e-4) == 0.20

    def test_phev_device_shares_sum_to_one(self):
        mileage = 12000.0
        t9 = pd.DataFrame([
            self._make_t9_row("PHEV", "Electricity", stock=300, mileage=mileage * 0.5,
                              efficiency=300, final_fuel_pj=0.006),
            self._make_t9_row("PHEV", "Motor gasoline", stock=300, mileage=mileage * 0.5,
                              efficiency=100, final_fuel_pj=0.018),
        ])
        t10 = calculate_device_shares(t9)
        total = t10["device_share"].sum()
        assert pytest.approx(total, abs=1e-6) == 1.0

    def test_mixed_drives_each_sums_to_one(self):
        """BEV and ICE branches independently sum to 1.0 each."""
        eff = 100.0
        mileage = 10000.0
        t9 = pd.DataFrame([
            self._make_t9_row("BEV", "Electricity", stock=200, mileage=mileage, efficiency=300,
                              final_fuel_pj=0.0067, vehicle_type="LPVs"),
            self._make_t9_row("ICE", "Motor gasoline", stock=800, mileage=mileage, efficiency=eff,
                              final_fuel_pj=0.06, vehicle_type="LPVs"),
            self._make_t9_row("ICE", "Biodiesel", stock=800, mileage=mileage, efficiency=eff,
                              final_fuel_pj=0.02, vehicle_type="LPVs"),
        ])
        t10 = calculate_device_shares(t9)
        for drive in ["BEV", "ICE"]:
            sub = t10[t10["drive_type"] == drive]["device_share"].sum()
            assert pytest.approx(sub, abs=1e-6) == 1.0, f"{drive} device shares do not sum to 1"

    def test_nan_size_group_device_shares_sum_to_one(self):
        """Missing size should not cause pandas groupby to drop the branch."""
        mileage = 12000.0
        t9 = pd.DataFrame([
            self._make_t9_row("PHEV", "Electricity", stock=300, mileage=mileage,
                              efficiency=300, final_fuel_pj=0.006),
            self._make_t9_row("PHEV", "Motor gasoline", stock=300, mileage=mileage,
                              efficiency=100, final_fuel_pj=0.018),
        ])
        t9["size"] = np.nan
        t10 = calculate_device_shares(t9)
        assert pytest.approx(t10["device_share"].sum(), abs=1e-6) == 1.0


class TestPHEVUtilisationDiagnostics:
    def test_backcalculates_electric_km_share(self):
        t9 = pd.DataFrame([
            _branch("LPVs", "PHEV", "Electricity", stock=100, mileage=4000, efficiency=200),
            _branch("LPVs", "PHEV", "Motor gasoline", stock=100, mileage=6000, efficiency=100),
        ])
        t9 = t9.rename(columns={
            "stock": "adjusted_stock",
            "mileage_km_per_year": "adjusted_mileage_km_per_year",
            "efficiency_km_per_gj": "adjusted_efficiency_km_per_gj",
        })
        t9["final_branch_fuel_pj"] = [1.0, 3.0]

        result = build_phev_utilisation_diagnostics(t9, phev_utilisation_rate=0.40, tolerance=0.10)

        assert len(result) == 1
        # electric km proxy = 1 PJ * 200 km/GJ; liquid = 3 PJ * 100 km/GJ
        assert pytest.approx(result["backcalculated_phev_utilisation_rate"].iloc[0]) == 0.40
        assert result["utilisation_status"].iloc[0] == "ok"

    def test_flags_backcalculated_rate_outside_range(self):
        t9 = pd.DataFrame([
            _branch("LPVs", "PHEV", "Electricity", stock=100, mileage=4000, efficiency=200),
            _branch("LPVs", "PHEV", "Motor gasoline", stock=100, mileage=6000, efficiency=100),
        ])
        t9 = t9.rename(columns={
            "stock": "adjusted_stock",
            "mileage_km_per_year": "adjusted_mileage_km_per_year",
            "efficiency_km_per_gj": "adjusted_efficiency_km_per_gj",
        })
        t9["final_branch_fuel_pj"] = [0.1, 3.0]

        result = build_phev_utilisation_diagnostics(t9, phev_utilisation_rate=0.40, tolerance=0.10)

        assert result["utilisation_status"].iloc[0] == "below_range"


# ---------------------------------------------------------------------------
# Stock accounting identity after reconciliation
# ---------------------------------------------------------------------------

class TestStockAccountingIdentity:
    """After reconcile_stock_mileage_efficiency, final_branch_fuel_pj should equal
    allocated_branch_fuel_pj within a small tolerance (determined by scalar clamping)."""

    def test_identity_holds_when_ecf_within_bounds(self):
        t4 = _make_t4(
            _branch("LPVs", "ICE", "Motor gasoline", stock=1000, mileage=15000, efficiency=100),
        )
        esto = _make_esto({"Motor gasoline": 2.5})  # slightly above model value of 1.5

        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(esto, pd.DataFrame())
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        t9 = reconcile_stock_mileage_efficiency(
            t8, t4,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds=(0.1, 10.0),
        )

        for _, row in t9.iterrows():
            recalc = row["adjusted_stock"] * row["adjusted_mileage_km_per_year"] / row["adjusted_efficiency_km_per_gj"] / 1_000_000
            assert pytest.approx(recalc, rel=1e-5) == row["final_branch_fuel_pj"]

    def test_final_fuel_matches_allocated_when_unclamped(self):
        """When ECF is within scalar bounds, final_branch_fuel_pj ≈ allocated_branch_fuel_pj."""
        t4 = _make_t4(
            _branch("LPVs", "BEV", "Electricity", stock=500, mileage=12000, efficiency=300),
        )
        # Initial energy = 500 × 12000 / 300 / 1e6 = 0.02 PJ
        # ESTO electricity = 0.025 PJ → ECF = 1.25 (within bounds)
        esto = _make_esto({"Electricity": 0.025})

        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(esto, pd.DataFrame())
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        t9 = reconcile_stock_mileage_efficiency(
            t8, t4,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds=(0.1, 10.0),
        )

        row = t9.iloc[0]
        assert pytest.approx(row["final_branch_fuel_pj"], rel=1e-4) == row["allocated_branch_fuel_pj"]

    def test_multiple_branches_each_satisfies_identity(self):
        t4 = _make_t4(
            _branch("LPVs", "ICE", "Motor gasoline", stock=800, mileage=14000, efficiency=90),
            _branch("LPVs", "BEV", "Electricity", stock=200, mileage=12000, efficiency=280),
        )
        # Initial: ICE = 800×14000/90/1e6 ≈ 0.124 PJ, BEV = 200×12000/280/1e6 ≈ 0.00857 PJ
        esto = _make_esto({"Motor gasoline": 0.13, "Electricity": 0.009})

        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(esto, pd.DataFrame())
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        t9 = reconcile_stock_mileage_efficiency(
            t8, t4,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds=(0.1, 10.0),
        )

        for _, row in t9.iterrows():
            recalc = (row["adjusted_stock"] * row["adjusted_mileage_km_per_year"]
                      / row["adjusted_efficiency_km_per_gj"] / 1_000_000)
            assert pytest.approx(recalc, rel=1e-5) == row["final_branch_fuel_pj"]

    def test_zero_allocated_fuel_reconciles_to_zero_final_energy(self):
        """Branches with zero allocated fuel should not retain artificial positive final energy."""
        t4 = _make_t4(
            _branch("LPVs", "ICE", "Motor gasoline", stock=1000, mileage=15000, efficiency=100),
            _branch("LPVs", "ICE", "LPG", stock=1000, mileage=15000, efficiency=100),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([
                {"fuel": "Motor gasoline", "energy_pj": 2.0},
                {"fuel": "LPG", "energy_pj": 0.0},
            ]),
            pd.DataFrame(),
        )
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        t9 = reconcile_stock_mileage_efficiency(
            t8,
            t4,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds={
                "stock": (0.0, 10.0),
                "mileage": (0.85, 1.15),
                "efficiency": (0.90, 1.10),
            },
        )

        lpg_row = t9[t9["fuel"] == "LPG"].iloc[0]
        assert lpg_row["allocated_branch_fuel_pj"] == 0.0
        assert lpg_row["energy_correction_factor"] == 0.0
        assert lpg_row["final_branch_fuel_pj"] == 0.0

    def test_iterative_reconciliation_keeps_cumulative_mileage_efficiency_bounds(self):
        """Iterative residual steps should not compound bounded scalars past their limits."""
        t4 = _make_t4(
            _branch("LPVs", "ICE", "Motor gasoline", stock=1000, mileage=15000, efficiency=100),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(_make_esto({"Motor gasoline": 15.0}), pd.DataFrame())
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        t9 = reconcile_stock_mileage_efficiency(
            t8,
            t4,
            weights={"stock": 0.5, "mileage": 0.25, "efficiency": 0.25},
            scalar_bounds={
                "stock": (0.0, np.inf),
                "mileage": (0.85, 1.15),
                "efficiency": (0.90, 1.10),
            },
        )

        row = t9.iloc[0]
        assert 0.85 <= row["mileage_scalar"] <= 1.15
        assert 0.90 <= row["efficiency_scalar"] <= 1.10
        assert (row["mileage_scalar"] - 1.0) * (row["efficiency_scalar"] - 1.0) <= 0.0


# ---------------------------------------------------------------------------
# calculate_remaining_esto
# ---------------------------------------------------------------------------

class TestCalculateRemainingEsto:
    def test_no_phev_returns_full_esto(self):
        esto = _make_esto({"Motor gasoline": 5.0, "Electricity": 2.0})
        result = calculate_remaining_esto(esto, pd.DataFrame())
        gas_row = result[result["fuel"] == "Motor gasoline"].iloc[0]
        assert pytest.approx(gas_row["remaining_esto_fuel_pj"]) == 5.0
        assert pytest.approx(gas_row["phev_liquid_subtracted_pj"]) == 0.0

    def test_phev_liquid_subtracted_from_gasoline(self):
        esto = _make_esto({"Motor gasoline": 5.0, "Gas and diesel oil": 3.0})
        phev = pd.DataFrame([
            {"vehicle_type": "LPVs", "drive_type": "PHEV", "fuel": "Motor gasoline", "phev_liquid_pj": 0.8},
        ])
        result = calculate_remaining_esto(esto, phev)
        gas = result[result["fuel"] == "Motor gasoline"].iloc[0]
        diesel = result[result["fuel"] == "Gas and diesel oil"].iloc[0]
        assert pytest.approx(gas["remaining_esto_fuel_pj"]) == 4.2
        assert pytest.approx(diesel["remaining_esto_fuel_pj"]) == 3.0

    def test_remaining_never_negative(self):
        esto = _make_esto({"Motor gasoline": 1.0})
        phev = pd.DataFrame([
            {"vehicle_type": "LPVs", "drive_type": "PHEV", "fuel": "Motor gasoline", "phev_liquid_pj": 2.0}
        ])
        result = calculate_remaining_esto(esto, phev)
        assert result["remaining_esto_fuel_pj"].iloc[0] == 0.0


class TestPHEVLiquidDistribution:
    def test_phev_liquid_uses_gasoline_family_only(self):
        phev = pd.DataFrame([
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "Motor gasoline", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "Gas and diesel oil", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "Biodiesel", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "Biogasoline", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "Efuel", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "LPG", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "PHEV", "size": "small", "fuel": "Natural gas", "phev_liquid_pj": 1.0},
        ])
        esto = _make_esto({
            "Motor gasoline": 40.0,
            "Gas and diesel oil": 60.0,
            "Biodiesel": 4.0,
            "Biogasoline": 6.0,
            "Efuel": 4.0,
            "LPG": 1000.0,
            "Natural gas": 1000.0,
        })

        result = distribute_phev_liquid_by_esto_mix(phev, esto)
        by_fuel = result.set_index("fuel")["phev_liquid_pj"]

        assert pytest.approx(by_fuel["Motor gasoline"], rel=1e-4) == 40.0 / 50.0
        assert pytest.approx(by_fuel["Biogasoline"], rel=1e-4) == 6.0 / 50.0
        assert pytest.approx(by_fuel["Efuel"], rel=1e-4) == 4.0 / 50.0
        assert by_fuel["Gas and diesel oil"] == 0.0
        assert by_fuel["Biodiesel"] == 0.0
        assert by_fuel["LPG"] == 0.0
        assert by_fuel["Natural gas"] == 0.0

    def test_erev_uses_same_gasoline_family_rule_as_phev(self):
        erev = pd.DataFrame([
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "EREV", "size": "small", "fuel": "Motor gasoline", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "EREV", "size": "small", "fuel": "Gas and diesel oil", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "EREV", "size": "small", "fuel": "Biodiesel", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "EREV", "size": "small", "fuel": "Biogasoline", "phev_liquid_pj": 1.0},
            {"economy": "12_NZ", "scenario": "Reference", "transport_type": "passenger", "vehicle_type": "LPVs", "drive_type": "EREV", "size": "small", "fuel": "Efuel", "phev_liquid_pj": 1.0},
        ])
        esto = _make_esto({
            "Motor gasoline": 40.0,
            "Gas and diesel oil": 60.0,
            "Biodiesel": 4.0,
            "Biogasoline": 6.0,
            "Efuel": 4.0,
        })

        result = distribute_phev_liquid_by_esto_mix(erev, esto)
        by_fuel = result.set_index("fuel")["phev_liquid_pj"]

        assert pytest.approx(by_fuel["Motor gasoline"], rel=1e-4) == 40.0 / 50.0
        assert pytest.approx(by_fuel["Biogasoline"], rel=1e-4) == 6.0 / 50.0
        assert pytest.approx(by_fuel["Efuel"], rel=1e-4) == 4.0 / 50.0
        assert by_fuel["Gas and diesel oil"] == 0.0
        assert by_fuel["Biodiesel"] == 0.0


# ---------------------------------------------------------------------------
# allocate_esto_fuel_to_branches
# ---------------------------------------------------------------------------

class TestAllocateFuelToBranches:
    def test_zero_stock_positive_electricity_target_is_bootstrapped(self):
        t4 = _make_t4(
            _branch("LPVs", "BEV", "Electricity", stock=0, mileage=12000, efficiency=300),
        )
        esto = pd.DataFrame([{"fuel": "Electricity", "energy_pj": 0.02}])
        branch_energy = calculate_initial_branch_energy(t4)

        bootstrapped = bootstrap_zero_stock_fuel_branches(branch_energy, esto)
        remaining = calculate_remaining_esto(esto, pd.DataFrame())
        t8 = allocate_esto_fuel_to_branches(bootstrapped, remaining, bootstrapped)
        t9 = reconcile_stock_mileage_efficiency(
            t8,
            bootstrapped,
            weights={"stock": 1.0, "mileage": 0.0, "efficiency": 0.0},
            scalar_bounds={"stock": (0.0, float("inf")), "mileage": (1.0, 1.0), "efficiency": (1.0, 1.0)},
        )

        row = t9.iloc[0]
        assert row["stock_bootstrapped_for_reconciliation"]
        assert row["adjusted_stock"] > 0
        assert pytest.approx(row["final_branch_fuel_pj"], rel=1e-6) == 0.02

    def test_single_branch_gets_all_fuel(self):
        t4 = _make_t4(
            _branch("LPVs", "BEV", "Electricity", stock=500, mileage=12000, efficiency=300),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = _make_esto({"Electricity": 2.0})
        remaining = calculate_remaining_esto(
            pd.DataFrame([{"fuel": "Electricity", "energy_pj": 2.0}]), pd.DataFrame()
        )
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        assert len(t8) == 1
        assert pytest.approx(t8["allocated_branch_fuel_pj"].iloc[0]) == 2.0
        assert pytest.approx(t8["branch_allocation_share"].iloc[0]) == 1.0

    def test_two_branches_same_fuel_split_by_energy(self):
        # LPV:  600 * 14000 / 100  = 84000 GJ = 0.084 PJ
        # Bus:  400 * 50000 / 60   = 333333 GJ ≈ 0.3333 PJ
        # Allocation uses energy-weighted shares (not stock count) so trucks/buses
        # with high utilisation receive a proportional share of liquid fuels.
        lpv_energy = 600 * 14000 / 100 / 1_000_000
        bus_energy = 400 * 50000 / 60 / 1_000_000
        total = lpv_energy + bus_energy
        t4 = _make_t4(
            _branch("LPVs", "ICE", "Motor gasoline", stock=600, mileage=14000, efficiency=100),
            _branch("Buses", "ICE", "Motor gasoline", stock=400, mileage=50000, efficiency=60,
                    transport_type="passenger"),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([{"fuel": "Motor gasoline", "energy_pj": 10.0}]), pd.DataFrame()
        )
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        shares = t8.set_index("vehicle_type")["branch_allocation_share"]
        assert pytest.approx(shares["LPVs"], rel=1e-4) == lpv_energy / total
        assert pytest.approx(shares["Buses"], rel=1e-4) == bus_energy / total

    def test_diesel_splits_trucks_and_lcvs_proportionally_before_passenger(self):
        # Trucks and LCVs share the combined freight ICE tier proportionally by
        # initial_energy_pj (both 1.0 PJ here, so they split the 1.5 PJ target
        # evenly) rather than Trucks draining the tier before LCVs gets any.
        t4 = _make_t4(
            _branch(
                "Trucks", "ICE", "Gas and diesel oil", stock=10000, mileage=10000, efficiency=100,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\Trucks\\ICE\\Gas and diesel oil",
            ),
            _branch(
                "LCVs", "ICE", "Gas and diesel oil", stock=10000, mileage=10000, efficiency=100,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\ICE\\Gas and diesel oil",
            ),
            _branch("LPVs", "ICE", "Gas and diesel oil", stock=10000, mileage=10000, efficiency=100),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([{"fuel": "Gas and diesel oil", "energy_pj": 1.5}]), pd.DataFrame()
        )

        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)

        allocated = t8.set_index("vehicle_type")["allocated_branch_fuel_pj"]
        assert pytest.approx(allocated["Trucks"], rel=1e-4) == 0.75
        assert pytest.approx(allocated["LCVs"], rel=1e-4) == 0.75
        assert pytest.approx(allocated["LPVs"], abs=1e-9) == 0.0
        assert set(t8["allocation_rule"]) == {"priority_spillover_stock_share"}

    def test_diesel_uses_lcv_liquid_capacity_before_passenger_spillover(self):
        # Trucks (1.0 PJ) and diesel-fuelled LCVs (0.2 PJ) split the 1.8 PJ diesel
        # target proportionally (5/6 : 1/6) within the combined freight ICE tier.
        t4 = _make_t4(
            _branch(
                "Trucks", "ICE", "Gas and diesel oil", stock=10000, mileage=10000, efficiency=100,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\Trucks\\ICE\\Gas and diesel oil",
            ),
            _branch(
                "LCVs", "ICE", "Gas and diesel oil", stock=10000, mileage=10000, efficiency=500,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\ICE\\Gas and diesel oil",
            ),
            _branch(
                "LCVs", "ICE", "Motor gasoline", stock=10000, mileage=10000, efficiency=125,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\ICE\\Motor gasoline",
            ),
            _branch("LPVs", "ICE", "Gas and diesel oil", stock=10000, mileage=10000, efficiency=100),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([
                {"fuel": "Gas and diesel oil", "energy_pj": 1.8},
                {"fuel": "Motor gasoline", "energy_pj": 0.5},
            ]),
            pd.DataFrame(),
        )

        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)

        diesel = t8[t8["fuel"] == "Gas and diesel oil"].set_index("vehicle_type")["allocated_branch_fuel_pj"]
        gasoline = t8[t8["fuel"] == "Motor gasoline"].set_index("vehicle_type")["allocated_branch_fuel_pj"]
        assert pytest.approx(diesel["Trucks"], rel=1e-4) == 1.5
        assert pytest.approx(diesel["LCVs"], rel=1e-4) == 0.3
        assert pytest.approx(diesel["LPVs"], abs=1e-9) == 0.0
        assert pytest.approx(gasoline["LCVs"], rel=1e-4) == 0.5

    def test_gasoline_allocates_to_passenger_before_lcvs_and_trucks(self):
        t4 = _make_t4(
            _branch("LPVs", "ICE", "Motor gasoline", stock=10000, mileage=10000, efficiency=100),
            _branch(
                "LCVs", "ICE", "Motor gasoline", stock=10000, mileage=10000, efficiency=100,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\ICE\\Motor gasoline",
            ),
            _branch(
                "Trucks", "ICE", "Motor gasoline", stock=10000, mileage=10000, efficiency=100,
                transport_type="freight", leap_branch_path="Demand\\Freight road\\Trucks\\ICE\\Motor gasoline",
            ),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([{"fuel": "Motor gasoline", "energy_pj": 1.5}]), pd.DataFrame()
        )

        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)

        allocated = t8.set_index("vehicle_type")["allocated_branch_fuel_pj"]
        assert pytest.approx(allocated["LPVs"], rel=1e-4) == 1.0
        assert pytest.approx(allocated["LCVs"], rel=1e-4) == 0.5
        assert pytest.approx(allocated["Trucks"], abs=1e-9) == 0.0

    def test_electricity_allocation_rule_uses_residual_energy_share(self):
        t4 = _make_t4(
            _branch("LPVs", "BEV", "Electricity", stock=100, mileage=10000, efficiency=300),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([{"fuel": "Electricity", "energy_pj": 1.0}]), pd.DataFrame()
        )
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        assert t8["allocation_rule"].iloc[0] == "residual_electric_energy_share"

    def test_ineligible_fuel_excluded(self):
        """A branch with drive_type=BEV but fuel=Motor gasoline is ineligible and excluded."""
        t4 = _make_t4(
            _branch("LPVs", "BEV", "Electricity", stock=100, mileage=10000, efficiency=300),
            _branch("LPVs", "BEV", "Motor gasoline", stock=100, mileage=10000, efficiency=100),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([{"fuel": "Electricity", "energy_pj": 1.0},
                          {"fuel": "Motor gasoline", "energy_pj": 1.0}]),
            pd.DataFrame()
        )
        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)
        # Only the BEV+Electricity row should appear
        assert len(t8) == 1
        assert t8["fuel"].iloc[0] == "Electricity"

    def test_phev_diesel_branch_excluded_from_fuel_allocation(self):
        t4 = _make_t4(
            _branch("LCVs", "PHEV", "Electricity", stock=100, mileage=5000, efficiency=300,
                    transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Electricity"),
            _branch("LCVs", "PHEV", "Motor gasoline", stock=100, mileage=5000, efficiency=100,
                    transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Motor gasoline"),
            _branch("LCVs", "PHEV", "Biogasoline", stock=100, mileage=5000, efficiency=100,
                    transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Biogasoline"),
            _branch("LCVs", "PHEV", "Efuel", stock=100, mileage=5000, efficiency=100,
                    transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Efuel"),
            _branch("LCVs", "PHEV", "Gas and diesel oil", stock=100, mileage=5000, efficiency=100,
                    transport_type="freight", leap_branch_path="Demand\\Freight road\\LCVs\\PHEV\\Gas and diesel oil"),
        )
        branch_energy = calculate_initial_branch_energy(t4)
        remaining = calculate_remaining_esto(
            pd.DataFrame([
                {"fuel": "Electricity", "energy_pj": 1.0},
                {"fuel": "Motor gasoline", "energy_pj": 1.0},
                {"fuel": "Biogasoline", "energy_pj": 1.0},
                {"fuel": "Efuel", "energy_pj": 1.0},
                {"fuel": "Gas and diesel oil", "energy_pj": 1.0},
            ]),
            pd.DataFrame(),
        )

        t8 = allocate_esto_fuel_to_branches(branch_energy, remaining, t4)

        assert set(t8["fuel"]) == {"Electricity", "Motor gasoline", "Biogasoline", "Efuel"}


class TestBuildLeapReadyTable:
    def test_t11_uses_leap_expected_branch_levels(self):
        t9 = pd.DataFrame([
            {
                "economy": "20_USA",
                "scenario": "Target",
                "base_year": 2022,
                "transport_type": "freight",
                "vehicle_type": "Trucks",
                "drive_type": "ICE",
                "size": "heavy",
                "fuel": "Gas and diesel oil",
                "leap_branch_path": "Demand\\Freight road\\Trucks\\ICE heavy\\Gas and diesel oil",
                "adjusted_stock": 100.0,
                "adjusted_mileage_km_per_year": 10000.0,
                "adjusted_efficiency_km_per_gj": 100.0,
                "final_branch_fuel_pj": 0.01,
            },
            {
                "economy": "20_USA",
                "scenario": "Target",
                "base_year": 2022,
                "transport_type": "freight",
                "vehicle_type": "LCVs",
                "drive_type": "BEV",
                "size": None,
                "fuel": "Electricity",
                "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
                "adjusted_stock": 300.0,
                "adjusted_mileage_km_per_year": 8000.0,
                "adjusted_efficiency_km_per_gj": 200.0,
                "final_branch_fuel_pj": 0.012,
            },
        ])
        t10 = pd.DataFrame([
            {
                "economy": "20_USA",
                "scenario": "Target",
                "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
                "device_share": 1.0,
            }
        ])
        t6 = pd.DataFrame([
            {"economy": "20_USA", "scenario": "Target", "year": 2022, "transport_type": "freight", "vehicle_type": "Trucks", "new_sales": 10.0},
            {"economy": "20_USA", "scenario": "Target", "year": 2022, "transport_type": "freight", "vehicle_type": "LCVs", "new_sales": 30.0},
        ])
        t7 = pd.DataFrame([
            {"economy": "20_USA", "scenario": "Target", "year": 2022, "transport_type": "freight", "vehicle_type": "Trucks", "drive_type": "ICE", "sales_share": 1.0},
            {"economy": "20_USA", "scenario": "Target", "year": 2022, "transport_type": "freight", "vehicle_type": "LCVs", "drive_type": "BEV", "sales_share": 1.0},
        ])

        t11 = build_leap_ready_table(t9, t10, t6, t7, projection_years=[2022])

        assert "Activity Level" not in set(t11["variable"])
        assert not t11[(t11["variable"] == "Sales") & (t11["leap_branch_path"] == "Demand\\Freight road")].empty
        assert not t11[(t11["variable"] == "Stock") & (t11["leap_branch_path"] == "Demand\\Freight road")].empty
        assert not t11[(t11["variable"] == "Stock") & (t11["leap_branch_path"] == "Demand\\Freight road\\Trucks")].empty
        assert not t11[(t11["variable"] == "Mileage") & (t11["leap_branch_path"].str.endswith("\\Gas and diesel oil"))].empty
        assert not t11[(t11["variable"] == "Stock Share") & (t11["leap_branch_path"] == "Demand\\Freight road\\LCVs")].empty
        assert not t11[(t11["variable"] == "Sales Share") & (t11["leap_branch_path"] == "Demand\\Freight road\\LCVs")].empty
        assert not t11[(t11["variable"] == "Sales Share") & (t11["leap_branch_path"] == "Demand\\Freight road\\LCVs\\BEV")].empty

    def test_leap_ready_sales_share_with_null_size_is_finite(self):
        t9 = pd.DataFrame([
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "base_year": 2022,
                "transport_type": "passenger",
                "vehicle_type": "Buses",
                "drive_type": "FCEV",
                "size": None,
                "fuel": "Hydrogen",
                "leap_branch_path": "Demand\\Passenger road\\Buses\\FCEV\\Hydrogen",
                "adjusted_stock": 10.0,
                "adjusted_mileage_km_per_year": 45000.0,
                "adjusted_efficiency_km_per_gj": 120.0,
                "final_branch_fuel_pj": 0.00375,
            },
        ])
        t10 = pd.DataFrame([
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "leap_branch_path": "Demand\\Passenger road\\Buses\\FCEV\\Hydrogen",
                "device_share": 1.0,
            }
        ])
        t7 = pd.DataFrame([
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2023,
                "transport_type": "passenger",
                "vehicle_type": "Buses",
                "drive_type": "FCEV",
                "sales_share": 1.0,
            }
        ])

        t11 = build_leap_ready_table(t9, t10, pd.DataFrame(), t7, projection_years=[2022, 2023])
        sales_share = t11[
            (t11["variable"] == "Sales Share")
            & (t11["leap_branch_path"] == "Demand\\Passenger road\\Buses\\FCEV")
            & (t11["year"] == 2023)
        ]

        assert len(sales_share) == 1
        assert sales_share.iloc[0]["value"] == pytest.approx(100.0)
        assert np.isfinite(sales_share.iloc[0]["value"])

    def test_leap_ready_table_exports_correction_factors(self):
        t9 = pd.DataFrame([
            {
                "economy": "20_USA",
                "scenario": "Target",
                "base_year": 2022,
                "transport_type": "freight",
                "vehicle_type": "LCVs",
                "drive_type": "BEV",
                "size": None,
                "fuel": "Electricity",
                "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
                "adjusted_stock": 300.0,
                "adjusted_mileage_km_per_year": 8000.0,
                "adjusted_efficiency_km_per_gj": 200.0,
                "final_branch_fuel_pj": 0.012,
            },
        ])
        t10 = pd.DataFrame([
            {
                "economy": "20_USA",
                "scenario": "Target",
                "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
                "device_share": 1.0,
            }
        ])
        factors = pd.DataFrame([
            {
                "economy": "20_USA",
                "scenario": "Target",
                "year": 2030,
                "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV\\Electricity",
                "value": 0.95,
            }
        ])

        t11 = build_leap_ready_table(
            t9,
            t10,
            pd.DataFrame(),
            pd.DataFrame(),
            projection_years=[2022, 2030],
            mileage_correction_factors=factors,
            fuel_economy_correction_factors=factors.assign(value=1.05),
        )

        mileage_factor = t11[t11["variable"].eq("Mileage Correction Factor")].iloc[0]
        efficiency_factor = t11[t11["variable"].eq("Fuel Economy Correction Factor")].iloc[0]
        assert mileage_factor["year"] == 2030
        assert mileage_factor["value"] == pytest.approx(0.95)
        assert efficiency_factor["value"] == pytest.approx(1.05)

    def test_t11_has_no_duplicate_keys_for_four_level_paths(self):
        """
        Regression: for 4-level LEAP paths (drive type is the leaf, no separate
        fuel branch), _tech_path == _vehicle_path.  The tech-level Stock Share
        loop previously wrote drive-type shares at the vehicle path, producing
        multiple rows with the same (economy, scenario, leap_branch_path,
        variable, year) key.
        """
        t9 = pd.DataFrame([
            {
                "economy": "20_USA", "scenario": "Target", "base_year": 2022,
                "transport_type": "freight", "vehicle_type": "LCVs",
                "drive_type": "Diesel", "size": None,
                "leap_branch_path": "Demand\\Freight road\\LCVs\\Diesel",
                "adjusted_stock": 80.0,
                "adjusted_mileage_km_per_year": 15_000.0,
                "adjusted_efficiency_km_per_gj": 250.0,
                "final_branch_fuel_pj": 4.8,
            },
            {
                "economy": "20_USA", "scenario": "Target", "base_year": 2022,
                "transport_type": "freight", "vehicle_type": "LCVs",
                "drive_type": "BEV", "size": None,
                "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV",
                "adjusted_stock": 20.0,
                "adjusted_mileage_km_per_year": 15_000.0,
                "adjusted_efficiency_km_per_gj": 400.0,
                "final_branch_fuel_pj": 0.75,
            },
        ])
        t10 = pd.DataFrame([
            {"economy": "20_USA", "scenario": "Target",
             "leap_branch_path": "Demand\\Freight road\\LCVs\\Diesel", "device_share": 1.0},
            {"economy": "20_USA", "scenario": "Target",
             "leap_branch_path": "Demand\\Freight road\\LCVs\\BEV", "device_share": 1.0},
        ])

        t11 = build_leap_ready_table(t9, t10, pd.DataFrame(), pd.DataFrame(), projection_years=[2022])

        key_cols = ["economy", "scenario", "leap_branch_path", "variable", "year"]
        dup_mask = t11.duplicated(subset=key_cols, keep=False)
        dup_count = dup_mask.sum()
        assert dup_count == 0, (
            f"T11 has {dup_count} rows with duplicate keys:\n"
            + t11.loc[dup_mask, key_cols + ["value"]].to_string()
        )

        # For 4-level paths the drive type IS the leaf — there is no distinct
        # drive-type path, so no tech-level Stock Share is emitted below the vehicle.
        # The vehicle-level Stock Share (LCVs as % of Freight road) must appear exactly once.
        vehicle_share = t11[
            (t11["variable"] == "Stock Share")
            & (t11["leap_branch_path"] == "Demand\\Freight road\\LCVs")
        ]
        assert len(vehicle_share) == 1, "Vehicle-level Stock Share should appear exactly once"
        assert vehicle_share.iloc[0]["value"] == pytest.approx(100.0)
