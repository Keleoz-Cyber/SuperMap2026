# Portable test fixtures

These files are tiny fixed samples created for CI. They are not real research data and do not contain sensitive locations, original measurements, SuperMap databases, or upstream reference materials.

- `rho_tiny_validation.csv`: three synthetic `X,Y,Z,RHO` validation rows.
- `rho_tiny_predictions.csv`: three synthetic SuperMap-style prediction rows aligned to the tiny validation rows, including one `-9999` NoData value.
- `rho_tiny_predictions_xy_mismatch.csv`: synthetic prediction rows with an intentional XY mismatch for negative testing.
