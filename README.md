# ePBR Unified Tester

Test framework for ePBR boards. Tests are defined per part number in TOML —
which steps run, and the pass/fail limits for every measurement. Steps just
measure and report; the limits decide pass/fail. Results go to `results/` as
JSON and CSV, full logs to `logs/`.

Right now it has `equipment_tests`, which checks the bench instruments
themselves (BK 5492B DMM, BK 4052 function generator).

## Drivers

Install these before anything else.

- **DMM (5492B)** — Silicon Labs CP210x, shows up as a COM port.
  [CP210x Universal Windows Driver](https://www.silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip).
  Unzip, right-click `silabser.inf` → Install, replug the DMM.
- **FG (4052)** — USBTMC, needs
  [NI-VISA](https://www.ni.com/en-us/support/downloads/drivers/download.ni-visa.html).
  Any version 3.0+. Drivers bind automatically once it's installed.

## Setup

PowerShell, from the repo root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
```

Activate again in every new terminal. Git Bash uses
`source .venv/Scripts/activate` instead, but run tests from PowerShell — the
operator prompts don't show up in Git Bash.

## Commands

```powershell
python main.py list                     # testers and part numbers
python main.py steps equipment_tests    # every step
python main.py ports                    # COM ports, with VID/PID
python main.py instruments              # ping whatever's connected
python main.py check DMM-CHECK          # validate the TOML, run nothing
python main.py run <part-number>        # run a test
```

Flags for `run`: `-S <serial>`, `-s <step>` to run one step (repeatable),
`--simulate` for no hardware, `--no-save` to skip result files.

`-l DEBUG` goes before the subcommand: `python main.py -l DEBUG run DMM-CHECK`.

## Running a test

Only one instrument connected at a time. DMM:

```powershell
python main.py run DMM-CHECK -S DMM01
```

Needs test leads, a bench supply and a known resistor — it asks for each as it
goes. Swap the cable to the FG and run `FG-CHECK` the same way.

No hardware:

```powershell
python main.py run DMM-CHECK --simulate
```

One step while setting up:

```powershell
python main.py run DMM-CHECK -s DMM_IDENTITY --no-save
```

## Config

COM ports and instrument addresses in `config/station.toml`. Put machine-specific
values in `config/station.local.toml` — gitignored, overrides the shared file.
Set `enabled = false` on whichever instrument isn't plugged in.
