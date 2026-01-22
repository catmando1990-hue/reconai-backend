## Goal

<!-- What is the user-visible outcome? -->

## Scope

<!-- Endpoints/services/modules touched -->

## Contract Changes

<!-- If you modified /api/core/state, /api/cfo/*, or /api/intelligence/*, check these boxes -->

### CORE State Contract

- [ ] Did `/api/core/state` contract change? If yes:
  - [ ] Updated `tests/fixtures/core_state_factory.py` to match new schema
  - [ ] Updated `SYNC_CONTRACT_VERSION` if breaking change
  - [ ] All tests still pass with `assert_valid_core_state()`
  - [ ] Coordinated with frontend team on schema changes
  - [ ] Updated `VALID_SYNC_STATUSES` if enum changed

### CFO Contract

- [ ] Did `/api/cfo/*` contract change? If yes:
  - [ ] Updated `tests/fixtures/cfo_state_factory.py` to match new schema
  - [ ] Updated `CFO_CONTRACT_VERSION` if breaking change
  - [ ] All tests still pass with `assert_valid_cfo_state()`
  - [ ] Coordinated with frontend team on schema changes
  - [ ] Updated `VALID_CFO_LIFECYCLE_STATUSES` if enum changed

### Intelligence Contract

- [ ] Did `/api/intelligence/*` contract change? If yes:
  - [ ] Updated `tests/fixtures/intelligence_state_factory.py` to match new schema
  - [ ] Updated `INTELLIGENCE_CONTRACT_VERSION` if breaking change
  - [ ] All tests still pass with `assert_valid_intelligence_state()`
  - [ ] Coordinated with frontend team on schema changes
  - [ ] Updated `VALID_LIFECYCLE_STATUSES` if enum changed

## Risk Level

- [ ] Low (copy/minor changes)
- [ ] Medium (new endpoints, refactors)
- [ ] High (auth, banking, Plaid, data access)

## Testing

<!-- How was this verified? -->

- [ ] CI passed
- [ ] Contract enforcement checks passed
- [ ] Tested locally with `pytest`
- [ ] No breaking changes to existing endpoints

## Notes

<!-- Anything the reviewer should know -->
