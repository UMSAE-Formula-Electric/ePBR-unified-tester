# Changelog - instrument_checkout

Bump `VERSION` whenever limits or steps change. It's recorded in every result
file, so a result can always be traced back to the test that produced it.

## 0.1.0

- Communication and identity checks for both instruments.
- FG programming and output control, no cabling needed.
- DMM checks: zero, lead resistance, open circuit, and a known resistor
  identified by the operator at run time.
- Loopback checks with FG CH1 driven into the DMM input: DC sweep, square-wave
  average, duty cycle by average, sine RMS, and frequency.
- Operator prompts via questionary, auto-answered when running unattended.

Limits are set loose enough to catch a fault rather than to qualify the
instruments against their datasheets. Tighten them once you've seen the real
spread over a few runs.
