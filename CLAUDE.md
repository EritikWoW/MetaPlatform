# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands must be run from the repo root `F:\MetaPlatform\` using the `.venv` interpreter.

**Run all tests:**
```
.venv\Scripts\python.exe -m pytest
```

**Run a single test file:**
```
.venv\Scripts\python.exe -m pytest src/tests/test_mpdb_btree_index.py -v
```

**Run a single test by name:**
```
.venv\Scripts\python.exe -m pytest src/tests/test_mpdb_btree_index.py::test_btree_index_point_lookup -v
```

**Launch the desktop app (Launcher → Configurator/Client):**
```
.venv\Scripts\python.exe src/scripts/run_launcher_qt.py
```

**Launch the Runtime server:**
```
.venv\Scripts\python.exe src/scripts/run_runtime_server_cmd.py --host 127.0.0.1 --port 8765
```

**Launch Runtime Admin UI:**
```
.venv\Scripts\python.exe src/scripts/run_runtime_admin_qt.py
```

**Run mpdb integrity checker:**
```
.venv\Scripts\python.exe src/scripts/mpdb_doctor.py <path-to.mpdb> [--json]
```

**Skip PySide6/Qt tests (headless/CI):**
```
MP_TEST_FORCE_NO_PYSIDE6=1 .venv\Scripts\python.exe -m pytest
```
Qt tests auto-use `QT_QPA_PLATFORM=offscreen` when PySide6 is present.

## Architecture

MetaPlatform is a desktop-first business-application development platform with its own file storage engine. The layered architecture enforces a strict access rule: **UI must never open `mpdb` directly — all access goes through the Runtime server via RPC.**

### Subsystems

| Package | Role |
|---|---|
| `src/mpdb` | File storage engine: page storage, WAL, recovery, allocator, CRC, compression |
| `src/runtime` | HTTP/JSON-RPC server — owns live mpdb access, manages DbPool/sessions, manifest ops, asset ops, 1C import, reports/print/posting |
| `src/runtime/gateway.py` | `RuntimeGateway` RPC client; `GatewayDb`/`GatewayTable` let Configurator use it as a drop-in DB API |
| `src/configurator` | Configuration editor split into `application` (services/orchestration), `domain` (models/defaults), `persistence` (manifest/tables/schema) |
| `src/ui_qt` | Shared Qt layer: Launcher, Runtime Admin UI, themes, i18n, viewmodels, reusable widgets |
| `src/client` | End-user app — reads configuration and data via runtime context |
| `src/dsl` | Internal DSL: lexer, parser, validator, VM, public API in `dsl/api.py` |
| `src/infra/onec` | 1C/BAS canonical metadata model (`MPXObject`, `MPXConfig`) |
| `src/mp_platform` | High-level platform API (catalog/document/register) built on top of `mpdb`; used in tests |

### Standard data flow

```
UI (Configurator / Client / Launcher)
  ↓
RuntimeGateway  (src/runtime/gateway.py)
  ↓
Runtime Server  (src/runtime/server.py — POST /rpc, GET /health)
  ↓
mpdb            (src/mpdb/mpdb.py)
```

### 1C/BAS import pipeline

Safe staged workflow — never touches the live DB until fully validated:

1. Backup current DB
2. Create staging copy
3. Import structure → DSL transformation → validate manifest
4. Swap staging → main DB

### Structure cache

`<database>.structure_cache.json` accelerates cold-start tree building. It is **not** the source of truth — the manifest inside `mpdb` is.

### Sources of truth

- **Manifest in `mpdb`** — configuration structure
- **`mpdb`** — all persisted data and assets
- **`src/docs/O_PRODELANNOI_RABOTE.md`** — invariants and historical decisions that must not be broken without an explicit revision of that document

## Localization

Only `uk` (Ukrainian) and `en` (English) are supported. Russian must not appear in UI, labels, or payloads. The DSL `parse_dsl()` accepts `language: "uk" | "en"`. When 1C source data contains only `ru` keys, transliterate or use the technical identifier — never display Russian text.

## Key invariants

- `ConfiguratorService` → `RuntimeGateway` → Runtime RPC → `mpdb` is the canonical configurator path. Persistence modules that directly open `mpdb` are legacy and should not be extended.
- Before modifying any non-trivial area, check `src/docs/O_PRODELANNOI_RABOTE.md` for recorded invariants.
- The root `pyproject.toml` is currently empty (not a packaging source of truth).
