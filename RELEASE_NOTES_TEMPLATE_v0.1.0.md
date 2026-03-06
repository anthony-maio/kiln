# Kiln v0.1.0 Release Notes

## Highlights
- [ ] Local single-user release workflow
- [ ] Release readiness report (JSON + Markdown export)
- [ ] Real benchmark adapter (`lm-eval-harness`)

## What changed

### Added
- 

### Changed
- 

### Fixed
- 

## Upgrade notes
- Python dependencies: `pip install -r requirements.txt`
- Seed endpoint is disabled by default. Enable only when needed:
  - `KILN_ENABLE_SEED_ENDPOINT=true`

## Known limitations
- v0.1 supports local single-user mode only.
- Only benchmark stage has a real adapter in this release.
- Remaining stages are manual/mock unless integrated by contributors.

## Verification checklist
- [ ] `pytest -q` passes
- [ ] `python -m py_compile api_server.py adapters/lm_eval_adapter.py`
- [ ] `node --check app.js`
- [ ] Docker quickstart works on clean machine
