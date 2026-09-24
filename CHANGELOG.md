# Changelog

## 0.1.0

Initial framework.

- **Runner** (`core/runner.py`) - data-driven step execution, results collected
  per run, a crashing step records failures rather than halting the run.
- **Result assertion** (`core/results.py`) - seven validation types declared in
  TOML: range, above, below, tolerance, string, regex, boolean.
- **Decorators** (`core/decorators.py`) - `test_step_result`, `with_psu`,
  `with_fg`, `with_fg_off`, `with_relay`, `retry`, `skip_if`, `requires_results`,
  `operator_prompt`, `timed`.
- **Instruments** - BK Precision PSU (generic SCPI), BK 4052 function generator,
  BK 5492B DMM, R221A08 8-channel relay bank. All 48 relay frames are generated
  from the checksum rule and verified against the reference table.
- **Transports** (`instruments/transport.py`) - VISA, serial and simulated,
  selected per instrument in `config/station.toml`.
- **Serial** (`utils/serial_device.py`) - command sending with prompt detection
  and timeouts, regex-parsed responses via `BaseSerialCommandParser`.
- **Port resolution** (`utils/ports.py`) - finds COM ports by USB VID/PID so
  Windows renumbering doesn't break the config.
- **Results** - JSON per run plus an appended CSV summary; no ERP integration.
- **Logging** - coloured console, full DEBUG file log per run.
- **CLI** (`main.py`) - `run`, `list`, `steps`, `check`, `ports`, `instruments`.
- **Simulate mode** - canned instrument responses from `station.toml`, so a
  tester can be built and dry-run with no hardware attached.
- **Operator prompts** (`utils/operator.py`) - questionary-backed confirm, text,
  number and select prompts that auto-answer when run unattended.
- **Starter tester** `testers/instrument_checkout`, which checks the bench
  instruments themselves: communication, FG programming, DMM zero/lead
  resistance/open circuit/known resistor, and FG-into-DMM loopback checks for
  DC level, square-wave average, duty cycle, sine RMS and frequency.

Known placeholders, to close out on the bench:

- The PSU model is unconfirmed; the driver uses the generic BK SCPI verbs.
- The BK 4052 command set is the Siglent-derived one used by the 4050 series,
  worth confirming against the programming manual.
- Every limit in `result_details.toml` and every serial command in `config.py`
  is invented and must be replaced with the real board's values.
