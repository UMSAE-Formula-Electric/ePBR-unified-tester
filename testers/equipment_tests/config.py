"""Constants for the equipment tests.

Two instruments, checked one at a time because there's one USB cable:

    dmm.py  the BK 5492B, checked against sources you connect by hand
    fg.py   the BK 4052, checked by reading its own front panel back

Nothing here talks to both at once, so whichever one is plugged in is the one
you test.
"""

from __future__ import annotations

from instruments.function_generator import FG_Setting, Waveforms

# ---------------------------------------------------------------------------
# Operator prompts
# ---------------------------------------------------------------------------


class Prompts:
    """Everything the operator gets asked, in one place so the wording is consistent."""

    # --- DMM ---
    DMM_CONNECTED = "Is the DMM powered on and connected to this PC by USB?"
    SHORT_LEADS = "Touch the DMM's two test leads together. Shorted?"
    OPEN_LEADS = "Separate the DMM's leads so nothing is connected. Open?"

    CONNECT_SUPPLY = (
        "Connect the bench supply to the DMM: + to the V input, - to COM. "
        "Supply switched on and output enabled?"
    )
    SUPPLY_VOLTAGE = "What voltage is the supply set to, in volts?"
    DISCONNECT_SUPPLY = "Switch the supply output off and disconnect it from the DMM. Done?"

    CONNECT_RESISTOR = "Connect a known resistor across the DMM's leads. Connected?"
    RESISTOR_VALUE = "Resistor's marked value in ohms"
    RESISTOR_TOLERANCE = "Resistor's marked tolerance in percent"

    # --- Function generator ---
    FG_CONNECTED = "Is the function generator powered on and connected to this PC by USB?"
    FG_WATCH_DISPLAY = "Look at the function generator's front panel display. Ready?"
    FG_SHAPE_SHOWN = "Does the display show a SQUARE wave on CH1?"
    FG_DISPLAYED_FREQUENCY = "What frequency does the display show, in Hz?"
    FG_DISPLAYED_AMPLITUDE = "What amplitude does the display show, in volts peak-to-peak?"
    FG_OUTPUT_LIT = "Is the CH1 output indicator lit?"
    FG_OUTPUT_DARK = "Is the CH1 output indicator now off?"


class Defaults:
    """Auto-answers used when the run is unattended (simulate mode, output piped).

    These keep a dry run moving without anyone at the keyboard. They're also the
    values offered as the default at a real prompt, so set them to whatever you
    use most often.
    """

    SUPPLY_VOLTS = 12.0
    RESISTOR_OHMS = 10_000.0
    RESISTOR_TOLERANCE_PCT = 1.0


# ---------------------------------------------------------------------------
# Function generator settings
# ---------------------------------------------------------------------------

FG_CHANNEL = 1


class FG_Settings:
    OFF = FG_Setting(waveform=Waveforms.DC, low_v=0.0, high_v=0.0, channel=FG_CHANNEL)

    # The waveform the operator is asked to read off the front panel. Deliberately
    # a round number at a round amplitude, so a misread is obvious.
    DISPLAY_CHECK = FG_Setting(
        waveform=Waveforms.SQUARE,
        period=1.0 / 1000.0,  # 1 kHz
        duty_cycle=50.0,
        low_v=-2.5,
        high_v=2.5,  # 5 Vpp centred on 0
        channel=FG_CHANNEL,
        settle_s=0.3,
    )


class Expected:
    """Nominal values. How far off is acceptable lives in result_details.toml."""

    FG_FREQUENCY_HZ = 1000.0
    FG_AMPLITUDE_VPP = 5.0


# ---------------------------------------------------------------------------
# Timing and sampling
# ---------------------------------------------------------------------------


class Times:
    DMM_FUNCTION_SETTLE_S = 0.5  # after switching measurement function
    SUPPLY_SETTLE_S = 0.5  # after the operator connects a source
    FG_SETTLE_S = 0.4  # after programming a waveform
    BETWEEN_SAMPLES_S = 0.05


class Samples:
    DC = 3
    RESISTANCE = 3


class Thresholds:
    """Used to interpret a reading, as opposed to deciding pass/fail.

    The 5492B signals over-range with a very large number rather than an error,
    so "open circuit" means "bigger than this".
    """

    OPEN_CIRCUIT_OHMS = 1_000_000.0
    SHORTED_LEADS_OHMS = 5.0
    SUPPLY_SANITY_MIN_V = 0.5  # below this, the supply probably isn't on


# Substrings that suggest the right instrument answered. Only used to log a
# warning - the identity limits in result_details.toml are permissive until
# you've seen what your firmware actually reports.
EXPECTED_DMM_HINTS = ("5492", "BK", "B&K", "BK PRECISION")
EXPECTED_FG_HINTS = ("4052", "BK", "B&K", "BK PRECISION")
