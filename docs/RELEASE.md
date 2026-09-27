# Release and rollback

MetaPlatform uses a reproducible Windows-oriented source/wheel bundle until a standalone installer is introduced.

## Build

Use Python 3.13 from a clean checkout:

~~~powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install pip==26.2.1
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.venv\Scripts\python.exe -m src.scripts.import_contract_smoke
.venv\Scripts\python.exe -m src.scripts.runtime_process_smoke
.venv\Scripts\python.exe -m src.scripts.build_release --output dist
~~~

The bundle contains Launcher, Runtime, Configurator, Client, assets, migration code, documentation, the dependency lock and VERSION.json. The build also produces SHA256SUMS.json. Build tooling is pinned and build isolation is disabled so the wheel uses the reviewed environment; SOURCE_DATE_EPOCH and normalized ZIP metadata make repeated builds byte-stable.

## Entry points

- metaplatform-launcher
- metaplatform-configurator
- metaplatform-client
- metaplatform-runtime
- metaplatform-runtime-admin

## Representative .1CD gate

Direct .1CD parsing uses the external Parse1CD backend. Configure META_PARSE1CD_PARSER to an authorised parser checkout before running this gate; parser-specific unit tests are skipped when that optional backend is absent from a clean public checkout.

Real business databases must not be committed to the repository or uploaded to public CI. Before a release intended for a specific 1C/BAS database, run:

~~~powershell
python -m src.scripts.real_onecd_gate --source "C:\Data\Base.1CD" --repeat --report .artifacts\real-onecd-gate.json
~~~

The gate rejects sample-limited imports, table errors, missing UUID/DBNames bindings, failed integrity checks and repeat-import row-count drift.

## Rollback

1. Stop Configurator and Client.
2. Stop the Runtime process that owns the live mpdb.
3. Restore the pre-import backup produced by the staged import workflow.
4. Install the previous wheel or unpack the previous source bundle.
5. Start Runtime and run the process smoke before reopening production data.

Do not replace a live mpdb while Runtime still owns the file.
