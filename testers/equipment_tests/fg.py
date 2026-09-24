"""BK Precision 4052 checks.

Run on its own, with only the function generator connected to the PC:

    python main.py run FG-CHECK -S FG01

With no meter attached there's a limit to what can be proven automatically, so
these tests use the instrument's own front panel as the reference: the PC
programs a waveform, and you read back what the display shows. That still
catches the things that actually go wrong - a command set that doesn't match
the model, an output that never enables, a wrong unit or a factor of ten.

Once you have a second USB cable, the same checks are worth redoing against the
DMM, which removes the operator from the loop.
"""

from __future__ import annotations

from core.decorators import operator_confirm, test_step_result
from core.logger import logger
from core.runner import TestRunner
from instruments.function_generator import FunctionGenerator
from testers.equipment_tests.config import (
    EXPECTED_FG_HINTS,
    FG_CHANNEL,
    Expected,
    FG_Settings,
    Prompts,
)
from testers.equipment_tests.utils import (
    describe,
    percent_error,
    read_fg_identity,
    report_identity,
    stop_fg,
)
from utils.operator import ask_float, confirm


@test_step_result("FG_RESPONDS", "FG_IDN")
@operator_confirm(Prompts.FG_CONNECTED)
def FG_IDENTITY(runner: TestRunner):
    """Ask the function generator who it is.

    If this fails, it's usually the USB-TMC side rather than the instrument: the
    4052 needs a WinUSB driver bound to it (use Zadig) or NI-VISA installed.
    """
    idn = read_fg_identity()
    report_identity("Function generator", idn, EXPECTED_FG_HINTS)

    runner.add_result("FG_RESPONDS", bool(idn))
    runner.add_result("FG_IDN", idn)


@test_step_result("FG_ACCEPTS_SETTINGS", "FG_WAVEFORM_ECHO")
def FG_PROGRAMMING(runner: TestRunner):
    """Program a waveform, then read the FG's own description of it back.

    This is the test that catches a command set mismatch. The driver sends the
    Siglent-style `C1:BSWV WVTP,SQUARE,...` that the 4050 series uses; if this
    model wants something else, the readback won't mention a square wave and
    every other FG test becomes meaningless.
    """
    echo = ""
    accepted = False

    try:
        with FunctionGenerator(off_on_exit=True) as fg:
            fg.apply_setting(FG_Settings.DISPLAY_CHECK, channel=FG_CHANNEL, enable=False)
            echo = fg.get_waveform(channel=FG_CHANNEL)
            accepted = True
    except Exception as e:
        logger.error(f"Could not program the function generator: {e}")

    logger.info(f"FG waveform readback: {echo or '(nothing)'}")

    runner.add_result("FG_ACCEPTS_SETTINGS", accepted)
    runner.add_result("FG_WAVEFORM_ECHO", echo)


@test_step_result("FG_DISPLAY_SHAPE", "FG_DISPLAY_FREQUENCY_ERROR", "FG_DISPLAY_AMPLITUDE_ERROR")
@operator_confirm(Prompts.FG_WATCH_DISPLAY)
def FG_DISPLAY_CHECK(runner: TestRunner):
    """Program a known waveform and have the operator read the display back.

    The PC asks for a 1 kHz, 5 Vpp square wave. You type in what the front panel
    actually shows, and the error is what gets recorded. A factor of ten, a
    wrong unit, or an amplitude interpreted as peak instead of peak-to-peak all
    show up immediately.

    Note the amplitude: the FG is programmed in high-Z. If its output load is
    set to 50 ohm the display will show half what we asked for, which this
    catches as a -50% amplitude error.
    """
    programmed = FG_Settings.DISPLAY_CHECK

    with FunctionGenerator(off_on_exit=True) as fg:
        fg.apply_setting(programmed, channel=FG_CHANNEL, enable=True)

        logger.info(
            f"Programmed CH{FG_CHANNEL}: square, "
            f"{Expected.FG_FREQUENCY_HZ:.0f} Hz, {Expected.FG_AMPLITUDE_VPP:.1f} Vpp"
        )

        shape_ok = confirm(Prompts.FG_SHAPE_SHOWN, default=True)
        shown_frequency = ask_float(
            Prompts.FG_DISPLAYED_FREQUENCY, default=Expected.FG_FREQUENCY_HZ, minimum=0.0
        )
        shown_amplitude = ask_float(
            Prompts.FG_DISPLAYED_AMPLITUDE, default=Expected.FG_AMPLITUDE_VPP, minimum=0.0
        )

    frequency_error = percent_error(shown_frequency, Expected.FG_FREQUENCY_HZ)
    amplitude_error = percent_error(shown_amplitude, Expected.FG_AMPLITUDE_VPP)

    logger.info(f"Displayed frequency: {describe(shown_frequency, Expected.FG_FREQUENCY_HZ, 'Hz')}")
    logger.info(f"Displayed amplitude: {describe(shown_amplitude, Expected.FG_AMPLITUDE_VPP, 'Vpp')}")

    if amplitude_error < -40:
        logger.error(
            "The displayed amplitude is about half what was programmed. The function "
            "generator's output load is probably set to 50 ohm instead of high-Z "
            '(config/station.toml: default_load = "HZ").'
        )

    runner.add_result("FG_DISPLAY_SHAPE", shape_ok)
    runner.add_result("FG_DISPLAY_FREQUENCY_ERROR", abs(frequency_error))
    runner.add_result("FG_DISPLAY_AMPLITUDE_ERROR", abs(amplitude_error))


@test_step_result("FG_OUTPUT_ENABLES", "FG_OUTPUT_DISABLES")
def FG_OUTPUT_CONTROL(runner: TestRunner):
    """Switch the output on and off, with the operator confirming the indicator.

    Worth proving rather than assuming: every `@with_psu` / `@with_fg` step in
    every tester you write later depends on the off command working to leave the
    bench safe.
    """
    enabled = False
    disabled = False

    try:
        with FunctionGenerator(off_on_exit=True) as fg:
            fg.apply_setting(FG_Settings.DISPLAY_CHECK, channel=FG_CHANNEL, enable=False)

            fg.enable_output(FG_CHANNEL)
            enabled = confirm(Prompts.FG_OUTPUT_LIT, default=True)

            fg.disable_output(FG_CHANNEL)
            disabled = confirm(Prompts.FG_OUTPUT_DARK, default=True)
    except Exception as e:
        logger.error(f"Could not toggle the function generator output: {e}")

    runner.add_result("FG_OUTPUT_ENABLES", enabled)
    runner.add_result("FG_OUTPUT_DISABLES", disabled)


@test_step_result("FG_TEARDOWN_SAFE")
def FG_TEARDOWN(runner: TestRunner):
    """Leave every output off so nothing is driving the bench afterwards."""
    stop_fg()
    runner.add_result("FG_TEARDOWN_SAFE", True)
