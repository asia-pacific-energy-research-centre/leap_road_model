from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - depends on runtime environment
    matplotlib = None
    plt = None


def _module_dir(root: str | Path, module_name: str) -> Path:
    out = Path(root) / module_name
    out.mkdir(parents=True, exist_ok=True)
    return out


def _save(fig: plt.Figure, path: Path) -> Path:
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").dropna()


def _annual_survival_to_cumulative_probability(annual_survival: pd.Series) -> pd.Series:
    """Convert annual survival probabilities p(age) to cumulative survival S(age)."""
    annual = pd.Series(annual_survival, dtype=float).sort_index().clip(0.0, 1.0)
    if annual.empty:
        return annual

    cumulative_values: list[float] = []
    current = 1.0
    for idx, age in enumerate(annual.index):
        if idx > 0:
            previous_age = annual.index[idx - 1]
            current *= float(annual.loc[previous_age])
        cumulative_values.append(current)
    return pd.Series(cumulative_values, index=annual.index, dtype=float)


def _can_plot() -> bool:
    return plt is not None


def write_module1_charts(merged_inputs: pd.DataFrame, diagnostics_dir: str | Path) -> list[Path]:
    """Write Module 1 QA charts from T3_merged_inputs."""
    if not _can_plot() or merged_inputs is None or merged_inputs.empty:
        return []

    out = _module_dir(diagnostics_dir, "module1")
    saved: list[Path] = []

    if {"variable", "source_flag"}.issubset(merged_inputs.columns):
        c = (
            merged_inputs.groupby(["variable", "source_flag"]).size()
            .unstack(fill_value=0)
            .sort_index()
        )
        fig, ax = plt.subplots(figsize=(9, 5))
        c.plot(kind="bar", stacked=True, ax=ax)
        ax.set_title("Module 1: Source flags by variable")
        ax.set_xlabel("Variable")
        ax.set_ylabel("Row count")
        ax.legend(title="source_flag", fontsize=8)
        saved.append(_save(fig, out / "module1_source_flags_by_variable.png"))

    if "value" in merged_inputs.columns and "variable" in merged_inputs.columns:
        fig, ax = plt.subplots(figsize=(9, 5))
        top_vars = merged_inputs["variable"].value_counts().head(8).index.tolist()
        box_df = merged_inputs[merged_inputs["variable"].isin(top_vars)].copy()
        box_df["value"] = _safe_numeric(box_df["value"]).reindex(box_df.index)
        box_df = box_df.dropna(subset=["value"])
        if not box_df.empty:
            groups = [box_df.loc[box_df["variable"] == v, "value"].to_numpy() for v in top_vars]
            ax.boxplot(groups, labels=top_vars, showfliers=False)
            ax.set_title("Module 1: Value distribution by variable")
            ax.set_ylabel("Value")
            ax.tick_params(axis="x", rotation=30)
            saved.append(_save(fig, out / "module1_value_distribution.png"))
        else:
            plt.close(fig)

    missing_pct = (merged_inputs.isna().mean() * 100.0).sort_values(ascending=False)
    if not missing_pct.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        missing_pct.plot(kind="bar", ax=ax, color="#EF6C00")
        ax.set_title("Module 1: Missingness by column")
        ax.set_ylabel("Missing (%)")
        ax.set_ylim(0, 100)
        ax.tick_params(axis="x", rotation=45)
        saved.append(_save(fig, out / "module1_missingness_by_column.png"))

    return saved


def write_module2_charts(t4: pd.DataFrame, diagnostics_dir: str | Path) -> list[Path]:
    """Write Module 2 QA charts from T4_base_year_branches."""
    if not _can_plot() or t4 is None or t4.empty:
        return []

    out = _module_dir(diagnostics_dir, "module2")
    saved: list[Path] = []

    if {"vehicle_type", "drive_type"}.issubset(t4.columns):
        pv = t4.pivot_table(index="vehicle_type", columns="drive_type", values="fuel", aggfunc="count", fill_value=0)
        fig, ax = plt.subplots(figsize=(8, 5))
        im = ax.imshow(pv.to_numpy(), aspect="auto")
        ax.set_title("Module 2: Branch count heatmap (vehicle × drive)")
        ax.set_xticks(range(len(pv.columns)), labels=pv.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(pv.index)), labels=pv.index)
        fig.colorbar(im, ax=ax, label="Branch count")
        saved.append(_save(fig, out / "module2_branch_count_heatmap.png"))

    flag_cols = [c for c in ["stock_source_flag", "mileage_source_flag", "efficiency_source_flag"] if c in t4.columns]
    if flag_cols:
        rows = []
        for col in flag_cols:
            vc = t4[col].fillna("missing").value_counts()
            for flag, count in vc.items():
                rows.append({"metric": col.replace("_source_flag", ""), "source_flag": flag, "count": count})
        ff = pd.DataFrame(rows)
        if not ff.empty:
            p = ff.pivot_table(index="metric", columns="source_flag", values="count", aggfunc="sum", fill_value=0)
            fig, ax = plt.subplots(figsize=(8, 5))
            p.plot(kind="bar", stacked=True, ax=ax)
            ax.set_title("Module 2: Source flag coverage")
            ax.set_xlabel("Metric")
            ax.set_ylabel("Row count")
            ax.legend(title="source_flag", fontsize=8)
            saved.append(_save(fig, out / "module2_source_flag_coverage.png"))

    num_cols = [c for c in ["stock", "mileage_km_per_year", "efficiency_km_per_gj"] if c in t4.columns]
    if num_cols:
        fig, axes = plt.subplots(1, len(num_cols), figsize=(5 * len(num_cols), 4))
        if len(num_cols) == 1:
            axes = [axes]
        for ax, col in zip(axes, num_cols):
            vals = _safe_numeric(t4[col])
            if len(vals) > 0:
                ax.hist(vals, bins=30, color="#1E88E5", alpha=0.8)
            ax.set_title(col)
        fig.suptitle("Module 2: Base-year metric distributions")
        saved.append(_save(fig, out / "module2_metric_distributions.png"))

    return saved


def write_module3_charts(t5: pd.DataFrame, diagnostics_dir: str | Path) -> list[Path]:
    """Write Module 3 QA charts from T5_stock_targets."""
    if not _can_plot() or t5 is None or t5.empty:
        return []

    out = _module_dir(diagnostics_dir, "module3")
    saved: list[Path] = []

    req = {"year", "transport_type", "vehicle_type", "target_stock"}
    if req.issubset(t5.columns):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=False)
        for ax, tt in zip(axes, ["passenger", "freight"]):
            sub = t5[t5["transport_type"] == tt]
            if sub.empty:
                ax.set_title(f"{tt.title()} (no data)")
                continue
            for vt, grp in sub.groupby("vehicle_type"):
                series = grp.groupby("year")["target_stock"].sum().sort_index()
                ax.plot(series.index, series.values, label=vt)
            ax.set_title(f"{tt.title()} target stocks")
            ax.set_xlabel("Year")
            ax.set_ylabel("Target stock")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
        fig.suptitle("Module 3: Target stock trajectories")
        saved.append(_save(fig, out / "module3_target_stock_trajectories.png"))

    if {"year", "motorisation_level"}.issubset(t5.columns):
        sub = t5[t5["transport_type"] == "passenger"].copy()
        if not sub.empty:
            line = (sub.groupby("year")["motorisation_level"].mean() * 1000.0).dropna().sort_index()
            sat = (sub.groupby("year")["saturation_level"].mean() * 1000.0).dropna().sort_index() if "saturation_level" in sub.columns else pd.Series(dtype=float)
            orig_sat = (sub.groupby("year")["original_saturation_level"].mean() * 1000.0).dropna().sort_index() if "original_saturation_level" in sub.columns else pd.Series(dtype=float)
            sat_was_adjusted = bool(sub["saturation_was_adjusted"].fillna(False).any()) if "saturation_was_adjusted" in sub.columns else False
            fig, ax = plt.subplots(figsize=(9, 4))
            if not line.empty:
                ax.plot(line.index, line.values, label="Projected X-LPV-equivalent vehicles", color="#6A1B9A")
            if not sat.empty:
                ax.plot(sat.index, sat.values, label="Saturation level", color="#EF6C00", linestyle="--")
            if sat_was_adjusted and not orig_sat.empty:
                ax.plot(orig_sat.index, orig_sat.values, label="Original saturation level (reduced — calibration bounds exceeded)", color="#2E7D32", linestyle="--")
            ax.set_title("Module 3: Passenger X-LPV-equivalent vehicles")
            ax.set_xlabel("Year")
            ax.set_ylabel("X-LPV-equivalent vehicles per 1,000 people")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            saved.append(_save(fig, out / "module3_motorisation_envelope.png"))

    weight_cols = {
        "vehicle_type",
        "original_vehicle_equivalent_weight",
        "adjusted_vehicle_equivalent_weight",
    }
    if weight_cols.issubset(t5.columns):
        bound_cols = [c for c in ["weight_lower_bound", "weight_upper_bound"] if c in t5.columns]
        weights_df = (
            t5[t5["transport_type"] == "passenger"]
            [["vehicle_type", "original_vehicle_equivalent_weight", "adjusted_vehicle_equivalent_weight"] + bound_cols]
            .dropna(subset=["vehicle_type"])
            .drop_duplicates("vehicle_type")
            .sort_values("vehicle_type")
            .reset_index(drop=True)
        )
        if not weights_df.empty:
            fig, ax = plt.subplots(figsize=(7, 4))
            x = np.arange(len(weights_df))
            width = 0.35
            ax.bar(
                x - width / 2,
                weights_df["original_vehicle_equivalent_weight"],
                width,
                label="Original",
                color="#5E6AD2",
            )
            ax.bar(
                x + width / 2,
                weights_df["adjusted_vehicle_equivalent_weight"],
                width,
                label="Adjusted",
                color="#EF6C00",
            )
            # Draw dotted bound lines for each vehicle type that has bounds
            if "weight_lower_bound" in weights_df.columns and "weight_upper_bound" in weights_df.columns:
                for i, row_data in weights_df.iterrows():
                    lb = row_data["weight_lower_bound"]
                    ub = row_data["weight_upper_bound"]
                    if pd.notna(lb) and pd.notna(ub):
                        ax.plot([i - width, i + width], [lb, lb], color="black", linestyle=":", linewidth=1.2)
                        ax.plot([i - width, i + width], [ub, ub], color="black", linestyle=":", linewidth=1.2)
                        ax.plot([i, i], [lb, ub], color="black", linestyle=":", linewidth=1.2)
            ax.set_xticks(x)
            ax.set_xticklabels(weights_df["vehicle_type"])
            ax.set_title("Module 3: Passenger X-LPV weight calibration")
            ax.set_ylabel("X-LPV-equivalent weight")
            ax.legend(fontsize=8)
            ax.grid(axis="y", alpha=0.3)
            saved.append(_save(fig, out / "module3_xlpv_weight_calibration.png"))

    if {"vehicle_type", "gdp_elasticity_used"}.issubset(t5.columns):
        el = t5[["vehicle_type", "gdp_elasticity_used"]].dropna().drop_duplicates()
        if not el.empty:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.bar(el["vehicle_type"], el["gdp_elasticity_used"], color="#00897B")
            ax.set_title("Module 3: Freight elasticity by vehicle type")
            ax.set_ylabel("Elasticity")
            ax.tick_params(axis="x", rotation=30)
            saved.append(_save(fig, out / "module3_freight_elasticity.png"))

    diag_cols = {
        "vehicle_type",
        "gdp_elasticity_used",
        "freight_raw_elasticity",
        "freight_energy_growth_rate",
        "freight_gdp_growth_rate",
        "freight_elasticity_data_source",
    }
    if diag_cols.issubset(t5.columns):
        diag = (
            t5[t5["transport_type"] == "freight"]
            [[*diag_cols]]
            .drop_duplicates("vehicle_type")
            .sort_values("vehicle_type")
        )
        if not diag.empty:
            fig, axes = plt.subplots(1, 2, figsize=(11, 4))
            x = np.arange(len(diag))
            width = 0.35
            axes[0].bar(
                x - width / 2,
                pd.to_numeric(diag["freight_raw_elasticity"], errors="coerce"),
                width,
                label="raw",
                color="#B0BEC5",
            )
            axes[0].bar(
                x + width / 2,
                pd.to_numeric(diag["gdp_elasticity_used"], errors="coerce"),
                width,
                label="final",
                color="#00897B",
            )
            axes[0].set_xticks(x)
            axes[0].set_xticklabels(diag["vehicle_type"], rotation=30)
            axes[0].set_title("Freight elasticity")
            axes[0].set_ylabel("Elasticity")
            axes[0].legend(fontsize=8)
            axes[0].grid(axis="y", alpha=0.3)

            axes[1].bar(
                x - width / 2,
                pd.to_numeric(diag["freight_energy_growth_rate"], errors="coerce") * 100,
                width,
                label="energy",
                color="#5E6AD2",
            )
            axes[1].bar(
                x + width / 2,
                pd.to_numeric(diag["freight_gdp_growth_rate"], errors="coerce") * 100,
                width,
                label="GDP",
                color="#EF6C00",
            )
            axes[1].set_xticks(x)
            axes[1].set_xticklabels(diag["vehicle_type"], rotation=30)
            axes[1].set_title("Lookback growth rates")
            axes[1].set_ylabel("Annual growth (%)")
            axes[1].legend(fontsize=8)
            axes[1].grid(axis="y", alpha=0.3)
            fig.suptitle("Module 3: Freight elasticity diagnostics")
            saved.append(_save(fig, out / "module3_freight_elasticity_diagnostics.png"))

    return saved


def write_module4_charts(t6: pd.DataFrame, t6v: pd.DataFrame, diagnostics_dir: str | Path) -> list[Path]:
    """Write Module 4 QA charts from T6 and T6v outputs."""
    if not _can_plot():
        return []

    saved: list[Path] = []
    out = _module_dir(diagnostics_dir, "module4")

    if t6 is not None and not t6.empty and {"year", "vehicle_type", "new_sales"}.issubset(t6.columns):
        fig, ax = plt.subplots(figsize=(10, 4))
        for vt, grp in t6.groupby("vehicle_type"):
            s = grp.groupby("year")["new_sales"].sum().sort_index()
            ax.plot(s.index, s.values, label=vt)
        ax.set_title("Module 4: New sales by vehicle type")
        ax.set_xlabel("Year")
        ax.set_ylabel("New sales")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module4_new_sales_by_vehicle_type.png"))

    if t6 is not None and not t6.empty and {"year", "natural_retirements", "additional_retirements"}.issubset(t6.columns):
        rr = t6.groupby("year")[["natural_retirements", "additional_retirements"]].sum().sort_index()
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.stackplot(rr.index, rr["natural_retirements"], rr["additional_retirements"], labels=["natural", "additional"], alpha=0.85)
        ax.set_title("Module 4: Retirements by type")
        ax.set_xlabel("Year")
        ax.set_ylabel("Vehicles retired")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module4_retirements_stack.png"))

    if t6v is not None and not t6v.empty and {"vehicle_type", "age", "vintage_share"}.issubset(t6v.columns):
        fig, ax = plt.subplots(figsize=(10, 4))
        for vt, grp in t6v.groupby("vehicle_type"):
            g = grp.sort_values("age")
            ax.plot(g["age"], g["vintage_share"], label=vt)
        ax.set_title("Module 4: Base-year vintage profiles")
        ax.set_xlabel("Age")
        ax.set_ylabel("Vintage share")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module4_vintage_profiles.png"))

    if t6v is not None and not t6v.empty and {"vehicle_type", "age", "survival_probability"}.issubset(t6v.columns):
        fig, ax = plt.subplots(figsize=(10, 4))
        for vt, grp in t6v.groupby("vehicle_type"):
            g = grp.sort_values("age")
            cumulative = _annual_survival_to_cumulative_probability(
                g.set_index("age")["survival_probability"]
            )
            ax.plot(cumulative.index, cumulative.values, label=vt)
        ax.set_title("Module 4: Base-year survival curves")
        ax.set_xlabel("Age")
        ax.set_ylabel("Cumulative survival probability")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module4_survival_curves.png"))

    if t6 is not None and not t6.empty and {"new_sales", "target_stock", "year"}.issubset(t6.columns):
        tmp = t6.groupby("year")[["new_sales", "target_stock"]].sum().sort_index()
        tmp["sales_to_stock_ratio"] = np.where(tmp["target_stock"] > 0, tmp["new_sales"] / tmp["target_stock"], np.nan)
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(tmp.index, tmp["sales_to_stock_ratio"], color="#5E35B1")
        ax.set_title("Module 4: Sales / stock ratio")
        ax.set_xlabel("Year")
        ax.set_ylabel("Ratio")
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module4_sales_to_stock_ratio.png"))

    event_cols = {"year", "vehicle_type", "stock_above_target"}
    if t6 is not None and not t6.empty and event_cols.issubset(t6.columns):
        events = t6[t6["stock_above_target"].fillna(False).astype(bool)].copy()
        if not events.empty:
            counts = events.groupby(["year", "vehicle_type"]).size().unstack(fill_value=0).sort_index()
            fig, ax = plt.subplots(figsize=(10, 4))
            bottom = np.zeros(len(counts))
            for idx, vt in enumerate(counts.columns):
                values = counts[vt].to_numpy()
                ax.bar(counts.index, values, bottom=bottom, label=str(vt))
                bottom += values
            ax.set_title("Module 4: Stock above target events")
            ax.set_xlabel("Year")
            ax.set_ylabel("Event count")
            ax.legend(fontsize=8)
            ax.grid(axis="y", alpha=0.3)
            saved.append(_save(fig, out / "module4_stock_above_target_events.png"))

    return saved


def write_module6_charts(module6_outputs: dict[str, pd.DataFrame], diagnostics_dir: str | Path) -> list[Path]:
    """Write Module 6 QA charts from T8–T12 outputs."""
    if not _can_plot() or not module6_outputs:
        return []

    out = _module_dir(diagnostics_dir, "module6")
    saved: list[Path] = []

    t8 = module6_outputs.get("T8", pd.DataFrame())
    t9 = module6_outputs.get("T9", pd.DataFrame())
    t10 = module6_outputs.get("T10", pd.DataFrame())
    t12 = module6_outputs.get("T12", pd.DataFrame())
    t5_pre = module6_outputs.get("T5_pre_reconciliation", pd.DataFrame())
    t5_post = module6_outputs.get("T5_post_reconciliation", pd.DataFrame())

    if t12 is not None and not t12.empty and {"fuel", "remaining_esto_pj", "post_reconciliation_model_pj"}.issubset(t12.columns):
        x = np.arange(len(t12))
        width = 0.25
        fig, ax = plt.subplots(figsize=(11, 4))
        has_pre = "pre_reconciliation_model_pj" in t12.columns
        if has_pre:
            ax.bar(x - width, t12["pre_reconciliation_model_pj"], width=width, label="pre_model")
            ax.bar(x, t12["remaining_esto_pj"], width=width, label="esto_target")
            ax.bar(x + width, t12["post_reconciliation_model_pj"], width=width, label="post_model")
        else:
            ax.bar(x - width / 2, t12["remaining_esto_pj"], width=width, label="esto_target")
            ax.bar(x + width / 2, t12["post_reconciliation_model_pj"], width=width, label="post_model")
        ax.set_xticks(x, t12["fuel"], rotation=30, ha="right")
        ax.set_title("Module 6: Fuel reconciliation check")
        ax.set_ylabel("Energy (PJ)")
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        saved.append(_save(fig, out / "module6_fuel_reconciliation_check.png"))

    scalar_cols = [c for c in ["stock_scalar", "mileage_scalar", "efficiency_scalar"] if c in t9.columns]
    if t9 is not None and not t9.empty and scalar_cols:
        fig, axes = plt.subplots(1, len(scalar_cols), figsize=(5 * len(scalar_cols), 4))
        if len(scalar_cols) == 1:
            axes = [axes]
        for ax, col in zip(axes, scalar_cols):
            vals = _safe_numeric(t9[col])
            if len(vals) > 0:
                ax.hist(vals, bins=30, alpha=0.85, color="#3949AB")
            ax.set_title(col)
        fig.suptitle("Module 6: Reconciliation scalar distributions")
        saved.append(_save(fig, out / "module6_scalar_distributions.png"))

    if t9 is not None and not t9.empty and {"fuel", "initial_branch_energy_pj", "allocated_branch_fuel_pj"}.issubset(t9.columns):
        df = t9.copy()
        df["initial_branch_energy_pj"] = pd.to_numeric(df["initial_branch_energy_pj"], errors="coerce").fillna(0.0)
        df["allocated_branch_fuel_pj"] = pd.to_numeric(df["allocated_branch_fuel_pj"], errors="coerce").fillna(0.0)
        stats = (
            df.groupby("fuel")[["initial_branch_energy_pj", "allocated_branch_fuel_pj"]]
            .sum()
        )
        stats["weighted_correction_factor"] = (
            stats["allocated_branch_fuel_pj"] / stats["initial_branch_energy_pj"].replace(0.0, np.nan)
        )
        stats = stats["weighted_correction_factor"].sort_values(ascending=False)
        if not stats.empty:
            fig, ax = plt.subplots(figsize=(9, 4))
            ax.bar(stats.index, stats.values, color="#00897B")
            ax.set_title("Module 6: Initial-energy weighted correction factor by fuel")
            ax.set_ylabel("Allocated fuel / initial branch energy")
            ax.tick_params(axis="x", rotation=35)
            ax.grid(axis="y", alpha=0.3)
            saved.append(_save(fig, out / "module6_ecf_by_fuel.png"))

    if t10 is not None and not t10.empty and {"drive_type", "fuel", "device_share"}.issubset(t10.columns):
        sub = t10[t10["drive_type"].isin(["ICE", "PHEV"])].copy()
        if not sub.empty:
            ds = sub.groupby(["drive_type", "fuel"])["device_share"].mean().reset_index()
            labels = ds.apply(lambda r: f"{r['drive_type']}|{r['fuel']}", axis=1)
            fig, ax = plt.subplots(figsize=(11, 4))
            ax.bar(labels, ds["device_share"], color="#6D4C41")
            ax.set_title("Module 6: Mean device share by drive/fuel")
            ax.set_ylabel("Device share")
            ax.tick_params(axis="x", rotation=45, labelsize=8)
            ax.grid(axis="y", alpha=0.3)
            saved.append(_save(fig, out / "module6_device_share_by_drive_fuel.png"))

    if t8 is not None and not t8.empty and {"fuel", "branch_allocation_share"}.issubset(t8.columns):
        top = (
            t8.groupby("fuel")["branch_allocation_share"].max()
            .sort_values(ascending=False)
        )
        if not top.empty:
            fig, ax = plt.subplots(figsize=(9, 4))
            ax.bar(top.index, top.values, color="#F4511E")
            ax.set_title("Module 6: Max branch allocation share by fuel")
            ax.set_ylabel("Max allocation share")
            ax.tick_params(axis="x", rotation=30)
            ax.grid(axis="y", alpha=0.3)
            saved.append(_save(fig, out / "module6_allocation_concentration.png"))

    stock_cols = {"year", "vehicle_type", "target_stock"}
    if (
        t5_pre is not None
        and t5_post is not None
        and not t5_pre.empty
        and not t5_post.empty
        and stock_cols.issubset(t5_pre.columns)
        and stock_cols.issubset(t5_post.columns)
    ):
        pre = t5_pre.copy()
        post = t5_post.copy()
        pre["target_stock"] = pd.to_numeric(pre["target_stock"], errors="coerce")
        post["target_stock"] = pd.to_numeric(post["target_stock"], errors="coerce")
        pre_series = pre.groupby(["year", "vehicle_type"])["target_stock"].sum().reset_index()
        post_series = post.groupby(["year", "vehicle_type"])["target_stock"].sum().reset_index()
        vehicle_types = sorted(set(pre_series["vehicle_type"]).union(post_series["vehicle_type"]))
        if vehicle_types:
            fig, ax = plt.subplots(figsize=(11, 5))
            colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", [])
            for idx, vt in enumerate(vehicle_types):
                color = colors[idx % len(colors)] if colors else None
                pre_vt = pre_series[pre_series["vehicle_type"] == vt].sort_values("year")
                post_vt = post_series[post_series["vehicle_type"] == vt].sort_values("year")
                if not pre_vt.empty:
                    ax.plot(
                        pre_vt["year"],
                        pre_vt["target_stock"],
                        linestyle="--",
                        linewidth=1.4,
                        color=color,
                        alpha=0.65,
                        label=f"{vt} pre",
                    )
                if not post_vt.empty:
                    ax.plot(
                        post_vt["year"],
                        post_vt["target_stock"],
                        linestyle="-",
                        linewidth=2.0,
                        color=color,
                        label=f"{vt} post",
                    )
            ax.set_title("Module 6: Stock trajectory after base-year reconciliation")
            ax.set_xlabel("Year")
            ax.set_ylabel("Vehicles")
            ax.legend(fontsize=8, ncol=2)
            ax.grid(alpha=0.3)
            saved.append(_save(fig, out / "module6_stock_trajectory_reconciliation.png"))

    return saved


def write_module7_charts(module7_outputs: dict[str, pd.DataFrame], diagnostics_dir: str | Path) -> list[Path]:
    """Write Module 7 QA charts from T13 mirror outputs."""
    if not _can_plot() or not module7_outputs:
        return []

    out = _module_dir(diagnostics_dir, "module7")
    saved: list[Path] = []

    t13 = module7_outputs.get("T13", pd.DataFrame())
    t13_fuel = module7_outputs.get("T13_fuel", pd.DataFrame())

    if t13 is not None and not t13.empty and {"year", "vehicle_type", "mirror_stock"}.issubset(t13.columns):
        fig, ax = plt.subplots(figsize=(10, 4))
        for vt, grp in t13.groupby("vehicle_type"):
            s = grp.groupby("year")["mirror_stock"].sum().sort_index()
            ax.plot(s.index, s.values, label=vt)
        ax.set_title("Module 7: Mirror stock by vehicle type")
        ax.set_xlabel("Year")
        ax.set_ylabel("Vehicles")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module7_mirror_stock_by_vehicle_type.png"))

    if t13 is not None and not t13.empty and {"year", "vehicle_type", "mirror_vehicle_km"}.issubset(t13.columns):
        fig, ax = plt.subplots(figsize=(10, 4))
        for vt, grp in t13.groupby("vehicle_type"):
            s = grp.groupby("year")["mirror_vehicle_km"].sum().sort_index()
            ax.plot(s.index, s.values, label=vt)
        ax.set_title("Module 7: Mirror vehicle-km by vehicle type")
        ax.set_xlabel("Year")
        ax.set_ylabel("Vehicle-km")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        saved.append(_save(fig, out / "module7_mirror_vehicle_km_by_vehicle_type.png"))

    if t13 is not None and not t13.empty and {"year", "transport_type", "mirror_energy_pj"}.issubset(t13.columns):
        energy = (
            t13.groupby(["year", "transport_type"])["mirror_energy_pj"]
            .sum()
            .unstack(fill_value=0.0)
            .sort_index()
        )
        if not energy.empty:
            fig, ax = plt.subplots(figsize=(10, 4))
            energy.plot(kind="area", stacked=True, ax=ax, alpha=0.85)
            ax.set_title("Module 7: Mirror energy by transport type")
            ax.set_xlabel("Year")
            ax.set_ylabel("Energy (PJ)")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            saved.append(_save(fig, out / "module7_mirror_energy_by_transport_type.png"))

    if t13_fuel is not None and not t13_fuel.empty and {"year", "fuel", "mirror_fuel_energy_pj"}.issubset(t13_fuel.columns):
        fuel_energy = (
            t13_fuel.groupby(["year", "fuel"])["mirror_fuel_energy_pj"]
            .sum()
            .unstack(fill_value=0.0)
            .sort_index()
        )
        if not fuel_energy.empty:
            fig, ax = plt.subplots(figsize=(11, 4))
            fuel_energy.plot(kind="area", stacked=True, ax=ax, alpha=0.85)
            ax.set_title("Module 7: Mirror fuel energy mix")
            ax.set_xlabel("Year")
            ax.set_ylabel("Fuel energy (PJ)")
            ax.legend(fontsize=8, ncol=2)
            ax.grid(alpha=0.3)
            saved.append(_save(fig, out / "module7_mirror_fuel_energy_mix.png"))

    if t13 is not None and not t13.empty and {"mirror_energy_pj", "leap_energy_pj", "year"}.issubset(t13.columns):
        comp = t13.dropna(subset=["leap_energy_pj"]).copy()
        if not comp.empty:
            comp["energy_difference_pj"] = pd.to_numeric(comp["mirror_energy_pj"], errors="coerce") - pd.to_numeric(comp["leap_energy_pj"], errors="coerce")
            diff = comp.groupby("year")["energy_difference_pj"].sum().sort_index()
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.axhline(0.0, color="#333333", linewidth=0.8)
            ax.bar(diff.index, diff.values, color="#D81B60")
            ax.set_title("Module 7: Mirror minus LEAP energy")
            ax.set_xlabel("Year")
            ax.set_ylabel("Energy difference (PJ)")
            ax.grid(axis="y", alpha=0.3)
            saved.append(_save(fig, out / "module7_mirror_vs_leap_energy_difference.png"))

    return saved


def write_workflow_summary_charts(
    workflow_outputs: dict[str, pd.DataFrame | dict | list | str | int | float],
    diagnostics_dir: str | Path,
) -> list[Path]:
    """Write end-of-process workflow summary figures from Module 6/7 outputs."""
    if not _can_plot() or not workflow_outputs:
        return []

    out = _module_dir(diagnostics_dir, "workflow")
    saved: list[Path] = []

    t12 = workflow_outputs.get("T12", pd.DataFrame())
    t13 = workflow_outputs.get("T13", pd.DataFrame())
    t13_fuel = workflow_outputs.get("T13_fuel", pd.DataFrame())
    timings = workflow_outputs.get("timings", {}) if isinstance(workflow_outputs.get("timings"), dict) else {}

    if t12 is not None and not t12.empty:
        fig, axes = plt.subplots(2, 2, figsize=(15, 9))
        axes = axes.flatten()

        if {"fuel", "gap_pct"}.issubset(t12.columns):
            g = t12[["fuel", "gap_pct"]].copy().sort_values("gap_pct", ascending=False)
            axes[0].bar(g["fuel"], g["gap_pct"], color="#EF6C00")
            axes[0].set_title("Module 6 reconciliation gap by fuel")
            axes[0].set_ylabel("Gap (%)")
            axes[0].tick_params(axis="x", rotation=35)
            axes[0].grid(axis="y", alpha=0.3)
        else:
            axes[0].set_visible(False)

        if {"fuel", "remaining_esto_pj", "post_reconciliation_model_pj"}.issubset(t12.columns):
            g = t12[["fuel", "remaining_esto_pj", "post_reconciliation_model_pj"]].copy()
            x = np.arange(len(g))
            width = 0.35
            axes[1].bar(x - width / 2, g["remaining_esto_pj"], width=width, label="ESTO target")
            axes[1].bar(x + width / 2, g["post_reconciliation_model_pj"], width=width, label="Post-model")
            axes[1].set_xticks(x, g["fuel"], rotation=35, ha="right")
            axes[1].set_title("Module 6 post-reconciliation check")
            axes[1].set_ylabel("Energy (PJ)")
            axes[1].legend(fontsize=8)
            axes[1].grid(axis="y", alpha=0.3)
        else:
            axes[1].set_visible(False)

        if timings:
            order = [k for k in sorted(timings.keys()) if k.endswith("_seconds")]
            vals = [timings[k] for k in order]
            labels = [k.replace("_seconds", "") for k in order]
            axes[2].bar(labels, vals, color="#3949AB")
            axes[2].set_title("Workflow timings")
            axes[2].set_ylabel("Seconds")
            axes[2].tick_params(axis="x", rotation=30)
            axes[2].grid(axis="y", alpha=0.3)
        else:
            axes[2].set_visible(False)

        statuses = t12["reconciliation_status"].value_counts() if "reconciliation_status" in t12.columns else pd.Series(dtype=int)
        if not statuses.empty:
            axes[3].pie(statuses.values, labels=statuses.index, autopct="%1.0f%%")
            axes[3].set_title("Reconciliation status share")
        else:
            axes[3].set_visible(False)

        fig.suptitle("Workflow summary dashboard — Module 6")
        fig.tight_layout()
        saved.append(_save(fig, out / "workflow_summary_module6_dashboard.png"))

    if t13 is not None and not t13.empty:
        fig, axes = plt.subplots(2, 2, figsize=(15, 9))
        axes = axes.flatten()

        if {"year", "vehicle_type", "mirror_stock"}.issubset(t13.columns):
            for vt, grp in t13.groupby("vehicle_type"):
                s = grp.groupby("year")["mirror_stock"].sum().sort_index()
                axes[0].plot(s.index, s.values, label=vt)
            axes[0].set_title("Module 7 mirror stock")
            axes[0].set_xlabel("Year")
            axes[0].set_ylabel("Vehicles")
            axes[0].legend(fontsize=7)
            axes[0].grid(alpha=0.3)
        else:
            axes[0].set_visible(False)

        if {"year", "transport_type", "mirror_energy_pj"}.issubset(t13.columns):
            g = t13.groupby(["year", "transport_type"])["mirror_energy_pj"].sum().unstack(fill_value=0.0).sort_index()
            if not g.empty:
                g.plot(kind="area", stacked=True, ax=axes[1], alpha=0.85)
                axes[1].set_title("Module 7 mirror energy by transport type")
                axes[1].set_xlabel("Year")
                axes[1].set_ylabel("Energy (PJ)")
                axes[1].grid(alpha=0.3)
        else:
            axes[1].set_visible(False)

        if t13_fuel is not None and not t13_fuel.empty and {"year", "fuel", "mirror_fuel_energy_pj"}.issubset(t13_fuel.columns):
            g = t13_fuel.groupby(["year", "fuel"])["mirror_fuel_energy_pj"].sum().unstack(fill_value=0.0).sort_index()
            if not g.empty:
                g.plot(kind="area", stacked=True, ax=axes[2], alpha=0.85)
                axes[2].set_title("Module 7 mirror fuel mix")
                axes[2].set_xlabel("Year")
                axes[2].set_ylabel("Fuel energy (PJ)")
                axes[2].grid(alpha=0.3)
        else:
            axes[2].set_visible(False)

        if {"year", "mirror_energy_pj", "leap_energy_pj"}.issubset(t13.columns):
            comp = t13.dropna(subset=["leap_energy_pj"]).copy()
            if not comp.empty:
                comp["energy_diff"] = pd.to_numeric(comp["mirror_energy_pj"], errors="coerce") - pd.to_numeric(comp["leap_energy_pj"], errors="coerce")
                diff = comp.groupby("year")["energy_diff"].sum().sort_index()
                axes[3].axhline(0.0, color="#333333", linewidth=0.8)
                axes[3].bar(diff.index, diff.values, color="#D81B60")
                axes[3].set_title("Module 7 mirror vs LEAP energy")
                axes[3].set_xlabel("Year")
                axes[3].set_ylabel("Difference (PJ)")
                axes[3].grid(axis="y", alpha=0.3)
            else:
                axes[3].text(0.5, 0.5, "No LEAP comparison loaded", ha="center", va="center")
                axes[3].set_axis_off()
        else:
            axes[3].text(0.5, 0.5, "No LEAP comparison loaded", ha="center", va="center")
            axes[3].set_axis_off()

        fig.suptitle("Workflow summary dashboard — Module 7 mirror")
        fig.tight_layout()
        saved.append(_save(fig, out / "workflow_summary_module7_dashboard.png"))

    return saved
