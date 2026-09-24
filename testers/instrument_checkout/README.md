# instrument_checkout

Checks the two instruments you have on the bench right now: the **BK Precision
4052** function generator and the **BK Precision 5492B** DMM.

It exists for two reasons. It's a real test you'll use — a five-minute
confidence check that the bench is behaving before you trust it with a board.
And it's a worked example of every framework pattern, written against hardware
you actually have, so you can run it and change it today.

## The five checkout levels

Each needs a different amount of setup. Start at the top; if `BENCH-COMMS`
fails, nothing below it will work either.

| Part number | Needs | What it proves |
|---|---|---|
| `BENCH-COMMS` | USB only | Both instruments answer `*IDN?` |
| `BENCH-FG` | USB only | The FG accepts a waveform and reads it back |
| `BENCH-DMM` | Test leads, one known resistor | Zero, lead resistance, open circuit, accuracy |
| `BENCH-LOOPBACK` | A cable from FG CH1 to the DMM input | The two instruments agree with each other |
| `BENCH-FULL` | All of the above | Everything in one run |

```bash
python main.py run BENCH-COMMS -S BENCH01
```

```bash
python main.py run BENCH-FULL -S BENCH01
```

## What you need for the loopback

One cable from the **FG CH1 output** to the **DMM's V/Ω and COM inputs**. The
FG output is BNC and the DMM inputs are banana jacks, so you'll want a
BNC-to-dual-banana adapter or a BNC-to-banana lead pair. Signal to V/Ω, shield
to COM.

Nothing here exceeds 5 V into a high-impedance input, so there's no hazard and
no current path to worry about.

## The loopback tests

With one cable, these five checks cover a surprising amount:

- **DC sweep** — the FG is set to 0, 1, 2.5 and 5 V in turn and the DMM reads
  each. Sweeping rather than testing one point catches a gain error that a
  single mid-scale reading would hide. The result is the worst error.
- **Square average** — a 0–5 V square at 50% duty should read 2.5 V on the
  DMM's *DC* range, because the meter integrates over many cycles.
- **Duty cycle** — a 0–4 V square at 25% duty averages 1.0 V. Since the levels
  were already confirmed by the sweep, the average is a direct read-out of the
  duty cycle. That's how you measure duty on a bench with no scope.
- **Sine RMS** — a 2 Vpp sine should read 0.707 V on the AC range. The
  peak-to-RMS ratio is fixed for a sine, so agreement means both ends behave.
- **Frequency** — the DMM's counter against the FG's timebase at 1 kHz. Both
  are crystal-referenced, so this should agree very closely.

## The one setting that will bite you

**The FG's output load must be set to high-Z.** A DMM is effectively an open
circuit. If the FG thinks it's driving 50 Ω, every voltage comes out at
**twice** what you programmed, and it looks like a broken instrument.

`default_load = "HZ"` in `config/station.toml` handles this, and
`LOOPBACK_DC_LEVELS` watches for readings that are ~2× the setting and says so
explicitly in the log if it sees them.

## Operator prompts

Steps that need something done to the fixture ask for it, using `questionary`:

```
? Connect FG CH1 output to the DMM's V/ohm and COM inputs. Connected? (Y/n)
? Resistor's marked value in ohms  10000
```

Every prompt is safe unattended. In simulate mode, or when output is piped to a
file or a script, the prompt is skipped and the default is used, with an
`[auto-answered]` line in the log. So a tester full of prompts still dry-runs
end to end without hanging.

Ctrl+C at a prompt stops the run rather than being recorded as a failure — an
operator walking away isn't a bad board.

The resistor check is worth a look as a pattern: the operator types in the
resistor's value at run time, so the *recorded result is the percentage error*
rather than the reading. One fixed limit then covers whatever resistor is in
the drawer.

## After the first run

Two things to tighten once you've seen real output:

1. **The identity limits.** `BENCH_DMM_IDN` and `BENCH_FG_IDN` currently accept
   any string of five characters or more, so your first run passes whatever the
   firmware reports. Find `DMM identifies as: ...` in the log and replace the
   regex in `result_details.toml` with something specific like `5492B`. That
   turns a connectivity check into a real identity check — the thing that stops
   someone testing a board with the wrong instrument plugged in.

2. **The loopback limits.** They're set to catch "something is wrong", not to
   qualify the instruments against their datasheets. Run it a few times, look
   at the spread in `results/summary.csv`, then tighten. A limit that never
   comes close to failing isn't testing anything.

## Simulate mode

```bash
python main.py run BENCH-COMMS --simulate     # passes 6/6
python main.py run BENCH-FG --simulate        # passes 7/7
```

Those two are the "is the framework healthy?" check and pass cleanly with no
hardware.

`BENCH-DMM` and `BENCH-LOOPBACK` will show failures under `--simulate`, and
that's expected rather than broken. The simulator is a lookup table with one
canned value per DMM function, and these tests deliberately measure *different*
values on the same function — 0 V with the leads shorted, 2.5 V for the square
average, 1.0 V for the duty average. No single canned value can satisfy all
three. The steps still run start to finish, which is what a dry run proves.

## Files

| File | What's in it |
|---|---|
| `parts.toml` | The five checkout levels |
| `result_details.toml` | Every limit |
| `config.py` | FG waveforms, expected values, prompt wording, timing |
| `utils.py` | Measurement helpers and the doubled-reading detector |
| `tester.py` | Setup, identity, teardown |
| `tests/dmm.py` | DMM checks with leads and a resistor |
| `tests/function_generator.py` | FG programming, no cable |
| `tests/loopback.py` | The FG↔DMM cross-checks |
