# Changelog - equipment_tests

Bump `VERSION` whenever limits or steps change. It's recorded in every result
file, so a result can always be traced back to the test that produced it.

## 0.1.0

- `dmm.py` (DMM-CHECK): identity, zero and lead resistance with the leads
  shorted, open circuit, a bench supply measured against its setting, and a
  marked resistor.
- `fg.py` (FG-CHECK): identity, waveform programming and readback, a
  front-panel check where the operator reads the display back, and output
  enable/disable.
- Each runs on its own with only that instrument connected, since there's one
  USB cable.

Limits are loose on purpose. Tighten them once you've seen the real spread.
