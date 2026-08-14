# Portable test fixtures

These files are tiny fixed samples created for CI. They are not real research data and do not contain sensitive locations, original measurements, SuperMap databases, or upstream reference materials.

- `rho_tiny_validation.csv`: three synthetic `X,Y,Z,RHO` validation rows.
- `rho_tiny_predictions.csv`: three synthetic SuperMap-style prediction rows aligned to the tiny validation rows, including one `-9999` NoData value.
- `rho_tiny_predictions_xy_mismatch.csv`: synthetic prediction rows with an intentional XY mismatch for negative testing.
- `platform_2d.csv`: six synthetic 2D `Easting,Northing,Rho` rows for the v0.4 upload/mapping flow.
- `platform_3d.csv`: six synthetic 3D `Easting,Northing,Depth,Rho` rows for the v0.4 upload/mapping flow.
- `platform_invalid.csv`: five synthetic `x,y,val` rows with three non-numeric/empty cells for numeric-coercion testing.
- `professional_2d.py` / `professional_3d.py`: deterministic in-memory generators (circulant-embedding FFT, fixed seeds) for the v0.6 professional-structure acceptance tests — anisotropic 2D/3D fields with declared truth geometry, an isotropic control, a hand-built anomaly grid, and a CSV writer used only under pytest `tmp_path` (generated runtime CSVs are never committed).
- `kriging_reference.json`: frozen reference numbers for the ordinary-kriging acceptance test (trusted recomputation anchor; do not regenerate casually).
- `legacy_rho_regular_grid.csv`: a small synthetic regular-grid CSV used by the legacy render-source registration (`render-grid import-csv`) tests.

Related contract fixtures live next door: `tests/microseismic_fixtures.py` (synthetic 22-DAT microseismic builder for CI live gates) and `tests/fixtures_result_analysis/` (frozen result-analysis DTO snapshots: 2d_not_applicable / 3d_normal / ai_not_configured / no_uncertainty).
