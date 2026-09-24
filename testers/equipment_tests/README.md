# equipment_tests

Checks the two instruments on the bench. **One at a time** — with a single USB
cable, only one can be connected, so these are two independent runs that never
need each other.

| File | Run it with | Instrument |
|---|---|---|
| `dmm.py` | `python main.py run DMM-CHECK -S DMM01` | BK Precision 5492B |
| `fg.py` | `python main.py run FG-CHECK -S FG01` | BK Precision 4052 |

Plug in the DMM, run `DMM-CHECK`. Swap the cable to the function generator, run
`FG-CHECK`. Neither touches the other instrument.

---

## DMM check (`dmm.py`)

The idea throughout: connect something whose value you already know, and ask
whether the meter agrees.

**You'll need:** test leads, a bench supply, one resistor.

| Step | What you do | What it checks |
|---|---|---|
| `DMM_IDENTITY` | Nothing | The DMM answers `*IDN?` |
| `DMM_SHORTED_LEADS` | Touch the leads together | The meter's zero, and the leads' own resistance |
| `DMM_OPEN_LEADS` | Separate the leads | Resistance reads over-range |
| `DMM_DC_VOLTAGE` | Connect the supply, type in its setting | The reading against a known voltage |
| `DMM_RESISTANCE` | Connect a resistor, type in its marking | The reading against a known resistance |
| `DMM_TEARDOWN` | Switch the supply off | Nothing is left live |

### The 12 V supply step

You type in what the supply is set to, so the recorded result is the
**percentage error**, not the reading. One fixed limit then covers any voltage —
12 V today, 5 V or 24 V another day, with nothing to edit.

The raw reading is recorded too, against a wide 0–60 V sanity range. That's
what catches the meter sitting on the wrong function or range, which a
percentage error on its own can hide.

Worth knowing: this compares the DMM against the *supply's front panel*, so the
supply's own error is included. A 1% disagreement doesn't tell you which of the
two is off. That's fine for a confidence check — if you later want to know the
DMM specifically, measure a reference you trust more than either.

---

## Function generator check (`fg.py`)

With no meter connected, there's a limit to what can be proven automatically.
So these tests use the instrument's own front panel as the reference: the PC
programs a waveform, and **you read the display back**.

**You'll need:** nothing but the USB cable.

| Step | What you do | What it checks |
|---|---|---|
| `FG_IDENTITY` | Nothing | The FG answers `*IDN?` |
| `FG_PROGRAMMING` | Nothing | The FG accepts a waveform and reads it back |
| `FG_DISPLAY_CHECK` | Read the display, type in what it shows | Frequency and amplitude match what was asked for |
| `FG_OUTPUT_CONTROL` | Confirm the output indicator | Enable and disable both work |
| `FG_TEARDOWN` | Nothing | All outputs off |

`FG_PROGRAMMING` is the one that matters most early on. The driver sends the
Siglent-style `C1:BSWV WVTP,SQUARE,...` that the 4050 series uses. If your unit
wants something different, the readback won't mention a square wave — and that
tells you to fix the `Scpi` class in `instruments/function_generator.py` before
trusting anything else.

`FG_OUTPUT_CONTROL` is worth proving rather than assuming: every `@with_fg` and
`@with_psu` step in every tester you write later depends on the *off* command
working to leave the bench safe.

Once you have a second USB cable, these same checks are worth redoing against
the DMM, which takes the operator out of the loop entirely.

---

## The setting that will bite you

The FG is programmed assuming a **high-Z** load. If its output load is set to
50 Ω, the display shows half the amplitude you asked for. `FG_DISPLAY_CHECK`
catches that as a −50% amplitude error and says so explicitly in the log.

`default_load = "HZ"` in `config/station.toml` is what sets this.

---

## Prompts

Instructions come through `questionary`:

```
? Connect the bench supply to the DMM: + to the V input, - to COM. Supply switched on and output enabled? (Y/n)
? What voltage is the supply set to, in volts?  12.0
```

Every prompt is safe unattended. In simulate mode, or with output piped to a
file, the prompt is skipped and the default is used with an `[auto-answered]`
line in the log — so a dry run never hangs waiting for someone. Defaults live in
`Defaults` in `config.py`; set them to the values you use most.

Ctrl+C at a prompt stops the run rather than being recorded as a failure.

---

## Simulate mode

```bash
python main.py run DMM-CHECK --simulate     # 9/9 pass
python main.py run FG-CHECK --simulate      # 10/10 pass
```

Both pass completely with nothing plugged in. Use that as the "is the framework
healthy?" check, and to try out changes to a step before you're at the bench.

The DMM steps pass a `sim_reading` to the measurement helper — a plausible value
for that particular step. It's needed because the simulated DMM is a lookup
table with one canned value per function, while these tests deliberately measure
different things through the same function (0 V shorted, 12 V from the supply).
**The argument is ignored entirely on real hardware.**

---

## After the first run

Two things to tighten:

1. **The identity limits.** `DMM_IDN` and `FG_IDN` currently accept any string
   of five characters or more, so your first run passes whatever the firmware
   reports. Find `DMM identifies as: ...` in the log and put something specific
   like `5492B` into `result_details.toml`.

2. **The accuracy limits.** `DMM_SUPPLY_ERROR` allows ±2% and
   `DMM_RESISTOR_ERROR` ±10%, which is loose. Run it a few times, look at the
   spread in `results/summary.csv`, then tighten.

## Files

| File | What's in it |
|---|---|
| `parts.toml` | The two runs, `DMM-CHECK` and `FG-CHECK` |
| `result_details.toml` | Every limit, DMM section then FG section |
| `config.py` | Prompt wording, defaults, FG waveform, timing, thresholds |
| `utils.py` | Measurement helpers, identity reporting, error maths |
| `dmm.py` | The DMM steps |
| `fg.py` | The function generator steps |
