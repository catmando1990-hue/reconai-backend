## Goal

<!-- What is the user-visible outcome? -->

## Scope

<!-- Endpoints/services/modules touched -->

## Contract Changes

<!-- If you modified /api/core/state, check these boxes -->

- [ ] Did `/api/core/state` contract change? If yes:
  - [ ] Updated `tests/fixtures/core_state_factory.py` to match new schema
  - [ ] Updated `SYNC_CONTRACT_VERSION` if breaking change
  - [ ] All tests still pass with `assert_valid_core_state()`
  - [ ] Coordinated with frontend team on schema changes
  - [ ] Updated `VALID_SYNC_STATUSES` if enum changed

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
