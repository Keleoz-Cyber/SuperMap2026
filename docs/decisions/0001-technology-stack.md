# ADR 0001: Initial MVP Technology Stack

## Status
Accepted

## Context
The MVP must run locally on Windows, reliably validate CSV/JSON data, recompute verification metrics from real baseline files, manage model/task state, register SuperMap results without depending on UI automation, and remain easy to test and extend for later microseismic, coalbed methane, and DSI-like modules.

## Options Considered

### Option A: Python CLI + file-backed registry + generated reports
Use Python 3.12, pandas/numpy for tabular data, pydantic for contracts, Typer/Rich for CLI, YAML for configuration, pytest for tests, and JSON/Markdown/HTML artifacts for registry and reports.

- Pros: matches installed environment; strong CSV/statistics ecosystem; easy automated tests; low operational complexity; SuperMap integration can start as a stable configuration/file-exchange boundary.
- Cons: less interactive than a dedicated GUI; requires disciplined report generation for defense/review use.

### Option B: Python FastAPI + local web UI
Use a local API and browser UI for datasets, tasks, metrics, and result status.

- Pros: clearer interactive UI; API boundary is explicit.
- Cons: more moving parts and dependency surface before the data contract is stable; MVP acceptance emphasizes correctness and traceability more than web interaction.

### Option C: Node.js/Electron shell + Python analytics backend
Use a desktop UI shell with a Python backend for data and metrics.

- Pros: potentially polished demo interface.
- Cons: cross-language packaging and Windows desktop complexity would slow the first reliable closed loop; current MVP does not require custom desktop controls.

## Decision
Choose Option A for the first MVP implementation.

Initial stack:

- Python 3.12
- pandas and numpy for CSV/statistical processing
- pydantic for contract and metadata models
- Typer and Rich for the command-line analysis entry
- PyYAML for configuration
- pytest for automated tests
- JSON files for machine-readable registry/metadata and Markdown/HTML for human-readable reports

SuperMap is integrated through a configuration-backed result registry and adapter boundary: UDBX path, datasource alias, dataset name, parameters, status, object counts, openability checks, and error evidence. Direct iObjects/GPA/Python integration is a later replaceable adapter, not the MVP core.

## Consequences
- The first usable interface is a CLI plus generated reports, which is acceptable because the functional list allows a clear analysis entry.
- UI work can later add Streamlit/FastAPI/Electron without rewriting validation, metrics, or registry services.
- File-backed registry artifacts must include schema versions and be generated under ignored `artifacts/` or `outputs/` directories.
- Tests can run against real baseline CSV/JSON files and small fixed fixtures without SuperMap automation.

## Validation
This decision is valid if the project can:
1. register the standardized/train/validation datasets with hashes and statistics;
2. validate the data contract and block invalid inputs;
3. import five prediction exports and reproduce baseline metrics within tolerance;
4. manage model states and SuperMap result status without registering empty/failed outputs as successful;
5. run locally with documented commands and automated tests.
