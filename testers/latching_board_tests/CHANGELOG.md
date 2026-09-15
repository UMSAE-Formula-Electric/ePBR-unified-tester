# Changelog - latching_board_tests

Bump `VERSION` whenever limits or steps change. The version is recorded in
every result file, so a result can always be traced back to the test that
produced it.

## 0.1.0

- Skeleton tester: fixture setup/teardown, current-limited power-on check,
  firmware version check, coil resistance, latch set/clear, trigger response
  and trigger threshold sweep.
- Limits are placeholders. Replace them with real numbers from the board's
  design once it is characterised on the bench.
