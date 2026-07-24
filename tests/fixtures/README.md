# Portable test fixtures

These files are tiny fixed samples created for CI. They are not real research data and do not contain sensitive locations, original measurements, SuperMap databases, or upstream reference materials.

- `rho_tiny_validation.csv`: three synthetic `X,Y,Z,RHO` validation rows.
- `rho_tiny_predictions.csv`: three synthetic SuperMap-style prediction rows aligned to the tiny validation rows, including one `-9999` NoData value.
- `rho_tiny_predictions_xy_mismatch.csv`: synthetic prediction rows with an intentional XY mismatch for negative testing.
- `platform_2d.csv`: six synthetic 2D `Easting,Northing,Rho` rows for the v0.4 upload/mapping flow.
- `platform_3d.csv`: six synthetic 3D `Easting,Northing,Depth,Rho` rows for the v0.4 upload/mapping flow.
- `platform_invalid.csv`: five synthetic `x,y,val` rows with three non-numeric/empty cells for numeric-coercion testing.
