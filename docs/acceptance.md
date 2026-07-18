# v0.1 Acceptance Notes

## Verified locally

- Python package editable install and CLI help.
- Portable pytest layer using only `tests/fixtures/`.
- Local real-data regression layer using adjacent read-only standardized data.
- Standardized/training/validation row counts: 17,549 / 15,827 / 1,722.
- Training spatial columns 264, validation spatial columns 29, overlap 0.
- Five prediction exports: 1,722 rows each, 1,481 valid, 241 NoData, XY mismatch 0.
- Recomputed metrics match `插值精度对比_总体指标.csv` within configured tolerance.
- SuperMap configured results: 3; formal configured result: 1.
- SuperMap UDBX file-level verification when `../Project/expore1.udbx` exists.

## Evidence boundaries

- `dataset_verified` is currently false because no supported SuperMap dataset API adapter is configured.
- Full voxel and horizontal slice support are manual iDesktopX evidence, not Python-rendered verification.
- Vertical slice is `unverified`.
- Native isosurface is `failed`; `RHO_ISO_77_K40` and `RHO_ISO_HIGH_P95_K40` are excluded from formal results.
- `RHO >= 77` is a demonstration threshold only.
- RHO physical unit and EPSG remain unconfirmed.

## Not implemented in v0.1

- Microseismic 3D coordinate reconstruction.
- Coalbed methane 3D fusion.
- DSI-like interpolation kernel.
- iDesktopX mouse automation.
- Web frontend, accounts, cloud deployment, and iServer publishing.
