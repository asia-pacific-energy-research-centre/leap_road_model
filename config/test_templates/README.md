# Synthetic LEAP reference templates

## Truck PHEV

`road_model_leap_export_truck_phev_synthetic_test.xlsx` is a test-only LEAP
reference for exercising the road-model pipeline before truck-PHEV technologies
are installed in a target LEAP area.

It contains 98 unique metadata rows for `PHEV heavy` and `PHEV medium` under
`Demand\Freight road\Trucks`, with Electricity, Gas and diesel oil, and
Biodiesel fuel leaves. All truck-PHEV rows use `BranchID = -1`; other metadata
follows the analogous Transport Stock Turnover patterns in the canonical
reference.

The workbook can be passed explicitly with:

```powershell
python codebase\road_workflow.py 20_USA `
  --scenarios Target Reference `
  --leap-reference-path config\test_templates\road_model_leap_export_truck_phev_synthetic_test.xlsx
```

Do not import the resulting workbook into a production LEAP area. `-1` is a
placeholder, not a real LEAP BranchID. After creating the branches in the
target area using the Transport Stock Turnover method, export that area and use
its assigned IDs as the reviewed reference.
