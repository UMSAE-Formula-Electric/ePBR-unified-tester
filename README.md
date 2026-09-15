# ePBR27 Unified Tester

Production test framework for the ePBR27 Formula Electric car. Boards get tested
by name, against limits declared in TOML, with results written to local files.

Adapted from a production tester framework at work: same core ideas (data-driven
test runner, TOML-declared limits, decorator-wrapped steps, regex serial
parsing), rebuilt around BK Precision bench instruments with no ERP integration.

```bash
python main.py run EPBR27-LB-BRINGUP -S 0042 --simulate
```

That runs a complete test with no hardware attached. Start there.

---

## Contents

1. [Setup on Windows](#setup-on-windows)
2. [First run](#first-run)
3. [How it fits together](#how-it-fits-together)
4. [Writing a test step](#writing-a-test-step)
5. [Declaring limits](#declaring-limits)
6. [Instruments](#instruments)
7. [Simulate mode](#simulate-mode)
8. [Adding a new tester](#adding-a-new-tester)
9. [CLI reference](#cli-reference)
10. [Results and logs](#results-and-logs)
11. [Troubleshooting](#troubleshooting)
12. [WSL](#wsl)

---

## Setup on Windows

Run this natively on Windows, not in WSL. COM ports and USB-TMC instruments are
visible to Python directly; under WSL every instrument has to be forwarded by
hand each time you plug it in. See [WSL](#wsl) if you want the detail.

You need **Python 3.11 or newer** (3.13 is what this was built against). Check:

```bash
python --version
```

If that fails or shows an older version, install from
[python.org/downloads](https://www.python.org/downloads/) and tick
**"Add python.exe to PATH"** in the installer.

Then, from the repo root:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -e .
```

You'll know the venv is active because your prompt gains a `(.venv)` prefix.
Activate it in every new terminal before running anything.

> In PowerShell, if activation is blocked by the execution policy, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

Then copy the environment template:

```bash
copy .env.example .env
```

### Driver notes

- **USB-serial adapters** (the relay bank, the DMM, most BK supplies) generally
  work on the built-in Windows driver. If a device shows up in Device Manager
  with a warning triangle, install the vendor's driver - usually FTDI, CP210x or
  CH340 depending on the chip.
- **USB-TMC instruments** (the BK 4052 function generator) are reached through
  `pyvisa-py`, which is installed as a dependency and needs no NI-VISA. It uses
  `pyusb` underneath, which on Windows needs a WinUSB driver bound to the
  instrument. If `python main.py instruments` can't see the FG, use
  [Zadig](https://zadig.akeo.ie/) to bind **WinUSB** to it. Installing
  [NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html)
  instead also works and is the more conventional route on a shared bench PC.

---

## First run

Nothing plugged in? Run the whole thing simulated:

```bash
python main.py run EPBR27-LB-BRINGUP -S 0042 --simulate
```

You should see four steps run, six results pass, and a JSON file appear under
`results/`. That confirms Python, the dependencies and the framework are all fine.

Then see what's defined:

```bash
python main.py list
```

```bash
python main.py steps latching_board_tests
```

When hardware arrives, find your instruments:

```bash
python main.py ports
```

Put the COM ports (or better, the VID/PID) into `config/station.toml`, then:

```bash
python main.py instruments
```

That pings each instrument for its `*IDN?` string. Once they all answer, you're
ready to test a real board.

---

## How it fits together

```
main.py                 CLI entry point
config/
  paths.py              where logs, results and testers live
  settings.py           env flags, station config loader, simulate switch
  station.toml          how THIS PC reaches each instrument
core/
  runner.py             resolves step names to functions and runs them
  results.py            limit specs and pass/fail validation
  decorators.py         @test_step_result, @with_psu, @with_fg, @with_relay, ...
  discovery.py          finds testers and loads their TOML
  sinks.py              writes result JSON + CSV
  logger.py             coloured console + per-run file log
instruments/
  transport.py          VISA / serial / simulated SCPI transports
  psu.py                BK power supply
  function_generator.py BK 4052
  dmm.py                BK 5492B
  relay.py              R221A08 8-channel relay bank
utils/
  serial_device.py      DUT console: commands, regex parsers, prompt handling
  ports.py              finds COM ports by USB VID/PID
  common.py             tolerance, sweeps, waiting, sampling
  strings.py            safe casting and extraction from console text
  timer.py              duration measurement
testers/
  latching_board_tests/ your starter tester
```

**The central idea:** a test step measures and reports; it never decides
pass/fail. Limits live in `result_details.toml`, which means you can review every
limit in one file, and nobody can quietly widen a limit inside test logic.

A run works like this:

1. You pass a part number. `parts.toml` says which steps run and which results
   they must produce.
2. The runner finds each step function by name, in `tester.py` then anywhere
   under `tests/`, and calls it with the `TestRunner`.
3. The step measures something and calls `runner.add_result("ID", value)`.
4. The runner validates against that ID's limit spec and logs PASS or FAIL.
5. Any declared result that never arrived is recorded as a failure - a step that
   crashes leaves failures, not gaps.
6. Results go to `results/<timestamp>_<serial>_<PASS|FAIL>.json` plus a row per
   measurement in `results/summary.csv`. Exit code is 0 only if everything passed.

---

## Writing a test step

```python
from core.decorators import test_step_result, with_psu
from core.runner import TestRunner
from testers.latching_board_tests.config import PSU_Settings, Relays
from testers.latching_board_tests.utils import measure_voltage_at


@test_step_result("LB_RAIL_3V3")          # every result this step must produce
@with_psu(PSU_Settings.NOMINAL_12V)       # powered for the step, off afterwards
def RAIL_CHECK(runner: TestRunner):
    """One line on what this proves about the board."""
    voltage = measure_voltage_at(Relays.SUPPLY_SENSE)
    runner.add_result("LB_RAIL_3V3", voltage)
```

Then add `"RAIL_CHECK"` to `steps` and `"LB_RAIL_3V3"` to `result_details` in
`parts.toml`, and define the limit in `result_details.toml`. Check the wiring:

```bash
python main.py check EPBR27-LB-001
```

### Available decorators

| Decorator                      | What it does                                                        |
|--------------------------------|---------------------------------------------------------------------|
| `@test_step_result(*ids)`      | Records failures for every named result if the step raises           |
| `@with_psu(setting)`           | Powers the DUT, cuts power in a `finally`                            |
| `@with_fg(setting)`            | Drives a waveform, stops it afterwards                               |
| `@with_fg_off`                 | Just guarantees the FG ends up off                                   |
| `@with_relay(*channels)`       | Closes relay channels for the step, releases them afterwards         |
| `@retry(attempts, delay_s)`    | Retries a flaky hardware call                                        |
| `@skip_if(condition, reason)`  | Skips a step when a run-time condition holds                         |
| `@requires_results(*ids)`      | Skips a step whose prerequisites never passed                        |
| `@operator_prompt(message)`    | Waits for the operator (auto-skipped when simulating)                |
| `@timed`                       | Logs how long a helper takes                                         |

Order matters: `@test_step_result` goes **outermost** so it catches failures in
the setup decorators too.

### Reporting results

```python
runner.add_result("ID", 12.01)       # float, rounded to 3 dp
runner.add_result("ID", True)        # bool -> "true"/"false"
runner.add_result("ID", "1.2.3")     # string, for regex or exact match
runner.get_result("ID")              # read back a result from earlier in the run
runner.has_result("ID")              # was it reported?
runner.context["key"] = value        # scratch space shared between steps
```

Only the first result for an ID counts. That's deliberate: a retry loop can't
overwrite a recorded failure with a later pass.

---

## Declaring limits

In `result_details.toml`:

```toml
["LB_COIL_RESISTANCE"]
validation_type = "range"
units = "ohm"
min = 8.0
max = 12.0
desc = "Latch coil resistance - catches an open or shorted winding"
```

| `validation_type` | Passes when                                    | Fields                        |
|-------------------|------------------------------------------------|-------------------------------|
| `range`           | `min <= measured <= max`                        | `min`, `max`                  |
| `above`           | `measured >= expected_value`                    | `expected_value`              |
| `below`           | `measured <= expected_value`                    | `expected_value`              |
| `tolerance`       | `|measured - expected_value| <= tolerance`      | `expected_value`, `tolerance` |
| `string`          | exact match                                     | `expected_value`              |
| `regex`           | `expected_value` found in the measured string   | `expected_value`              |
| `boolean`         | matches `expected_value` (default `true`)       | `expected_value`              |

A measurement that can't be converted to a number where one is required fails
with the reason recorded in the result file, rather than raising.

---

## Instruments

| Instrument            | Model                | Transport                     | Driver                             |
|-----------------------|----------------------|-------------------------------|------------------------------------|
| Power supply          | BK Precision (TBD)   | serial SCPI (or VISA)         | `instruments/psu.py`               |
| Function generator    | BK Precision 4052    | USB-TMC via VISA              | `instruments/function_generator.py`|
| Bench DMM             | BK Precision 5492B   | USB virtual COM, SCPI         | `instruments/dmm.py`               |
| Relay bank            | R221A08, 8 channel   | serial, fixed hex frames      | `instruments/relay.py`             |
| DUT console           | your board           | serial, regex-parsed          | `utils/serial_device.py`           |

**Every SCPI driver has a `Scpi` class at the top holding each command string.**
When you have the programming manual in front of you, check the verbs against
that one class - if a command differs on your model, fix it there and nothing
else in the codebase needs to change.

Two open questions you'll need to close out on the bench:

- **The PSU model.** The driver uses the generic SCPI set (`INST:NSEL`, `VOLT`,
  `CURR`, `OUTP`, `MEAS:VOLT?`, `MEAS:CURR?`) that most BK supplies accept.
  Confirm it, and set `transport` to `serial` or `visa` to match how it enumerates.
- **The 4052's command set.** The 4050 series uses the Siglent-derived
  `C1:BSWV WVTP,SQUARE,FRQ,...` syntax, which is what the driver sends. Worth
  confirming against the manual before you trust a threshold sweep.

The relay frames need no such check: all 48 are generated from the documented
checksum rule and verified byte-for-byte against the work tester's table.

### DMM + relay bank

With one DMM and eight relay channels, you move the meter around the board
rather than having a channel per node:

```python
with RelayBank() as relay:
    relay.open_only(Relays.COIL_SENSE)   # interlock: exactly one path live
    with DMM() as dmm:
        resistance = dmm.measure_resistance()
```

`open_only()` with a single channel uses the board's interlock mode, so the bank
is never momentarily in a state where two nodes are connected to the meter at once.

---

## Simulate mode

```bash
python main.py run EPBR27-LB-001 -S 0042 --simulate
```

Every instrument returns canned values from the `[*.simulation]` tables in
`config/station.toml`, and no port is opened. Use it to build a whole tester
before the board exists, and to check your TOML wiring on a laptop.

The tables also serve as a written record of what the console protocol is meant
to look like, which stays useful once the hardware is real.

**What it can't do:** the simulator is a lookup table, not a model of your board.
It can't make a pin go low in response to a command, so steps that check for
*change* (latch clears, output toggles, a threshold sweep) will fail under
`--simulate`. That's expected. `EPBR27-LB-BRINGUP` is the part number that passes
cleanly simulated - use it as the "is the framework healthy" check.

---

## Adding a new tester

```
testers/<your_tester>/
    __init__.py
    VERSION                 bump when limits or steps change
    parts.toml              part number -> steps + expected results
    result_details.toml     the limits
    config.py               rails, waveforms, relay map, serial commands, timing
    utils.py                helpers shared by steps
    tester.py               top-level steps
    tests/                  more steps, any folder depth
        __init__.py
```

Copy `latching_board_tests`, rename it, and delete the steps you don't need.
`python main.py list` will pick it up with no registration step.

---

## CLI reference

```bash
python main.py run <part_number> [-S serial] [-s step] [--simulate] [--no-save]
python main.py list                          # testers and part numbers
python main.py steps <tester_name>           # every runnable step
python main.py check <part_number>           # validate TOML wiring, run nothing
python main.py ports                         # serial ports with VID/PID
python main.py instruments [--simulate]      # ping each instrument
python main.py -l DEBUG run ...              # verbose
```

`run` exits 0 only when every result passed, so you can branch on it in a script.

Run a single step while developing it:

```bash
python main.py run EPBR27-LB-001 -s COIL_RESISTANCE_TEST --no-save
```

---

## Results and logs

- `results/<timestamp>_<serial>_<PASS|FAIL>.json` - the full record of one run:
  every measurement, its limit, its duration, the tester version, the operator.
- `results/summary.csv` - one row per measurement, appended across all runs.
  Open it in Excel to trend a parameter across boards.
- `logs/<timestamp>_<tester>_<serial>.log` - the complete DEBUG log for that run,
  including every SCPI command and serial exchange, regardless of console level.

Both directories are gitignored.

To send results somewhere else later - a database, a dashboard - write a class
with a `write(run)` method and pass it to the runner's `sinks`. Nothing else changes.

---

## Troubleshooting

**`Could not find a serial port for 'psu'`**
Nothing matched that instrument's `port`/`vid`/`pid` in `station.toml`. Run
`python main.py ports` to see what's actually attached.

**`No VISA resources found`**
The USB-TMC instrument isn't visible to pyusb. Check the cable, check the
instrument is in USB (not GPIB/RS-232) mode, and bind WinUSB with Zadig or
install NI-VISA.

**`Access is denied` on a COM port**
Something else holds it - PuTTY, a serial monitor, or a previous run that
crashed. Close it. Always use `with SerialManager(...) as ser:` so the port is
released even when a step fails.

**A serial command times out but the DUT is clearly alive**
The prompt regex doesn't match what your firmware prints. Set `prompt_regex` in
`[dut_serial]`, and check the pattern in `SerialDevices.DUT`.

**A regex parser raises `No match for ...`**
Run with `-l DEBUG` to see the raw console text, then fix the pattern in your
tester's `config.py`. `try_parse()` returns `None` instead of raising when a
missing response is a legitimate outcome.

**COM ports move between runs**
Windows renumbers them per USB jack. Address instruments by `vid`/`pid` in
`station.toml` instead of a hard-coded port.

---

## WSL

Native Windows is the recommended setup and the one this was built for. WSL is
workable but adds a step to every session:

WSL2 has no direct USB access. Each device must be forwarded from Windows with
[usbipd-win](https://github.com/dorssel/usbipd-win): `usbipd list`, then
`usbipd bind --busid <id>` (once, as admin) and `usbipd attach --wsl --busid <id>`
(after every replug, and after every reboot). Ports then appear as `/dev/ttyUSB*`
rather than `COM*`, so `station.toml` needs different values.

The upside is stable device names: udev rules can pin a device to a fixed path
like `/dev/dut-serial` regardless of plug order. If you want that, the `vid`/`pid`
addressing already in `station.toml` gets you the same result on Windows without
the forwarding.

If you do want WSL set up, ask and it's straightforward to add - the code is
OS-agnostic, it's only the port names and the forwarding that differ.
