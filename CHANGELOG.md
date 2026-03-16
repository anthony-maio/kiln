# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-03-16

### Added
- Benchmark-backed safety evaluation via the external `safety-eval` harness.
- `safety_eval` provider support with benchmark thresholds and normalized harness artifacts.
- A dedicated `safety_eval` adapter for dry-run testing and local harness execution.

### Changed
- Safety automation now prefers benchmark-backed evaluation over judge-only prompt cases.
- Project config and reports now describe safety automation in benchmark terms when `safety_eval` is configured.

### Fixed
- Safety policy evaluation now reasons over benchmark success rates instead of only case-level refusal counts.

## [0.3.0] - 2026-03-16

### Added
- Candidate-aware `v2` project configs with one-candidate-per-run execution.
- Executor-driven pre-release pipeline for benchmarks, documentation, packaging, serving, and configurable safety automation.
- Repo-local stage artifacts and logs for executor-backed project runs.
- Automated tests for documentation, packaging, serving, stage execution, project runs, and safety automation.
- WildGuard-backed safety evaluation for configured harmful prompt cases.
- Stronger documentation and packaging gate checks for release-shaped repos.

### Changed
- Shifted Kiln from a dashboard-first demo to a projects-first local release workspace.
- Release reports now mark a stage as integrated based on jobs actually queued for that run, avoiding false manual/automated labeling.
- The project editor now supports explicit safety configuration and treats manual safety decisions as overrides when automation is configured.
- Documentation now requires release-facing README sections and warns on incomplete model cards.
- Packaging now validates format-specific artifact layout for `hf` and `gguf` candidates.

### Fixed
- Project runs no longer rely on manual safety as the default when safety automation is configured.
- Release reports and UI copy now match the actual shipped automation surface.

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
