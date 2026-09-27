# Audit remediation status — 2026-09-27

This document maps the findings in PROJECT_AUDIT_2026-09.md to executable controls on branch audit-remediation-2026-09-27.

## High-priority findings

1. Sample-limited .1CD import — production import no longer inherits the preview limit. Migration manifests explicitly report sampled, complete, source/imported row counts and limited tables. CI runs the synthetic import contract smoke; representative data can be checked with the real .1CD gate.
2. Repeat packed import / row locator — migration is replacement-oriented, resets packed storage and offloaded assets, resets the primary row locator, and verifies point reads after a repeated import in CI.
3. UUID/DBNames and reference presentations — storage bindings are persisted by UUID. Runtime now falls back to imported catalog/enumeration rows when a Parse1CD reference has a UUID but no resolved_name, preserving the raw GUID alongside the user presentation.
4. End-to-end gate — runtime_process_smoke starts Runtime as a process, performs a manifest point read, starts the real Configurator offscreen, opens a metadata object through the Configurator Control API, builds a Runtime-backed Client object form, reads a requisite and tabular part, then closes Configurator through its real close path under a timeout.

## Medium-priority findings

1. Cold start and shutdown — the process smoke performs three sequential real Configurator start/open/close cycles, records startup/list-load/object-load/shutdown timings and fails when budgets are exceeded. Runtime RPC logs include request ID, action, session ID and duration.
2. IDE — the branch contains the existing UK/EN lexer, formatting, completion, navigation, signature-help and semantic-index work plus the additional diagnostics/snippet regressions from this remediation branch.
3. CI — Windows CI rejects whitespace errors, runs compileall, private-data checks, the full pytest suite, synthetic import smoke, Runtime/Configurator/Client process smoke, deterministic release-build smoke and dependency vulnerability audit. GitHub actions are pinned to commit SHAs.
4. Reproducible setup/release — Python 3.13, pip and the complete CI/build dependency set are pinned; console entry points and a byte-reproducible wheel/source release bundle with packaged runtime assets, checksums, a repeat-build gate and rollback documentation are provided.

## Real-data boundary

Public CI cannot prove compatibility with a private representative .1CD without receiving that database. The repository therefore contains an explicit local gate that fails closed on sampling, import errors, missing DBNames bindings, integrity failures and repeat-import row-count drift; --representative-document additionally verifies active/imported row equality for the target document and all physical tables bound to its metadata UUID. This is a data availability boundary, not a silent skipped check.
