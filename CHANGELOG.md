# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-03-13

### Added
- Projects-first workspace with `kiln.yaml` as source of truth.
- Backend-managed benchmark jobs via lm-eval-harness adapter.
- Manual stage tracking for non-integrated pipeline stages.
- Release readiness report endpoint with Markdown and JSON export.
- Report artifacts written to repo under configurable output directory.
- `lm-eval-harness` adapter script for benchmarks.
- API contract tests and CI workflow.
- Docker and Docker Compose support.
- OSS governance docs (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY).

### Changed
- Enforced request enums for run mode, stage completion status, and incident severity.
- Fixed run state machine so pending stages are not terminal.
- Restricted default CORS to localhost origins.
- Gated `/api/seed` behind `KILN_ENABLE_SEED_ENDPOINT=true`.
- Sanitized API data rendered in the frontend to prevent stored XSS.

### Fixed
- Invalid incident model IDs now return `404` instead of server errors.
- Frontend API base now defaults to same-origin for local runs.

## [0.1.0] - 2026-03-13

### Added
- Initial public release of Kiln.
